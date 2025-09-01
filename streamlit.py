import os
import webbrowser
import pandas as pd
import requests
import streamlit as st

BACKEND_BASE = os.getenv("BACKEND_BASE", "http://localhost:8000/api/v1")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8502")  # returnUrl

st.set_page_config(page_title="Donation Demo", layout="wide")

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
    return r.json()["items"]

def get_disbursements(campaign_id: str):
    r = requests.get(f"{BACKEND_BASE}/disbursements", params={"campaignId": campaign_id}, timeout=20)
    r.raise_for_status()
    return r.json()

def get_my_disbursement(order_id: str):
    """내 기부에 대한 분배 내역 조회 (백엔드에서 orderId→campaign 매핑 필요)"""
    r = requests.get(f"{BACKEND_BASE}/disbursements", params={"orderId": order_id}, timeout=20)
    r.raise_for_status()
    return r.json()

# ========================
# 기부하기 페이지
# ========================
st.title("기부하기")
st.markdown("블록체인으로 투명한 기부를 해요!")
st.markdown('---')


# ✅ 결제 승인 리다이렉트 감지
qp = st.query_params
order_id = qp.get("orderId", "")
pg_token = qp.get("pg_token", "")

if order_id and pg_token:
    try:
        res = post_approve(order_id, pg_token, f"idem-{order_id}")
        if res.get("status") == "paid":
            st.success("결제 승인이 완료되었습니다.")

            # 주요 정보 요약
            st.markdown("<br><br>", unsafe_allow_html=True)
            st.markdown("### 결제 내역")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("💰 기부 금액 (KRW)", f"{res['amountWon']:,} 원")
                st.metric("⚡ 온체인 상태", res['onchainStatus'])
            with col2:
                st.metric("🔗 Tx Hash", res['txHash'][:12] + "...")
                st.metric("💎 Wei 단위", res['amountWei'])

            # Etherscan embed
            if res.get("etherscanUrl"):
                st.markdown("<br><br>", unsafe_allow_html=True)
                st.markdown("### 트랜잭션 상세 (Etherscan)")
                st.components.v1.iframe(
                    src=res["etherscanUrl"],
                    height=600,
                    scrolling=True
                )
            # ✅ 내 기부 분배 내역 표시
            st.markdown("### 내 기부 분배 내역")
            try:
                disb = get_my_disbursement(order_id)  # orderId 기반 조회
                st.markdown(f"**앵커링 트랜잭션:** [Etherscan]({disb['etherscanUrl']})")

                alloc_df = pd.DataFrame(disb["allocations"])
                st.dataframe(alloc_df, use_container_width=True)
            except Exception as e:
                st.info("분배 내역은 아직 업로드되지 않았습니다.")

            # 더 기부하기 버튼
            st.markdown("---")  # 구분선 하나 추가해서 시각적으로 아래쪽 느낌
            spacer = st.empty()

            col1, col2, col3 = st.columns([1,2,1])  # 3등분: 좌-중앙-우
            with col2:  # 중앙 영역에 버튼 넣기
                if st.button("더 기부하기", use_container_width=True):
                    st.query_params.clear()   # URL 쿼리 정리
                    st.rerun()
                
    except Exception as e:
        st.error(f"승인 처리 오류: {e}")

# 결제 입력 폼
else:
    # 캠페인 선택 (현재는 하나만)
    campaign_id = st.selectbox("캠페인 선택", ["깨끗한 물 프로젝트"])

    campaign_info = {
        "깨끗한 물 프로젝트": {
            "title": "🌱 깨끗한 물 프로젝트",
            "description": "아프리카 농촌 마을에 깨끗한 식수를 공급해요!",
            "goal_amount": 1_000_000  # 목표액 (KRW)
        }
    }
    info = campaign_info[campaign_id]

    # 기부 내역 가져오기
    items = get_donations(50)
    df = pd.DataFrame(items) if items else pd.DataFrame()

    # 모집 완료액 계산 (amountWon 합계)
    raised_amount = int(df["amountWon"].sum()) if not df.empty else 0
    # 캠페인 정보 표시
    st.markdown(f"### {info['title']}")
    st.write(info["description"])
    # 목표액 & 모금액 박스 (컬럼)
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
                <p style="font-size:18px; font-weight:bold; margin:0;">{info['goal_amount']:,} 원</p>
            </div>
            <div style="flex:1; padding-left: 20px;">
                <h4>💰 현재 모금액</h4>
                <p style="font-size:18px; font-weight:bold; margin:0;">{raised_amount:,} 원</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.markdown("<br><br>", unsafe_allow_html=True)

    # 최근 기부 내역
    st.subheader(" 최근 기부 내역")
    if df.empty:
        st.info("기부 내역이 아직 없습니다.")
    else:
        st.dataframe(df, use_container_width=True)

    st.markdown('---')

    #결제 입력창
    amount = st.number_input("금액(원)", min_value=1000, step=1000, value=10000)
    nickname = st.text_input("닉네임(선택)", value="")
    memo = st.text_input("메모(선택)", value="")
    
    # 결제 버튼 중앙 배치
    col1, col2, col3 = st.columns([1, 2, 1])  # 비율 조정 (좌:우=1:1, 가운데 2배)
    with col2:
        if st.button("기부하기", use_container_width=True):
            try:
                res = post_ready(amount, nickname, memo)
                redirect_url = res["redirectUrl"]

                # ✅ 바로 카카오 결제창 이동
                st.markdown(
                    f'<meta http-equiv="refresh" content="0; url={redirect_url}">',
                    unsafe_allow_html=True
                )
            except Exception as e:
                st.error(f"오류: {e}")
