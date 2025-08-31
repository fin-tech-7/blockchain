# app.py
import streamlit as st
import kakao_pay

# 세션 상태 초기화
if 'tid' not in st.session_state:
    st.session_state.tid = None
if 'order_id' not in st.session_state:
    st.session_state.order_id = None

def main():
    st.title("블록체인 기부 플랫폼")

    query_params = st.query_params
    pg_token = query_params.get("pg_token")

    # Case 2: 결제 성공 후 돌아온 경우
    if pg_token:
        st.info("결제를 승인하고 있습니다...")
        tid = st.session_state.tid
        order_id = st.session_state.order_id
        
        if not tid or not order_id:
            st.error("결제 정보가 세션에 존재하지 않습니다. 처음부터 다시 시도해주세요.")
            return

        payment_result = kakao_pay.approve_payment(tid, pg_token, order_id)
        
        if payment_result and payment_result.get("amount"):
            st.success("🎉 결제가 성공적으로 완료되었습니다!")
            st.write("결제 완료 정보:")
            st.json(payment_result)
        else:
            st.error("결제 승인에 실패했습니다. 카카오페이 서버로부터 받은 응답을 확인해주세요.")
            st.write("오류 내용:")
            st.json(payment_result)

        st.session_state.tid = None
        st.session_state.order_id = None
        st.query_params.clear()

    # Case 1: 처음 페이지에 들어온 경우
    else:
        st.write("프로젝트의 첫걸음을 환영합니다!")
        amount = st.number_input("기부할 금액을 입력하세요", min_value=1000, step=1000)
        
        if st.button("카카오페이로 기부하기"):
            st.info("결제를 준비하고 있습니다...")
            
            tid, next_url, order_id = kakao_pay.ready_to_pay("소중한 기부", amount)
            
            if tid:
                st.session_state.tid = tid
                st.session_state.order_id = order_id
                
                st.success("결제 준비가 완료되었습니다. 아래 링크를 눌러 결제를 계속 진행해주세요.")
                # st.link_button 대신 st.markdown을 사용하여 현재 탭에서 링크가 열리도록 합니다.
                st.markdown(f'<a href="{next_url}" target="_self">카카오페이로 결제하러 가기</a>', unsafe_allow_html=True)
            else:
                st.error("결제 준비에 실패했습니다. 다시 시도해주세요.")

if __name__ == "__main__":
    main()