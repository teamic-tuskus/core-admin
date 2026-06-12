from __future__ import annotations

import json
import time

import httpx

BASE = "https://api.tuskus.com/api/v1"


def main() -> None:
    out: dict[str, object] = {}
    with httpx.Client(timeout=25.0) as client:
        products_res = client.get(f"{BASE}/products")
        out["products_status"] = products_res.status_code
        products = products_res.json() if products_res.status_code == 200 else []
        out["products_count"] = len(products)

        product = next(
            (
                p
                for p in products
                if p.get("code") in {"core-growth", "core-starter", "core-enterprise"}
            ),
            products[0] if products else None,
        )
        if not product:
            out["ok"] = False
            out["stage"] = "products"
            print(json.dumps(out))
            return

        payload = {
            "tenant_id": f"smoke-tenant-{int(time.time())}",
            "product_id": product["id"],
            "tenure_months": 12,
            "requested_users": 15,
            "coupon_code": None,
            "customer_name": "Smoke Test",
            "customer_email": "app@teamic.in",
            "customer_phone": "919999999999",
            "company_name": "Smoke Test Co",
            "idempotency_key": f"smoke-{int(time.time())}",
        }
        intent_res = client.post(f"{BASE}/checkout/intent", json=payload)
        out["intent_status"] = intent_res.status_code
        if intent_res.status_code != 200:
            out["ok"] = False
            out["stage"] = "intent"
            out["error"] = intent_res.text[:300]
            print(json.dumps(out))
            return
        intent = intent_res.json()
        subscription_id = intent["subscription_id"]
        out["subscription_id"] = subscription_id

        gst_res = client.post(
            f"{BASE}/onboarding/gst/verify",
            json={"subscription_id": subscription_id, "gstin": "27ABCDE1234F1Z5"},
        )
        out["gst_status"] = gst_res.status_code
        if gst_res.status_code != 200:
            out["ok"] = False
            out["stage"] = "gst"
            out["error"] = gst_res.text[:300]
            print(json.dumps(out))
            return
        gst = gst_res.json()

        send_payload = {
            "subscription_id": subscription_id,
            "gstin": "27ABCDE1234F1Z5",
            "transaction_id": gst.get("transaction_id"),
            "email": "app@teamic.in",
            "phone": "919999999999",
        }
        otp_send_res = client.post(f"{BASE}/onboarding/otp/send", json=send_payload)
        out["otp_send_status"] = otp_send_res.status_code
        if otp_send_res.status_code != 200:
            out["ok"] = False
            out["stage"] = "otp_send"
            out["error"] = otp_send_res.text[:350]
            print(json.dumps(out))
            return
        otp_session_id = otp_send_res.json()["otp_session_id"]
        out["otp_session_id"] = otp_session_id

        otp_verify_res = client.post(
            f"{BASE}/onboarding/otp/verify",
            json={
                "otp_session_id": otp_session_id,
                "email_otp": "000000",
                "phone_otp": "000000",
            },
        )
        out["otp_verify_negative_status"] = otp_verify_res.status_code
        out["otp_verify_negative_body"] = otp_verify_res.text[:200]

    out["ok"] = True
    out["stage"] = "smoke-complete"
    print(json.dumps(out))


if __name__ == "__main__":
    main()
