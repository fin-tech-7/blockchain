import requests
import uuid
import config
import json

KAKAO_PAY_API_HOST = "https://kapi.kakao.com"

def ready_to_pay(item_name, total_amount):
    headers = {
        "Authorization": f"KakaoAK {config.KAKAO_ADMIN_KEY}",
        "Content-type": "application/x-www-form-urlencoded;charset=utf-8",
    }
    
    order_id = str(uuid.uuid4())

    params = {
        "cid": "TC0ONETIME",
        "partner_order_id": order_id,
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

    try:
        result = response.json()
    except json.JSONDecodeError:
        print("⚠️ JSON 파싱 실패:", response.text)
        return None

    if response.status_code != 200:
        print("❌ 카카오페이 결제 준비 실패:", result)
        return None

    print("카카오페이 준비 응답:", result)
    return result.get("tid"), result.get("next_redirect_pc_url"), order_id