import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, String, Integer, DateTime, Text, create_engine, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

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
    returnUrl: str


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
app = FastAPI(title="Donation Backend (Dummy)", version="1.0.0")


# ========================
# 1) 결제 준비 (더미 Ready)
# ========================
@app.post("/api/v1/kakaopay/ready", response_model=ReadyRes)
async def api_ready(body: ReadyReq):
    order_id = str(uuid.uuid4())

    # 가짜 redirect URL (카카오 결제창 → 프론트로 리다이렉트)
    redirect_url = f"{body.returnUrl}?orderId={order_id}&pg_token=FAKEPGTOKEN"

    db = SessionLocal()
    try:
        p = Payment(
            order_id=order_id,
            tid=f"T{uuid.uuid4()}",
            payment_status="pending",
            amount_won=body.amountWon,
            nickname=body.nickname,
            memo=body.memo,
        )
        db.add(p)
        db.commit()
    finally:
        db.close()
    print("DEBUG /ready orderId:", order_id)

    return ReadyRes(orderId=order_id, redirectUrl=redirect_url, qrImage=None)


# ========================
# 2) 결제 승인 (더미 Approve)
# ========================
@app.post("/api/v1/kakaopay/approve", response_model=ApproveRes)
async def api_approve(body: ApproveReq, idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    db = SessionLocal()
    print("DEBUG /approve got orderId:", body.orderId)
    try:
        p: Payment = db.query(Payment).filter(Payment.order_id == body.orderId).first()
        if not p:
            raise HTTPException(status_code=400, detail="unknown orderId")

        # 이미 승인된 경우
        if p.payment_status == "approved" and p.donation:
            return ApproveRes(
                status="paid", orderId=p.order_id,
                txHash=p.donation.tx_hash,
                etherscanUrl=p.donation.etherscan_url,
                amountWon=p.amount_won,
                amountWei=p.donation.amount_wei,
                onchainStatus=p.donation.onchain_status
            )

        # 승인 처리 (가짜)
        p.payment_status = "approved"
        p.updated_at = datetime.now(timezone.utc)
        db.add(p)
        db.commit()

        # 더미 온체인 기록
        tx_hash = "0xDUMMY_HASH"
        etherscan_url = f"https://sepolia.etherscan.io/tx/{tx_hash}"
        amount_wei = str(p.amount_won * 10**9)

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
            status="paid", orderId=p.order_id,
            txHash=tx_hash, etherscanUrl=etherscan_url,
            amountWon=p.amount_won, amountWei=amount_wei,
            onchainStatus="confirmed"
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
            items.append(DonationItem(
                orderId=p.order_id,
                nickname=p.nickname,
                amountWon=p.amount_won,
                amountWei=(d.amount_wei if d else None),
                memo=p.memo,
                txHash=(d.tx_hash if d else None),
                etherscanUrl=(d.etherscan_url if d else None),
                timestamp=p.created_at.astimezone(timezone.utc).isoformat(),
            ))
        return DonationList(items=items, nextCursor=None)
    finally:
        db.close()
