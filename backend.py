# backend.py
import uuid
import json
import requests
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, String, Integer, DateTime, Text, create_engine, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# ⚠️ 카카오 관리자 키/컨트랙트 주소 등을 읽기 위해 필요
import config

# =========================================
# 외부 API 상수
# =========================================
KAKAO_PAY_API_HOST = "https://kapi.kakao.com"
ETHERSCAN_BASE = "https://sepolia.etherscan.io"  # Etherscan 베이스 (표시용)

# =========================================
# DB 초기화 (SQLite)
# =========================================
Base = declarative_base()
engine = create_engine("sqlite:///./app.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Payment(Base):
    __tablename__ = "payments"
    order_id = Column(String, primary_key=True, index=True)
    tid = Column(String, nullable=True, index=True)  # KakaoPay TID
    payment_status = Column(String, default="pending")  # pending|approved|failed
    amount_won = Column(Integer, nullable=False)
    nickname = Column(String, nullable=True)
    memo = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc))

    donation = relationship("Donation", back_populates="payment", uselist=False)


class Donation(Base):
    __tablename__ = "donations"
    order_id = Column(String, ForeignKey("payments.order_id"), primary_key=True)
    tx_hash = Column(String, index=True)
    etherscan_url = Column(String)
    onchain_status = Column(String, default="idle")  # idle|confirmed
    amount_wei = Column(String)
    block_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    payment = relationship("Payment", back_populates="donation")


Base.metadata.create_all(bind=engine)


# =========================================
# Pydantic 스키마
# =========================================
class ReadyReq(BaseModel):
    amountWon: int = Field(..., ge=1)
    nickname: Optional[str] = None
    memo: Optional[str] = None
    returnUrl: str  # 예: http://localhost:8501


class ReadyRes(BaseModel):
    orderId: str
    redirectUrl: str
    qrImage: Optional[str] = None


class ApproveReq(BaseModel):
    orderId: str
    pgToken: str


class ApproveRes(BaseModel):
    status: str
    orderId: str
    txHash: Optional[str] = None
    etherscanUrl: Optional[str] = None
    amountWon: Optional[int] = None
    amountWei: Optional[str] = None
    onchainStatus: Optional[str] = None
    # ===== 여기가 추가된 필드들 (프론트 표시용 메타) =====
    contractAddress: Optional[str] = None
    contractName: Optional[str] = None
    orderIdKeccak: Optional[str] = None   # 표시만(계산 생략), 필요 시 web3 keccak으로 채워도 됨
    explorerBase: Optional[str] = None
    function: Optional[str] = None         # "recordDonation" | "donateEthAndForward" 등


class DonationItem(BaseModel):
    orderId: str
    nickname: Optional[str]
    amountWon: int
    amountWei: Optional[str]
    memo: Optional[str]
    txHash: Optional[str]
    etherscanUrl: Optional[str]
    timestamp: str


class DonationList(BaseModel):
    items: List[DonationItem]
    nextCursor: Optional[str] = None


# =========================================
# FastAPI 앱
# =========================================
app = FastAPI(title="Donation Backend", version="1.1.0")


# =========================================
# 내부 헬퍼
# =========================================
def kakao_headers() -> dict:
    return {
        "Authorization": f"KakaoAK {config.KAKAO_ADMIN_KEY}",
        "Content-type": "application/x-www-form-urlencoded;charset=utf-8",
    }


def kakao_post(path: str, data: dict) -> dict:
    """카카오페이 POST (폼인코딩) + JSON 파싱/에러 처리"""
    url = f"{KAKAO_PAY_API_HOST}{path}"
    r = requests.post(url, headers=kakao_headers(), data=data, timeout=20)
    try:
        result = r.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail=f"Kakao response not JSON: {r.text}")

    if r.status_code != 200:
        # 카카오 에러 원문 전달
        raise HTTPException(status_code=400, detail={"kakao_error": result})
    return result


# ========================
# 1) 결제 준비 (카카오 연동)
# ========================
@app.post("/api/v1/kakaopay/ready", response_model=ReadyRes)
async def api_ready(body: ReadyReq):
    """
    - 고유 orderId 생성
    - 카카오 ready 호출 (폼 인코딩: data=)
    - 승인 리다이렉트 URL에 ?orderId=<...>를 미리 붙여서 프론트가 orderId 인지할 수 있게 함
      (카카오는 여기에 자동으로 &pg_token=...을 추가해줌)
    - DB에 Payment+tid 기록
    """
    order_id = str(uuid.uuid4())

    approval_url = f"{body.returnUrl}?orderId={order_id}"
    fail_url = f"{body.returnUrl}"
    cancel_url = f"{body.returnUrl}"

    data = {
        "cid": "TC0ONETIME",
        "partner_order_id": order_id,
        "partner_user_id": "GoormDonor",
        "item_name": "Donation",
        "quantity": 1,
        "total_amount": body.amountWon,
        "tax_free_amount": 0,
        "approval_url": approval_url,
        "fail_url": fail_url,
        "cancel_url": cancel_url,
    }

    # 카카오 ready
    ready = kakao_post("/v1/payment/ready", data)

    # DB 저장
    db = SessionLocal()
    try:
        p = Payment(
            order_id=order_id,
            tid=ready.get("tid"),
            payment_status="pending",
            amount_won=body.amountWon,
            nickname=body.nickname,
            memo=body.memo,
        )
        db.add(p)
        db.commit()
    finally:
        db.close()

    # 프론트로 결제창 URL 반환
    redirect_url = (
        ready.get("next_redirect_pc_url")
        or ready.get("next_redirect_app_url")
        or ready.get("next_redirect_mobile_url")
    )
    if not redirect_url:
        raise HTTPException(status_code=502, detail="No redirect URL from KakaoPay")

    return ReadyRes(orderId=order_id, redirectUrl=redirect_url, qrImage=None)


