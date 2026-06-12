"""API route tests for checkout endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes.checkout import router as checkout_router
from app.services.container import get_checkout_service


class _FakeCheckoutService:
    def __init__(self) -> None:
        self.webhook_calls: list[dict[str, object]] = []

    def create_checkout_intent(self, payload: dict) -> dict:
        if payload.get("product_id") == "missing":
            raise ValueError("Product not found")
        return {
            "subscription_id": "sub_001",
            "razorpay_order_id": "order_001",
            "currency": "INR",
            "amount_paise": 10000,
            "applied_coupon_code": payload.get("coupon_code"),
            "entitlement_modules": ["execution", "store"],
            "entitlement_max_users": 25,
            "entitlement_tenure_months": int(payload["tenure_months"]),
        }

    def confirm_checkout(self, payload: dict) -> dict:
        if payload.get("razorpay_signature") == "bad_signature":
            raise ValueError("Invalid Razorpay signature")
        now = datetime.now(UTC)
        return {
            "id": payload["subscription_id"],
            "tenant_id": "tenant_001",
            "product_id": "prod_001",
            "status": "active",
            "start_at": now,
            "end_at": now,
            "modules": ["execution"],
            "max_users": 10,
            "tenure_months": 12,
            "currency": "INR",
            "amount_paise": 10000,
            "coupon_code": None,
            "created_at": now,
            "updated_at": now,
        }

    def handle_webhook(self, *, event_id: str, raw_body: bytes, signature: str) -> bool:
        self.webhook_calls.append(
            {
                "event_id": event_id,
                "raw_body": raw_body,
                "signature": signature,
            }
        )
        return signature != "invalid_sig"


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(checkout_router, prefix="/api/v1")
    app.dependency_overrides[get_checkout_service] = lambda: _FakeCheckoutService()
    return TestClient(app)


def _build_client_with_service(service: _FakeCheckoutService) -> TestClient:
    app = FastAPI()
    app.include_router(checkout_router, prefix="/api/v1")
    app.dependency_overrides[get_checkout_service] = lambda: service
    return TestClient(app)


def test_create_checkout_intent_returns_checkout_details() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/checkout/intent",
        json={
            "tenant_id": "tenant_001",
            "product_id": "prod_001",
            "tenure_months": 12,
            "requested_users": 20,
            "coupon_code": "WELCOME-10",
            "customer_name": "Ops User",
            "customer_email": "ops@example.com",
            "idempotency_key": "idem-12345678",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["subscription_id"] == "sub_001"
    assert payload["razorpay_order_id"] == "order_001"
    assert payload["applied_coupon_code"] == "WELCOME-10"
    assert payload["entitlement_max_users"] == 25


def test_create_checkout_intent_maps_service_errors_to_bad_request() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/checkout/intent",
        json={
            "tenant_id": "tenant_001",
            "product_id": "missing",
            "tenure_months": 12,
            "requested_users": 20,
            "coupon_code": None,
            "customer_name": "Ops User",
            "customer_email": "ops@example.com",
            "idempotency_key": "idem-12345678",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Product not found"}


def test_confirm_checkout_returns_subscription_details() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/checkout/confirm",
        json={
            "subscription_id": "sub_001",
            "razorpay_order_id": "order_001",
            "razorpay_payment_id": "pay_001",
            "razorpay_signature": "sig_0012345",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "sub_001"
    assert payload["status"] == "active"
    assert payload["currency"] == "INR"


def test_confirm_checkout_maps_invalid_signature_to_bad_request() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/checkout/confirm",
        json={
            "subscription_id": "sub_001",
            "razorpay_order_id": "order_001",
            "razorpay_payment_id": "pay_001",
            "razorpay_signature": "bad_signature",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid Razorpay signature"}


def test_webhook_requires_signature_header() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/checkout/webhook",
        content='{"event":"payment.captured"}',
        headers={"X-Razorpay-Event-Id": "evt_001"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Missing webhook signature"}


def test_webhook_requires_event_id_header() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/checkout/webhook",
        content='{"event":"payment.captured"}',
        headers={"X-Razorpay-Signature": "sig_001"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Missing webhook event id"}


def test_webhook_invalid_signature_returns_bad_request() -> None:
    service = _FakeCheckoutService()
    client = _build_client_with_service(service)

    response = client.post(
        "/api/v1/checkout/webhook",
        content='{"event":"payment.captured"}',
        headers={
            "X-Razorpay-Signature": "invalid_sig",
            "X-Razorpay-Event-Id": "evt_002",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid webhook signature"}
    assert len(service.webhook_calls) == 1


def test_webhook_accepts_valid_signature_and_passes_body() -> None:
    service = _FakeCheckoutService()
    client = _build_client_with_service(service)
    body = '{"event":"payment.captured","payload":{"payment":{"entity":{"id":"pay_1"}}}}'

    response = client.post(
        "/api/v1/checkout/webhook",
        content=body,
        headers={
            "X-Razorpay-Signature": "sig_valid",
            "X-Razorpay-Event-Id": "evt_003",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert len(service.webhook_calls) == 1
    assert service.webhook_calls[0]["event_id"] == "evt_003"
    assert service.webhook_calls[0]["signature"] == "sig_valid"
    assert service.webhook_calls[0]["raw_body"] == body.encode("utf-8")
