# backend.py
import uuid
import json
import os
import requests
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
    onchainError: Optional[str] = None
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
app = FastAPI(title="Donation Backend", version="1.2.0")

# CORS for Streamlit frontend (localhost:8501)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# 오프라인(모의) 모드: 외부 카카오 API 없이 로컬에서 흐름 테스트
OFFLINE_MODE = (os.getenv("MOCK_KAKAO", "0") == "1") or (os.getenv("OFFLINE", "0") == "1")

def ensure_0x(hexstr: str) -> str:
    if not isinstance(hexstr, str):
        return hexstr
    return hexstr if hexstr.startswith("0x") else ("0x" + hexstr)

def explorer_base_for_chain() -> str:
    try:
        from web3 import Web3
        rpc = getattr(config, "RPC_URL", None)
        if not rpc:
            return ETHERSCAN_BASE
        w3 = Web3(Web3.HTTPProvider(rpc))
        if not w3.is_connected():
            return ETHERSCAN_BASE
        cid = w3.eth.chain_id
        # minimal mapping
        if cid == 1:
            return "https://etherscan.io"
        if cid == 11155111:
            return "https://sepolia.etherscan.io"
        if cid == 17000 or cid == 17001:
            return "https://holesky.etherscan.io"
        return ETHERSCAN_BASE
    except Exception:
        return ETHERSCAN_BASE

