"""End-to-end regression for catalog, checkout, webhook, and reconciliation."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes.admin import router as admin_router
from app.api.v1.routes.checkout import router as checkout_router
from app.api.v1.routes.coupons import router as coupons_router
from app.api.v1.routes.products import router as products_router
from app.core.auth import require_admin, require_coupons_access, require_products_access
from app.services.admin_container import get_admin_service
from app.services.admin_service import AdminService
from app.services.catalog_service import CatalogService
from app.services.checkout_service import CheckoutService
from app.services.container import get_catalog_service, get_checkout_service
from app.services.payment_gateway import RazorpayGateway
from app.services.repositories import (
    CouponRepository,
    IdempotencyRepository,
    PortalAccessInvitationRepository,
    ProductRepository,
    SubscriptionRepository,
    SuperAdminRepository,
    TenantRepository,
    WebhookEventRepository,
)


class _NoopEmailSender:
    def send_email(self, *, to_email: str, subject: str, body_text: str, body_html: str | None = None) -> None:
        return None


class _IntegrationGateway(RazorpayGateway):
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
        item = {"id": f"sub_rzp_{len(self.gateway_subscriptions) + 1}", "status": "active", **payload}
        self.gateway_subscriptions.append(item)
        return item

    def verify_payment_signature(self, *, order_id: str, payment_id: str, received_signature: str, key_secret: str) -> bool:
        return True

    def verify_webhook_signature(self, *, raw_body: bytes, received_signature: str, webhook_secret: str) -> bool:
        return True

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        for order in self.orders:
            if order["id"] == order_id:
                return {**order, "status": "created"}
        return {"id": order_id, "status": "created"}

    def fetch_payment(self, payment_id: str) -> dict[str, Any]:
        return {"id": payment_id, "status": "captured"}

    def fetch_subscription(self, subscription_id: str) -> dict[str, Any]:
        for item in self.gateway_subscriptions:
            if item["id"] == subscription_id:
                return {**item}
        return {"id": subscription_id, "status": "active"}

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

    def parse_webhook_payload(self, raw_body: bytes) -> dict[str, Any]:
        return json.loads(raw_body.decode("utf-8"))


def _build_client() -> TestClient:
    os.environ.setdefault("COREADMIN_GCP_PROJECT_ID", "core-admin-test")

    product_repo = ProductRepository()
    coupon_repo = CouponRepository()
    subscription_repo = SubscriptionRepository()
    idempotency_repo = IdempotencyRepository()
    webhook_repo = WebhookEventRepository()
    tenant_repo = TenantRepository()
    super_admin_repo = SuperAdminRepository()
    portal_access_invitation_repo = PortalAccessInvitationRepository()
    gateway = _IntegrationGateway()

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
        gateway=gateway,
        settings=SimpleNamespace(environment="local", checkout_test_payment_bypass_enabled=False),
    )
    admin_service = AdminService(
        tenant_repo=tenant_repo,
        subscription_repo=subscription_repo,
        super_admin_repo=super_admin_repo,
        portal_access_invitation_repo=portal_access_invitation_repo,
        email_sender=_NoopEmailSender(),  # type: ignore[arg-type]
        gateway=gateway,
    )

    app = FastAPI()
    app.include_router(products_router, prefix="/api/v1")
    app.include_router(coupons_router, prefix="/api/v1")
    app.include_router(checkout_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.dependency_overrides[get_catalog_service] = lambda: catalog_service
    app.dependency_overrides[get_checkout_service] = lambda: checkout_service
    app.dependency_overrides[get_admin_service] = lambda: admin_service
    app.dependency_overrides[require_products_access] = lambda: object()
    app.dependency_overrides[require_coupons_access] = lambda: object()
    app.dependency_overrides[require_admin] = lambda: object()
    return TestClient(app)


def test_checkout_purchase_cycle_preserves_locked_contract_snapshot(monkeypatch) -> None:
    client = _build_client()
    monkeypatch.setattr("app.services.checkout_service.get_secret", lambda *_args, **_kwargs: "secret")

    product_response = client.post(
        "/api/v1/products",
        json={
            "code": "core-growth",
            "name": "Core Growth",
            "description": "Growth plan",
            "modules": ["execution", "store"],
            "base_max_users": 10,
            "pricing": [
                {"tenure_months": 1, "amount_paise": 12000},
                {"tenure_months": 12, "amount_paise": 120000},
            ],
        },
    )
    assert product_response.status_code == 200
    product = product_response.json()

    coupon_response = client.post(
        "/api/v1/coupons",
        json={
            "code": "growth-10",
            "product_id": product["id"],
            "discount_percent": 10,
            "max_redemptions": 3,
        },
    )
    assert coupon_response.status_code == 200
    coupon = coupon_response.json()

    checkout_response = client.post(
        "/api/v1/checkout/intent",
        json={
            "tenant_id": "tenant_001",
            "product_id": product["id"],
            "tenure_months": 12,
            "requested_users": 12,
            "coupon_code": coupon["code"],
            "customer_name": "Ops User",
            "customer_email": "ops@example.com",
            "idempotency_key": "idem-purchase-123456",
        },
    )
    assert checkout_response.status_code == 200
    checkout = checkout_response.json()
    assert checkout["amount_paise"] == 108000
    assert "product_snapshot" not in checkout
    assert "coupon_snapshot" not in checkout

    updated_product_response = client.patch(
        f"/api/v1/products/{product['id']}",
        json={
            "name": "Core Growth Updated",
            "modules": ["store"],
            "base_max_users": 3,
            "pricing": [
                {"tenure_months": 1, "amount_paise": 12000},
                {"tenure_months": 12, "amount_paise": 130000},
            ],
        },
    )
    assert updated_product_response.status_code == 200
    assert updated_product_response.json()["name"] == "Core Growth Updated"

    confirm_response = client.post(
        "/api/v1/checkout/confirm",
        json={
            "subscription_id": checkout["subscription_id"],
            "razorpay_subscription_id": checkout["razorpay_subscription_id"],
            "razorpay_payment_id": "pay_purchase_123",
            "razorpay_signature": "sig_purchase_12345",
        },
    )
    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["status"] == "active"
    assert "product_snapshot" not in confirmed
    assert "coupon_snapshot" not in confirmed

    webhook_response = client.post(
        "/api/v1/checkout/webhook",
        content=json.dumps(
            {
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_purchase_123",
                            "subscription_id": checkout["razorpay_subscription_id"],
                        }
                    }
                },
            }
        ),
        headers={
            "X-Razorpay-Signature": "sig_webhook_12345",
            "X-Razorpay-Event-Id": "evt_purchase_123",
        },
    )
    assert webhook_response.status_code == 200
    assert webhook_response.json() == {"status": "accepted"}

    reconcile_response = client.post(f"/api/v1/admin/subscriptions/{checkout['subscription_id']}/reconcile")
    assert reconcile_response.status_code == 200
    reconciled = reconcile_response.json()
    assert reconciled["gateway_status"] == "captured"
    assert reconciled["product_snapshot"]["name"] == "Core Growth"
    assert reconciled["product_snapshot"]["modules"] == ["execution", "store"]
    yearly_tier = next(item for item in reconciled["product_snapshot"]["pricing"] if item["tenure_months"] == 12)
    assert yearly_tier["amount_paise"] == 120000
    assert reconciled["coupon_snapshot"]["code"] == "GROWTH-10"

    subscriptions_response = client.get("/api/v1/admin/subscriptions")
    assert subscriptions_response.status_code == 200
    subscriptions = subscriptions_response.json()
    assert len(subscriptions) == 1
    assert subscriptions[0]["product_snapshot"]["name"] == "Core Growth"
    assert subscriptions[0]["amount_paise"] == 108000
