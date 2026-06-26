"""API route tests for public sales endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.routes.sales as sales_routes
from app.api.v1.routes.sales import router as sales_router
from app.services.container import get_catalog_service, get_checkout_service, get_rate_limiter


class _FakeRateLimiter:
    def __init__(self, *, allowed: bool = True, retry_after_seconds: int = 0) -> None:
        self.allowed = allowed
        self.retry_after_seconds = retry_after_seconds

    def check(self, *, route_key: str, subject: str, limit: int, window_seconds: int):
        _ = (route_key, subject, limit, window_seconds)
        return type(
            "Decision",
            (),
            {"allowed": self.allowed, "retry_after_seconds": self.retry_after_seconds},
        )()


class _FakeCatalogService:
    def list_products(self) -> list[dict]:
        return [
            {
                "id": "prd_001",
                "code": "CORE-GROWTH",
                "name": "Core Growth",
                "description": "Growth plan",
                "features": "<p>Feature</p>",
                "modules": ["execution", "store"],
                "base_max_users": 50,
                "pricing": [{"tenure_months": 12, "amount_paise": 240000}],
            }
        ]


class _FakeCheckoutService:
    def create_public_checkout_intent(self, payload: dict) -> dict:
        if payload.get("product_id") == "missing":
            raise ValueError("Product not found")
        return {
            "subscription_id": "sub_sales_001",
            "razorpay_order_id": "order_sales_001",
            "currency": "INR",
            "amount_paise": 240000,
            "applied_coupon_code": payload.get("coupon_code"),
            "entitlement_modules": ["execution", "store"],
            "entitlement_max_users": 50,
            "entitlement_storage_gb": 50.0,
            "entitlement_tenure_months": int(payload["tenure_months"]),
        }

    def confirm_checkout(self, payload: dict) -> dict:
        if payload.get("razorpay_signature") == "bad_signature":
            raise ValueError("Invalid Razorpay signature")
        now = datetime.now(UTC)
        return {
            "id": payload["subscription_id"],
            "tenant_id": "lead_123",
            "product_id": "prd_001",
            "status": "active",
            "start_at": now,
            "end_at": now,
            "modules": ["execution", "store"],
            "max_users": 50,
            "tenure_months": 12,
            "currency": "INR",
            "amount_paise": 240000,
            "coupon_code": None,
            "created_at": now,
            "updated_at": now,
        }


def _build_client(*, allowed: bool = True, retry_after_seconds: int = 0) -> TestClient:
    app = FastAPI()
    app.include_router(sales_router, prefix="/api/v1")
    app.dependency_overrides[get_catalog_service] = lambda: _FakeCatalogService()
    app.dependency_overrides[get_checkout_service] = lambda: _FakeCheckoutService()
    app.dependency_overrides[get_rate_limiter] = lambda: _FakeRateLimiter(
        allowed=allowed,
        retry_after_seconds=retry_after_seconds,
    )
    return TestClient(app)


def test_list_sales_products_returns_public_rows() -> None:
    client = _build_client()

    response = client.get("/api/v1/sales/products")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == "prd_001"
    assert payload[0]["code"] == "CORE-GROWTH"


def test_sales_checkout_config_exposes_test_bypass_in_non_production(monkeypatch) -> None:
    monkeypatch.setattr(
        sales_routes,
        "get_settings",
        lambda: SimpleNamespace(environment="staging", checkout_test_payment_bypass_enabled=True),
    )
    monkeypatch.setattr(sales_routes, "get_secret", lambda _name: "")

    client = _build_client()

    response = client.get("/api/v1/sales/checkout/config")

    assert response.status_code == 200
    assert response.json() == {"razorpay_key_id": "", "test_payment_bypass_enabled": True}


def test_sales_checkout_intent_returns_checkout_details() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/sales/checkout/intent",
        json={
            "product_id": "prd_001",
            "tenure_months": 12,
            "requested_users": 40,
            "coupon_code": "WELCOME-10",
            "customer_name": "Ops User",
            "customer_email": "ops@example.com",
            "customer_phone": "919999999999",
            "company_name": "Ops Co",
            "idempotency_key": "sales-12345678",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["subscription_id"] == "sub_sales_001"
    assert payload["applied_coupon_code"] == "WELCOME-10"


def test_sales_checkout_intent_maps_errors_to_bad_request() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/sales/checkout/intent",
        json={
            "product_id": "missing",
            "tenure_months": 12,
            "requested_users": 40,
            "coupon_code": None,
            "customer_name": "Ops User",
            "customer_email": "ops@example.com",
            "customer_phone": "919999999999",
            "company_name": "Ops Co",
            "idempotency_key": "sales-12345678",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Product not found"}


def test_sales_checkout_confirm_returns_subscription() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/sales/checkout/confirm",
        json={
            "subscription_id": "sub_sales_001",
            "razorpay_order_id": "order_sales_001",
            "razorpay_payment_id": "pay_sales_001",
            "razorpay_signature": "sig_ok_123456",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "sub_sales_001"
    assert payload["status"] == "active"


def test_sales_products_returns_429_when_rate_limited() -> None:
    client = _build_client(allowed=False, retry_after_seconds=42)

    response = client.get("/api/v1/sales/products")

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many requests. Please try again shortly."}
    assert response.headers.get("retry-after") == "42"