# =========================================
# Web3 (실 온체인 기록)
# =========================================
def try_onchain_record(amount_wei: int, memo: str) -> tuple[Optional[str], Optional[str]]:
    """recordDonation(amount, memo) 호출을 시도.
    Returns (tx_hash_hex, error_message). 성공 시 error_message는 None.
    """
    try:
        from web3 import Web3

        rpc = getattr(config, "RPC_URL", None)
        contract_addr = getattr(config, "CONTRACT_ADDRESS", None)
        priv = getattr(config, "WALLET_PRIVATE_KEY", None)
        abi = getattr(config, "CONTRACT_ABI", None)
        if not rpc:
            return None, "RPC_URL missing"
        if not contract_addr:
            return None, "CONTRACT_ADDRESS missing"
        if not priv:
            return None, "WALLET_PRIVATE_KEY missing"
        if not abi:
            return None, "CONTRACT_ABI missing"

        w3 = Web3(Web3.HTTPProvider(rpc))
        if not w3.is_connected():
            return None, "Web3 not connected (check RPC_URL/key)"

        # Basic sanity: contract code exists
        caddr = Web3.to_checksum_address(contract_addr)
        code = w3.eth.get_code(caddr)
        if not code or code == b"":
            return None, "No contract code at address (wrong network?)"

        # Derive account and build EIP-1559 tx (fallback to legacy)
        try:
            acct = w3.eth.account.from_key(priv)
        except Exception as e:
            return None, f"Invalid private key: {e}"

        chain_id = w3.eth.chain_id
        base = None
        try:
            base = w3.eth.get_block("latest").get("baseFeePerGas")
        except Exception:
            base = None

        tx_params = {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "gas": 300000,
            "chainId": chain_id,
        }
        if base:
            prio = w3.to_wei(1, "gwei")
            tx_params.update({
                "maxPriorityFeePerGas": prio,
                "maxFeePerGas": base * 2 + prio,
            })
        else:
            tx_params.update({"gasPrice": w3.eth.gas_price})

        tx = w3.eth.contract(address=caddr, abi=abi).functions.recordDonation(
            int(amount_wei), str(memo or "")
        ).build_transaction(tx_params)

        signed = w3.eth.account.sign_transaction(tx, private_key=priv)
        # web3.py v5/6 -> rawTransaction, v7 -> raw_transaction
        raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
        if raw is None:
            return None, "SignedTransaction missing raw transaction bytes (web3 version mismatch)"
        tx_hash = w3.eth.send_raw_transaction(raw)
        return tx_hash.hex(), None
    except Exception as e:
        return None, str(e)


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

    # 오프라인 모드면 외부 호출 없이 바로 리다이렉트 시뮬레이션
    if OFFLINE_MODE:
        db = SessionLocal()
        try:
            p = Payment(
                order_id=order_id,
                tid="OFFLINE_TID",
                payment_status="pending",
                amount_won=body.amountWon,
                nickname=body.nickname,
                memo=body.memo,
            )
            db.add(p)
            db.commit()
        finally:
            db.close()

        redirect_url = f"{approval_url}&pg_token=OFFLINE"
        return ReadyRes(orderId=order_id, redirectUrl=redirect_url, qrImage=None)

    # 온라인(실서비스) 모드: 카카오 ready 호출
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

        # 오프라인 모드가 아니면 카카오 approve 호출 및 tid 검증
        if not OFFLINE_MODE:
            if not p.tid:
                raise HTTPException(status_code=400, detail="missing tid for this orderId")
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

        # ===== 온체인 기록 (오프라인이면 더미, 온라인이면 Web3 시도) =====
        amount_wei = str(p.amount_won * (10**9))  # KRW -> (데모)Wei 변환
        onchain_error = None
        if OFFLINE_MODE:
            tx_hash = "0xDUMMY_HASH"
            onchain_status = "confirmed"
        else:
            txh, err = try_onchain_record(int(amount_wei), p.memo or "")
            if txh:
                tx_hash = txh
                onchain_status = "submitted"
            else:
                tx_hash = "0xERROR_ONCHAIN"
                onchain_status = "error"
                onchain_error = err
        tx_hash = ensure_0x(tx_hash)
        etherscan_url = f"{explorer_base_for_chain()}/tx/{tx_hash}"

        d = Donation(
            order_id=p.order_id,
            tx_hash=tx_hash,
            etherscan_url=etherscan_url,
            onchain_status=onchain_status,
            amount_wei=amount_wei,
            block_time=datetime.now(timezone.utc),
        )
        db.add(d)
        db.commit()

        res = ApproveRes(
            status="paid",
            orderId=p.order_id,
            txHash=ensure_0x(tx_hash),
            etherscanUrl=etherscan_url,
            amountWon=p.amount_won,
            amountWei=amount_wei,
            onchainStatus=onchain_status,
            onchainError=onchain_error,
            # ▼ 추가 메타
            contractAddress=getattr(config, "CONTRACT_ADDRESS", None),
            contractName="DonationSettlement",
            orderIdKeccak=None,  # 필요시 web3 keccak으로 채워도 됨
            explorerBase=explorer_base_for_chain(),
            function="recordDonation",  # 현재 더미 온체인 경로에 맞춰 표시
        )
        return res
    finally:
        db.close()


@app.get("/api/v1/web3/health")
def web3_health():
    try:
        from web3 import Web3
        rpc = getattr(config, "RPC_URL", None)
        caddr = getattr(config, "CONTRACT_ADDRESS", None)
        priv = getattr(config, "WALLET_PRIVATE_KEY", None)
        abi = getattr(config, "CONTRACT_ABI", None)
        if not rpc:
            raise RuntimeError("RPC_URL missing")
        w3 = Web3(Web3.HTTPProvider(rpc))
        ok = w3.is_connected()
        chain = w3.eth.chain_id if ok else None
        acct = None
        if priv:
            try:
                acct = w3.eth.account.from_key(priv).address
            except Exception:
                acct = "invalid_private_key"
        has_code = None
        if caddr and ok:
            try:
                has_code = (w3.eth.get_code(Web3.to_checksum_address(caddr)) != b"")
            except Exception:
                has_code = False
        return {
            "connected": ok,
            "chainId": chain,
            "account": acct,
            "hasContractCode": has_code,
            "abiLoaded": bool(abi),
            "explorerBase": explorer_base_for_chain(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
