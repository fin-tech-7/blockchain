import os
import json
from urllib.parse import urlparse, parse_qs

os.environ["MOCK_KAKAO"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from backend import app  # noqa: E402


def main():
    client = TestClient(app)

    # 1) Ready
    ready_payload = {
        "amountWon": 10000,
        "nickname": "Tester",
        "memo": "Mock run",
        "returnUrl": "http://localhost:8501",
    }
    r1 = client.post("/api/v1/kakaopay/ready", json=ready_payload)
    r1.raise_for_status()
    ready = r1.json()
    print("[READY]", json.dumps(ready, ensure_ascii=False))

    # Parse redirectUrl for orderId and pg_token
    redirect = ready.get("redirectUrl", "")
    qs = parse_qs(urlparse(redirect).query)
    order_id = qs.get("orderId", [None])[0] or ready.get("orderId")
    pg_token = qs.get("pg_token", ["OFFLINE"])[0]

    # 2) Approve
    headers = {"Idempotency-Key": f"idem-{order_id}"}
    approve_payload = {"orderId": order_id, "pgToken": pg_token}
    r2 = client.post("/api/v1/kakaopay/approve", json=approve_payload, headers=headers)
    r2.raise_for_status()
    approve = r2.json()
    print("[APPROVE]", json.dumps(approve, ensure_ascii=False))

    # 3) List donations
    r3 = client.get("/api/v1/donations", params={"limit": 5})
    r3.raise_for_status()
    dons = r3.json()
    print("[DONATIONS]", json.dumps(dons, ensure_ascii=False))


if __name__ == "__main__":
    main()

