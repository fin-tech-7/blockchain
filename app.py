# app.py
import streamlit as st
import kakao_pay  # 우리가 만든 kakao_pay.py 파일을 불러옵니다!

def main():
    st.title("블록체인 기부 플랫폼")
    st.write("프로젝트의 첫걸음을 환영합니다!")

    # 기부금액 입력 필드와 버튼 생성
    amount = st.number_input("기부할 금액을 입력하세요", min_value=1000, step=1000)

    if st.button("카카오페이로 기부하기"):
        st.info("결제를 준비하고 있습니다...")

        # kakao_pay.py 파일에 있는 ready_to_pay 함수를 '호출'합니다.
        tid, next_url = kakao_pay.ready_to_pay("소중한 기부", amount)

        # 함수의 결과를 화면에 보여줍니다.
        st.success("결제 준비가 완료되었습니다!")
        st.write(f"결제 고유번호(tid): {tid}")
        st.write(f"다음 결제 URL: {next_url}")
        st.write("실제로는 이 URL로 사용자를 이동시켜야 합니다.")

if __name__ == "__main__":
    main()
    