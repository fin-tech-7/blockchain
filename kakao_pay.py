# kakao_pay.py
import requests
import uuid
import config  # 우리가 만든 config.py 파일을 불러옵니다.

# 카카오페이 API 서버 주소
KAKAO_PAY_API_HOST = "https://kapi.kakao.com"

def ready_to_pay(item_name, total_amount):
    """
    실제 카카오페이 결제 준비(ready) API를 호출하는 함수입니다.
    """
    # 1. 요청을 보내기 위한 헤더(headers) 준비
    headers = {
        "Authorization": f"KakaoAK {config.KAKAO_ADMIN_KEY}", # 어드민 키
        "Content-type": "application/x-www-form-urlencoded;charset=utf-8",
    }

    # 2. 요청에 필요한 파라미터(params) 준비
    params = {
        "cid": "TC0ONETIME",  # 테스트용 가맹점 코드. 실제 운영시에는 발급받은 코드를 사용해야 합니다.
        "partner_order_id": str(uuid.uuid4()),  # 중복되지 않는 우리 서비스의 주문번호
        "partner_user_id": "GoormDonor",      # 우리 서비스의 회원 ID
        "item_name": item_name,               # 상품명 (기부 캠페인 이름 등)
        "quantity": 1,
        "total_amount": total_amount,         # 총 결제 금액
        "tax_free_amount": 0,                 # 비과세 금액
        # 결제가 성공했을 때, 실패했을 때, 취소했을 때 돌아올 우리 서비스의 주소(URL)
        "approval_url": "http://localhost:8501", 
        "fail_url": "http://localhost:8501",
        "cancel_url": "http://localhost:8501",
    }

    # 3. 준비된 헤더와 파라미터를 가지고 카카오페이 서버에 POST 요청 보내기
    response = requests.post(f"{KAKAO_PAY_API_HOST}/v1/payment/ready", headers=headers, params=params)
    
    # 4. 응답(response)을 JSON 형태로 변환하고 필요한 정보 추출하기
    result = response.json()
    print("카카오페이 서버의 응답:", result)
    # 5. 결제 페이지로 이동할 수 있는 URL과, 다음 단계에 필요한 tid를 반환
    return result.get("tid"), result.get("next_redirect_pc_url")