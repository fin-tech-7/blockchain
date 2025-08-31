# kakao_pay.py
import requests
import uuid
import config

KAKAO_PAY_API_HOST = "https://kapi.kakao.com"

def ready_to_pay(item_name, total_amount):
    headers = {
        "Authorization": f"KakaoAK {config.KAKAO_ADMIN_KEY}",
        "Content-type": "application/x-www-form-urlencoded;charset=utf-8",
    }
    
    # 고유한 주문번호 생성
    order_id = str(uuid.uuid4())

    params = {
        "cid": "TC0ONETIME",
        "partner_order_id": order_id, # 생성한 주문번호 사용
        "partner_user_id": "GoormDonor",
        "item_name": item_name,
        "quantity": 1,
        "total_amount": total_amount,
        "tax_free_amount": 0,
        "approval_url": "http://localhost:8501", 
        "fail_url": "http://localhost:8501",
        "cancel_url": "http://localhost:8501",
    }

    response = requests.post(f"{KAKAO_PAY_API_HOST}/v1/payment/ready", headers=headers, params=params)
    result = response.json()
    
    print("카카오페이 준비 응답:", result)
    
    # tid, 결제 URL과 함께 주문번호(order_id)도 반환
    return result.get("tid"), result.get("next_redirect_pc_url"), order_id

def approve_payment(tid, pg_token, order_id):
    headers = {
        "Authorization": f"KakaoAK {config.KAKAO_ADMIN_KEY}",
        "Content-type": "application/x-www-form-urlencoded;charset=utf-8",
    }

    params = {
        "cid": "TC0ONETIME",
        "tid": tid,
        "partner_order_id": order_id, # '준비' 단계에서 받은 주문번호 사용
        "partner_user_id": "GoormDonor",
        "pg_token": pg_token,
    }

    response = requests.post(f"{KAKAO_PAY_API_HOST}/v1/payment/approve", headers=headers, params=params)
    result = response.json()
    
    print("카카오페이 승인 응답:", result)
    return result