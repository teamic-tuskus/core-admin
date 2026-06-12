"""End-to-end sales sync integration: internal catalog changes reflected in public sales flow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes.coupons import router as coupons_router
from app.api.v1.routes.products import router as products_router
from app.api.v1.routes.sales import router as sales_router
from app.core.auth import require_coupons_access, require_products_access
from app.services.catalog_service import CatalogService
from app.services.checkout_service import CheckoutService
from app.services.container import get_catalog_service, get_checkout_service, get_rate_limiter
from app.services.payment_gateway import RazorpayGateway
from app.services.repositories import (
    CouponRepository,
    IdempotencyRepository,
    ProductRepository,
    SubscriptionRepository,
    TenantRepository,
    WebhookEventRepository,
)


class _FakeGateway(RazorpayGateway):
    def __init__(self) -> None:
        self.orders: list[dict[str, Any]] = []
        self.plans: list[dict[str, Any]] = []
        self.gateway_subscriptions: list[dict[str, Any]] = []

    def create_order(self, *, amount_paise: int, currency: str, receipt: str, notes: dict[str, str]) -> dict[str, Any]:
        order = {
            "id": f"order_{len(self.orders) + 1}",
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "notes": notes,
        }
        self.orders.append(order)
        return order

    def create_plan(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        item = {"id": f"plan_{len(self.plans) + 1}", **payload}
        self.plans.append(item)
        return item

    def create_subscription(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        item = {"id": f"sub_rzp_{len(self.gateway_subscriptions) + 1}", "status": "created", **payload}
        self.gateway_subscriptions.append(item)
        return item

    def verify_payment_signature(self, *, order_id: str, payment_id: str, received_signature: str, key_secret: str) -> bool:
        return True

    def verify_webhook_signature(self, *, raw_body: bytes, received_signature: str, webhook_secret: str) -> bool:
        return True

    @staticmethod
    def verify_checkout_signature(
        *,
        payment_id: str,
        received_signature: str,
        key_secret: str,
        order_id: str | None = None,
        subscription_id: str | None = None,
    ) -> bool:
        return True


class _FakeRateLimiter:
    def check(self, *, route_key: str, subject: str, limit: int, window_seconds: int):
        _ = (route_key, subject, limit, window_seconds)
        return type("Decision", (), {"allowed": True, "retry_after_seconds": 0})()


def _build_client() -> TestClient:
    product_repo = ProductRepository()
    coupon_repo = CouponRepository()
    subscription_repo = SubscriptionRepository()
    idempotency_repo = IdempotencyRepository()
    webhook_repo = WebhookEventRepository()
    tenant_repo = TenantRepository()

    catalog_service = CatalogService(
        product_repo=product_repo,
        coupon_repo=coupon_repo,
        subscription_repo=subscription_repo,
        tenant_repo=tenant_repo,
    )
    checkout_service = CheckoutService(
        product_repo=product_repo,
        subscription_repo=subscription_repo,
        idempotency_repo=idempotency_repo,
        webhook_repo=webhook_repo,
        catalog_service=catalog_service,
        gateway=_FakeGateway(),
        settings=SimpleNamespace(environment="local", checkout_test_payment_bypass_enabled=False),
    )

    app = FastAPI()
    app.include_router(products_router, prefix="/api/v1")
    app.include_router(coupons_router, prefix="/api/v1")
    app.include_router(sales_router, prefix="/api/v1")
    app.dependency_overrides[get_catalog_service] = lambda: catalog_service
    app.dependency_overrides[get_checkout_service] = lambda: checkout_service
    app.dependency_overrides[get_rate_limiter] = lambda: _FakeRateLimiter()
    app.dependency_overrides[require_products_access] = lambda: object()
    app.dependency_overrides[require_coupons_access] = lambda: object()
    return TestClient(app)


def test_coreadmin_catalog_syncs_to_public_sales_flow() -> None:
    client = _build_client()

    product_response = client.post(
        "/api/v1/products",
        json={
            "code": "core-sync",
            "name": "Core Sync",
            "description": "Sync verification product",
            "modules": ["execution", "store"],
            "base_max_users": 20,
            "pricing": [
                {"tenure_months": 1, "amount_paise": 20000},
                {"tenure_months": 12, "amount_paise": 200000},
            ],
        },
    )
    assert product_response.status_code == 200
    product = product_response.json()

    coupon_response = client.post(
        "/api/v1/coupons",
        json={
            "code": "sync-10",
            "product_id": product["id"],
            "discount_percent": 10,
            "max_redemptions": 5,
        },
    )
    assert coupon_response.status_code == 200
    coupon = coupon_response.json()

    public_products_response = client.get("/api/v1/sales/products")
    assert public_products_response.status_code == 200
    public_products = public_products_response.json()
    created_public_product = next((item for item in public_products if item["id"] == product["id"]), None)
    assert created_public_product is not None
    assert created_public_product["code"] == "CORE-SYNC"

    checkout_intent_response = client.post(
        "/api/v1/sales/checkout/intent",
        json={
            "product_id": product["id"],
            "tenure_months": 12,
            "requested_users": 20,
            "coupon_code": coupon["code"],
            "customer_name": "Sales Buyer",
            "customer_email": "buyer@example.com",
            "customer_phone": "919999999999",
            "company_name": "Buyer Co",
            "idempotency_key": "sales-sync-test-123456",
        },
    )
    assert checkout_intent_response.status_code == 200
    checkout_payload = checkout_intent_response.json()
    assert checkout_payload["applied_coupon_code"] == "SYNC-10"
    assert checkout_payload["amount_paise"] == 180000
