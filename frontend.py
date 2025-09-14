# frontend.py
import os
import pandas as pd
import requests
import streamlit as st

BACKEND_BASE = os.getenv("BACKEND_BASE", "http://localhost:8000/api/v1")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8501")  # returnUrl

st.set_page_config(page_title="Donation Demo", layout="wide")

# -----------------------------------------------------------------------------
# 백엔드 REST API
# -----------------------------------------------------------------------------
def post_ready(amount_won: int, nickname: str, memo: str):
    payload = {
        "amountWon": amount_won,
        "nickname": nickname or None,
        "memo": memo or None,
        "returnUrl": APP_BASE_URL,
    }
    r = requests.post(f"{BACKEND_BASE}/kakaopay/ready", json=payload, timeout=20)
    r.raise_for_status()
    return r.json()

def post_approve(order_id: str, pg_token: str, idem_key: str):
    headers = {"Idempotency-Key": idem_key}
    payload = {"orderId": order_id, "pgToken": pg_token}
    r = requests.post(f"{BACKEND_BASE}/kakaopay/approve", json=payload, headers=headers, timeout=40)
    r.raise_for_status()
    return r.json()

def get_donations(limit: int = 20):
    r = requests.get(f"{BACKEND_BASE}/donations", params={"limit": limit}, timeout=20)
    r.raise_for_status()
    return r.json().get("items", [])

# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
st.title("블록체인 기부 플랫폼")
st.markdown("블록체인으로 투명한 기부를 해요!")
st.markdown("---")

# 캠페인 정보
campaign = {
    "title": "🌱 깨끗한 물 프로젝트",
    "description": "아프리카 농촌 마을에 깨끗한 식수를 공급해요!",
    "goal_amount": 1_000_000,
}

# 최근 기부 내역/헤더
def render_campaign_header():
    try:
        items = get_donations(50)
        df = pd.DataFrame(items) if items else pd.DataFrame()
    except Exception:
        df = pd.DataFrame()

    raised_amount = int(df["amountWon"].sum()) if not df.empty else 0

    st.markdown(f"### {campaign['title']}")
    st.write(campaign["description"])
    st.markdown(
        f"""
        <div style="
            border: 1px solid #ddd;
            border-radius: 10px;
            padding: 20px;
            display: flex;
            justify-content: space-around;
            text-align: center;
            box-shadow: 0px 4px 10px rgba(0,0,0,0.05);
        ">
            <div style="flex:1; border-right: 1px solid #ddd; padding-right: 20px;">
                <h4>🎯 목표액</h4>
                <p style="font-size:18px; font-weight:bold; margin:0;">{campaign['goal_amount']:,} 원</p>
            </div>
            <div style="flex:1; padding-left: 20px;">
                <h4>💰 현재 모금액</h4>
                <p style="font-size:18px; font-weight:bold; margin:0;">{raised_amount:,} 원</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<br><br>", unsafe_allow_html=True)

    st.subheader(" 최근 기부 내역")
    if df.empty:
        st.info("기부 내역이 아직 없습니다.")
    else:
        st.dataframe(df, use_container_width=True)

# -----------------------------------------------------------------------------
# 리다이렉트 감지 및 승인 처리 (백엔드 REST 모드)
# -----------------------------------------------------------------------------
qp = st.query_params
pg_token = qp.get("pg_token", "")
order_id_q = qp.get("orderId", "")

if pg_token and order_id_q:
    st.info("결제 승인을 처리하고 있습니다...")
    try:
        res = post_approve(order_id_q, pg_token, f"idem-{order_id_q}")
        if res.get("status") == "paid":
            st.success("결제 승인이 완료되었습니다.")

            # 주요 정보 요약
            st.markdown("<br><br>", unsafe_allow_html=True)
            st.markdown("### 결제 내역")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("💰 기부 금액 (KRW)", f"{res.get('amountWon', 0):,} 원")
                st.metric("⚡ 온체인 상태", res.get("onchainStatus", ""))
            with col2:
                txh = (res.get("txHash") or "")
                st.metric("🔗 Tx Hash", (txh[:12] + "...") if txh else "-")
                st.metric("💎 Wei 단위", res.get("amountWei", "-"))

            # --- 트랜잭션 링크 ---
        if res.get("onchainError"):
            st.warning(f"온체인 오류: {res['onchainError']}")

        if res.get("etherscanUrl"):
            st.markdown("### 트랜잭션 상세 (Etherscan)")
            st.link_button("Etherscan에서 트랜잭션 보기 ↗", res["etherscanUrl"])

        # --- 스마트 콘트랙트 정보 ---
        if res.get("contractAddress"):
            st.markdown("### 스마트 콘트랙트")
            explorer = res.get("explorerBase") or "https://sepolia.etherscan.io"
            ca = res["contractAddress"]
            fn = res.get("function") or "-"
            name = res.get("contractName") or "DonationSettlement"

            cols = st.columns(2)
            with cols[0]:
                st.metric("컨트랙트", name)
                st.write(f"**주소**: [{ca}]({explorer}/address/{ca})")
                st.write(f"**함수**: `{fn}`")
            with cols[1]:
                if res.get("orderIdKeccak"):
                    st.write("**OrderId (keccak256)**")
                    st.code(res["orderIdKeccak"])

        else:
            st.error("결제 승인에 실패했습니다.")
            st.write(res)
    except Exception as e:
        st.error(f"승인 처리 오류: {e}")

# -----------------------------------------------------------------------------
# 초기 화면 (결제 준비)
# -----------------------------------------------------------------------------
else:
    render_campaign_header()
    st.markdown("---")

    amount = st.number_input("금액(원)", min_value=1000, step=1000, value=10000)
    nickname = st.text_input("닉네임(선택)", value="")
    memo = st.text_input("메모(선택)", value="")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("기부하기 (카카오페이)", use_container_width=True):
            try:
                res = post_ready(amount, nickname, memo)
                redirect_url = res["redirectUrl"]
                # 카카오 결제창으로 즉시 이동
                st.markdown(
                    f'<meta http-equiv="refresh" content="0; url={redirect_url}">',
                    unsafe_allow_html=True,
                )
            except Exception as e:
                st.error(f"오류: {e}")