# ========================
# 2) 결제 승인 (카카오 연동)
# ========================
@app.post("/api/v1/kakaopay/approve", response_model=ApproveRes)
async def api_approve(
    body: ApproveReq,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """
    - DB에서 orderId로 tid 조회
    - 카카오 approve 호출
    - 온체인(Dummy) 기록 생성
    - (추가) 프론트 표시용 컨트랙트 메타 포함
    """
    db = SessionLocal()
    try:
        p: Payment = db.query(Payment).filter(Payment.order_id == body.orderId).first()
        if not p:
            raise HTTPException(status_code=400, detail="unknown orderId")

        # 이미 승인된 경우 재응답
        if p.payment_status == "approved" and p.donation:
            # 표시용 function 값 추론 (amount_wei가 0이 아니면 donateEthAndForward라고 가정)
            fn = "donateEthAndForward" if (p.donation.amount_wei and p.donation.amount_wei != "0") else "recordDonation"
            return ApproveRes(
                status="paid",
                orderId=p.order_id,
                txHash=p.donation.tx_hash,
                etherscanUrl=p.donation.etherscan_url,
                amountWon=p.amount_won,
                amountWei=p.donation.amount_wei,
                onchainStatus=p.donation.onchain_status,
                # ▼ 추가 메타
                contractAddress=getattr(config, "CONTRACT_ADDRESS", None),
                contractName="DonationSettlement",
                orderIdKeccak=None,  # 필요시 web3 keccak으로 채워도 됨
                explorerBase=ETHERSCAN_BASE,
                function=fn,
            )

        if not p.tid:
            raise HTTPException(status_code=400, detail="missing tid for this orderId")

        # 카카오 approve
        data = {
            "cid": "TC0ONETIME",
            "tid": p.tid,
            "partner_order_id": p.order_id,
            "partner_user_id": "GoormDonor",
            "pg_token": body.pgToken,
        }
        _approve = kakao_post("/v1/payment/approve", data)

        # 승인 처리
        p.payment_status = "approved"
        p.updated_at = datetime.now(timezone.utc)
        db.add(p)
        db.commit()

        # ===== 더미 온체인 기록 (원한다면 실제 Web3로 교체) =====
        tx_hash = "0xDUMMY_HASH"
        etherscan_url = f"{ETHERSCAN_BASE}/tx/{tx_hash}"
        amount_wei = str(p.amount_won * (10**9))  # 데모 변환

        d = Donation(
            order_id=p.order_id,
            tx_hash=tx_hash,
            etherscan_url=etherscan_url,
            onchain_status="confirmed",
            amount_wei=amount_wei,
            block_time=datetime.now(timezone.utc),
        )
        db.add(d)
        db.commit()

        return ApproveRes(
            status="paid",
            orderId=p.order_id,
            txHash=tx_hash,
            etherscanUrl=etherscan_url,
            amountWon=p.amount_won,
            amountWei=amount_wei,
            onchainStatus="confirmed",
            # ▼ 추가 메타
            contractAddress=getattr(config, "CONTRACT_ADDRESS", None),
            contractName="DonationSettlement",
            orderIdKeccak=None,  # 필요시 web3 keccak으로 채워도 됨
            explorerBase=ETHERSCAN_BASE,
            function="recordDonation",  # 현재 더미 온체인 경로에 맞춰 표시
        )
    finally:
        db.close()


# ========================
# 3) 기부 내역 조회
# ========================
@app.get("/api/v1/donations", response_model=DonationList)
def api_donations(limit: int = 20):
    db = SessionLocal()
    try:
        rows = (
            db.query(Payment, Donation)
            .outerjoin(Donation, Donation.order_id == Payment.order_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
            .all()
        )
        items: List[DonationItem] = []
        for p, d in rows:
            items.append(
                DonationItem(
                    orderId=p.order_id,
                    nickname=p.nickname,
                    amountWon=p.amount_won,
                    amountWei=(d.amount_wei if d else None),
                    memo=p.memo,
                    txHash=(d.tx_hash if d else None),
                    etherscanUrl=(d.etherscan_url if d else None),
                    timestamp=p.created_at.astimezone(timezone.utc).isoformat(),
                )
            )
        return DonationList(items=items, nextCursor=None)
    finally:
        db.close()
