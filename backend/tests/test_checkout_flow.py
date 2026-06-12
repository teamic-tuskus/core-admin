"""Tests for checkout and entitlement flow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from dateutil.relativedelta import relativedelta
import pytest

from app.services.catalog_service import CatalogService
from app.services.checkout_service import CheckoutService
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
        self.payments: dict[str, dict[str, Any]] = {}

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

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        for order in self.orders:
            if order["id"] == order_id:
                return {**order, "status": "created"}
        return {"id": order_id, "status": "created"}

    def fetch_payment(self, payment_id: str) -> dict[str, Any]:
        return self.payments.get(payment_id, {"id": payment_id, "status": "captured"})

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


class _DetachedPendingSubscriptionRepository(SubscriptionRepository):
    """Simulate persistence backends that return detached records on create."""

    def create_pending(self, payload: dict[str, Any]) -> dict[str, Any]:
        created = super().create_pending(payload)
        return dict(created)


class _FakeInvoiceService:
    def __init__(self) -> None:
        self.calls = 0

    def create_and_send(self, *, subscription: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {
            "razorpay_invoice_id": "inv_rzp_001",
            "zoho_invoice_id": "inv_zoho_001",
            "invoice_customer_email": subscription.get("customer_email"),
            "invoice_email_sent_at": subscription.get("updated_at"),
            "invoice_sync_status": "completed",
            "invoice_sync_error": None,
        }


class _DisabledInvoiceService:
    def create_and_send(self, *, subscription: dict[str, Any]) -> dict[str, Any]:
        _ = subscription
        raise ValueError("Invoice sync is disabled")


def _build_service() -> tuple[CheckoutService, CouponRepository, ProductRepository, SubscriptionRepository, TenantRepository]:
    product_repo = ProductRepository()
    coupon_repo = CouponRepository()
    subscription_repo = SubscriptionRepository()
    tenant_repo = TenantRepository()
    idempotency_repo = IdempotencyRepository()
    webhook_repo = WebhookEventRepository()
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
    return checkout_service, coupon_repo, product_repo, subscription_repo, tenant_repo


def test_checkout_intent_does_not_redemption_count_coupon() -> None:
    checkout_service, coupon_repo, product_repo, _subscription_repo, _tenant_repo = _build_service()

    product = product_repo.create(
        {
            "code": "core-growth",
            "name": "Core Growth",
            "description": "Growth plan",
            "modules": ["execution", "store"],
            "base_max_users": 10,
            "pricing": [{"tenure_months": 12, "amount_paise": 120000}],
        }
    )
    coupon_repo.create(
        {
            "code": "exclusive-user",
            "product_id": product["id"],
            "discount_percent": 10,
            "exclusive_for_tenant_id": "tenant_1",
            "override_max_users": 25,
            "override_modules": ["execution"],
            "override_tenure_months": 24,
            "valid_from": None,
            "valid_until": None,
            "max_redemptions": 2,
        }
    )

    response = checkout_service.create_checkout_intent(
        {
            "tenant_id": "tenant_1",
            "product_id": product["id"],
            "tenure_months": 12,
            "requested_users": 12,
            "coupon_code": "exclusive-user",
            "customer_name": "Test Tenant",
            "customer_email": "tenant@example.com",
            "idempotency_key": "idem-12345678",
        }
    )

    assert response["amount_paise"] == 108000
    assert response["entitlement_modules"] == ["execution"]
    assert response["entitlement_max_users"] == 25
    assert response["entitlement_tenure_months"] == 24
    assert coupon_repo.get_by_code("exclusive-user")["redemption_count"] == 0


def test_public_checkout_intent_derives_tenant_and_is_idempotent() -> None:
    checkout_service, _coupon_repo, product_repo, subscription_repo, _tenant_repo = _build_service()

    product = product_repo.create(
        {
            "code": "core-public",
            "name": "Core Public",
            "description": "Public plan",
            "modules": ["execution"],
            "base_max_users": 25,
            "pricing": [{"tenure_months": 12, "amount_paise": 150000}],
        }
    )

    payload = {
        "product_id": product["id"],
        "tenure_months": 12,
        "requested_users": 30,
        "coupon_code": None,
        "customer_name": "Public Buyer",
        "customer_email": "buyer@example.com",
        "customer_phone": "919999999999",
        "company_name": "Buyer Co",
        "idempotency_key": "sales-public-123456",
    }

    first = checkout_service.create_public_checkout_intent(payload)
    second = checkout_service.create_public_checkout_intent(payload)

    assert first == second

    subscription = subscription_repo.get(first["subscription_id"])
    assert subscription is not None
    assert str(subscription["tenant_id"]).startswith("lead_")
    assert len(str(subscription["tenant_id"])) == 29


def test_checkout_intent_skips_gateway_when_test_payment_bypass_enabled() -> None:
    checkout_service, _coupon_repo, product_repo, subscription_repo, _tenant_repo = _build_service()
    checkout_service.settings = SimpleNamespace(environment="staging", checkout_test_payment_bypass_enabled=True)

    product = product_repo.create(
        {
            "code": "core-bypass",
            "name": "Core Bypass",
            "description": "Bypass plan",
            "modules": ["execution"],
            "base_max_users": 25,
            "pricing": [{"tenure_months": 12, "amount_paise": 150000}],
        }
    )

    response = checkout_service.create_public_checkout_intent(
        {
            "product_id": product["id"],
            "tenure_months": 12,
            "requested_users": 30,
            "coupon_code": None,
            "customer_name": "Public Buyer",
            "customer_email": "buyer@example.com",
            "customer_phone": "919999999999",
            "company_name": "Buyer Co",
            "idempotency_key": "sales-bypass-123456",
        }
    )

    assert response["razorpay_subscription_id"].startswith("test_bypass_")
    assert checkout_service.gateway.plans == []
    assert checkout_service.gateway.gateway_subscriptions == []
    subscription = subscription_repo.get(response["subscription_id"])
    assert subscription is not None
    assert str(subscription.get("razorpay_subscription_id") or "").startswith("test_bypass_")


def test_checkout_intent_persists_gateway_subscription_id_for_detached_repository_records() -> None:
    product_repo = ProductRepository()
    coupon_repo = CouponRepository()
    subscription_repo = _DetachedPendingSubscriptionRepository()
    tenant_repo = TenantRepository()
    idempotency_repo = IdempotencyRepository()
    webhook_repo = WebhookEventRepository()
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

    product = product_repo.create(
        {
            "code": "core-detached",
            "name": "Core Detached",
            "description": "Detached plan",
            "modules": ["execution"],
            "base_max_users": 5,
            "pricing": [{"tenure_months": 12, "amount_paise": 120000}],
        }
    )

    checkout = checkout_service.create_checkout_intent(
        {
            "tenant_id": "tenant_detached",
            "product_id": product["id"],
            "tenure_months": 12,
            "requested_users": 5,
            "coupon_code": None,
            "customer_name": "Detached Tenant",
            "customer_email": "detached@example.com",
            "idempotency_key": "idem-detached-1234",
        }
    )

    saved = subscription_repo.get(checkout["subscription_id"])
    assert saved is not None
    assert saved.get("razorpay_subscription_id") == checkout["razorpay_subscription_id"]


def test_confirm_checkout_increments_redemption_and_activates_subscription(monkeypatch) -> None:
    checkout_service, coupon_repo, product_repo, _subscription_repo, _tenant_repo = _build_service()

    product = product_repo.create(
        {
            "code": "core-starter",
            "name": "Core Starter",
            "description": "Starter plan",
            "modules": ["execution"],
            "base_max_users": 5,
            "pricing": [{"tenure_months": 6, "amount_paise": 60000}],
        }
    )
    coupon_repo.create(
        {
            "code": "tenant-only",
            "product_id": product["id"],
            "discount_amount_paise": 5000,
            "exclusive_for_tenant_id": "tenant_2",
            "max_redemptions": 1,
        }
    )

    checkout = checkout_service.create_checkout_intent(
        {
            "tenant_id": "tenant_2",
            "product_id": product["id"],
            "tenure_months": 6,
            "requested_users": 5,
            "coupon_code": "tenant-only",
            "customer_name": "Tenant Two",
            "customer_email": "tenant2@example.com",
            "idempotency_key": "idem-87654321",
        }
    )

    monkeypatch.setattr("app.services.checkout_service.get_secret", lambda *_args, **_kwargs: "secret")
    activated = checkout_service.confirm_checkout(
        {
            "subscription_id": checkout["subscription_id"],
            "razorpay_subscription_id": checkout["razorpay_subscription_id"],
            "razorpay_payment_id": "pay_123",
            "razorpay_signature": "sig_123",
        }
    )

    assert activated["status"] == "active"
    assert activated["product_snapshot"]["code"] == "CORE-STARTER"
    assert activated["product_snapshot"]["pricing"][0]["amount_paise"] == 60000
    assert activated["coupon_snapshot"]["code"] == "TENANT-ONLY"
    assert coupon_repo.get_by_code("tenant-only")["redemption_count"] == 1


def test_confirm_checkout_allows_test_payment_bypass_in_non_production() -> None:
    checkout_service, _coupon_repo, product_repo, subscription_repo, _tenant_repo = _build_service()
    checkout_service.settings = SimpleNamespace(environment="staging", checkout_test_payment_bypass_enabled=True)

    product = product_repo.create(
        {
            "code": "core-bypass-confirm",
            "name": "Core Bypass Confirm",
            "description": "Bypass plan",
            "modules": ["execution"],
            "base_max_users": 25,
            "pricing": [{"tenure_months": 12, "amount_paise": 150000}],
        }
    )

    intent = checkout_service.create_checkout_intent(
        {
            "tenant_id": "tenant_bypass",
            "product_id": product["id"],
            "tenure_months": 12,
            "requested_users": 30,
            "coupon_code": None,
            "customer_name": "Bypass Buyer",
            "customer_email": "buyer@example.com",
            "customer_phone": "919999999999",
            "company_name": "Buyer Co",
            "idempotency_key": "idem-bypass-123456",
        }
    )

    activated = checkout_service.confirm_checkout(
        {
            "subscription_id": intent["subscription_id"],
            "razorpay_order_id": None,
            "razorpay_subscription_id": intent["razorpay_subscription_id"],
            "razorpay_payment_id": "test_payment_sub",
            "razorpay_signature": "test_bypass_signature",
            "test_payment_bypass": True,
        }
    )

    assert activated["status"] == "active"
    assert subscription_repo.get(intent["subscription_id"])["status"] == "active"


def test_confirm_checkout_does_not_fail_if_coupon_increment_rejected(monkeypatch) -> None:
    checkout_service, coupon_repo, product_repo, _subscription_repo, _tenant_repo = _build_service()

    product = product_repo.create(
        {
            "code": "core-resilient",
            "name": "Core Resilient",
            "description": "Resilient plan",
            "modules": ["execution"],
            "base_max_users": 5,
            "pricing": [{"tenure_months": 6, "amount_paise": 60000}],
        }
    )
    coupon_repo.create(
        {
            "code": "flaky-coupon",
            "product_id": product["id"],
            "discount_amount_paise": 5000,
            "exclusive_for_tenant_id": "tenant_resilient",
            "max_redemptions": 1,
        }
    )

    checkout = checkout_service.create_checkout_intent(
        {
            "tenant_id": "tenant_resilient",
            "product_id": product["id"],
            "tenure_months": 6,
            "requested_users": 5,
            "coupon_code": "flaky-coupon",
            "customer_name": "Tenant Resilient",
            "customer_email": "tenant-resilient@example.com",
            "idempotency_key": "idem-resilient-12345",
        }
    )

    monkeypatch.setattr("app.services.checkout_service.get_secret", lambda *_args, **_kwargs: "secret")

    def _raise_coupon_limit(_code: str) -> None:
        raise ValueError("Coupon redemption limit reached")

    monkeypatch.setattr(
        checkout_service.catalog_service,
        "increment_coupon_redemption",
        _raise_coupon_limit,
    )

    activated = checkout_service.confirm_checkout(
        {
            "subscription_id": checkout["subscription_id"],
            "razorpay_subscription_id": checkout["razorpay_subscription_id"],
            "razorpay_payment_id": "pay_resilient_123",
            "razorpay_signature": "sig_resilient_123",
        }
    )

    assert activated["status"] == "active"


def test_checkout_intent_respects_coupon_redemption_limit() -> None:
    checkout_service, coupon_repo, product_repo, _subscription_repo, _tenant_repo = _build_service()

    product = product_repo.create(
        {
            "code": "core-cap",
            "name": "Core Cap",
            "description": "Cap plan",
            "modules": ["execution"],
            "base_max_users": 5,
            "pricing": [{"tenure_months": 6, "amount_paise": 60000}],
        }
    )
    coupon = coupon_repo.create(
        {
            "code": "one-time",
            "product_id": product["id"],
            "discount_amount_paise": 5000,
            "exclusive_for_tenant_id": "tenant_cap",
            "max_redemptions": 1,
        }
    )
    coupon_repo.reserve_redemption(coupon["id"])

    with pytest.raises(ValueError, match="Coupon redemption limit reached"):
        checkout_service.create_checkout_intent(
            {
                "tenant_id": "tenant_cap",
                "product_id": product["id"],
                "tenure_months": 6,
                "requested_users": 5,
                "coupon_code": "one-time",
                "customer_name": "Tenant Cap",
                "customer_email": "tenant-cap@example.com",
                "idempotency_key": "idem-cap-123456",
            }
        )


def test_confirm_checkout_syncs_invoices_when_service_enabled(monkeypatch) -> None:
    checkout_service, _coupon_repo, product_repo, subscription_repo, _tenant_repo = _build_service()
    fake_invoice = _FakeInvoiceService()
    checkout_service.invoice_service = fake_invoice  # type: ignore[assignment]

    product = product_repo.create(
        {
            "code": "core-invoice",
            "name": "Core Invoice",
            "description": "Invoice plan",
            "modules": ["execution"],
            "base_max_users": 5,
            "pricing": [{"tenure_months": 12, "amount_paise": 120000}],
        }
    )

    checkout = checkout_service.create_checkout_intent(
        {
            "tenant_id": "tenant_invoice",
            "product_id": product["id"],
            "tenure_months": 12,
            "requested_users": 5,
            "coupon_code": None,
            "customer_name": "Tenant Invoice",
            "customer_email": "tenant-invoice@example.com",
            "idempotency_key": "idem-invoice-123456",
        }
    )

    monkeypatch.setattr("app.services.checkout_service.get_secret", lambda *_args, **_kwargs: "secret")
    activated = checkout_service.confirm_checkout(
        {
            "subscription_id": checkout["subscription_id"],
            "razorpay_subscription_id": checkout["razorpay_subscription_id"],
            "razorpay_payment_id": "pay_invoice_123",
            "razorpay_signature": "sig_invoice_123",
        }
    )

    assert activated["status"] == "active"
    assert fake_invoice.calls == 1
    saved = subscription_repo.get(checkout["subscription_id"])
    assert saved is not None
    assert saved.get("razorpay_invoice_id") == "inv_rzp_001"
    assert saved.get("zoho_invoice_id") == "inv_zoho_001"


def test_confirm_checkout_succeeds_when_invoicing_disabled(monkeypatch) -> None:
    checkout_service, _coupon_repo, product_repo, _subscription_repo, _tenant_repo = _build_service()
    checkout_service.invoice_service = _DisabledInvoiceService()  # type: ignore[assignment]

    product = product_repo.create(
        {
            "code": "core-no-invoice",
            "name": "Core No Invoice",
            "description": "No invoice plan",
            "modules": ["execution"],
            "base_max_users": 5,
            "pricing": [{"tenure_months": 12, "amount_paise": 120000}],
        }
    )

    checkout = checkout_service.create_checkout_intent(
        {
            "tenant_id": "tenant_no_invoice",
            "product_id": product["id"],
            "tenure_months": 12,
            "requested_users": 5,
            "coupon_code": None,
            "customer_name": "Tenant No Invoice",
            "customer_email": "tenant-no-invoice@example.com",
            "idempotency_key": "idem-no-invoice-123456",
        }
    )

    monkeypatch.setattr("app.services.checkout_service.get_secret", lambda *_args, **_kwargs: "secret")
    activated = checkout_service.confirm_checkout(
        {
            "subscription_id": checkout["subscription_id"],
            "razorpay_subscription_id": checkout["razorpay_subscription_id"],
            "razorpay_payment_id": "pay_no_invoice_123",
            "razorpay_signature": "sig_no_invoice_123",
        }
    )

    assert activated["status"] == "active"


def test_checkout_subscription_snapshot_stays_fixed_after_product_update(monkeypatch) -> None:
    checkout_service, coupon_repo, product_repo, _subscription_repo, _tenant_repo = _build_service()

    product = product_repo.create(
        {
            "code": "core-lock",
            "name": "Core Lock",
            "description": "Locked plan",
            "modules": ["execution", "store"],
            "base_max_users": 10,
            "pricing": [{"tenure_months": 12, "amount_paise": 120000}],
        }
    )
    coupon_repo.create(
        {
            "code": "lock-coupon",
            "product_id": product["id"],
            "discount_amount_paise": 10000,
            "exclusive_for_tenant_id": "tenant_lock",
            "max_redemptions": 1,
        }
    )

    checkout = checkout_service.create_checkout_intent(
        {
            "tenant_id": "tenant_lock",
            "product_id": product["id"],
            "tenure_months": 12,
            "requested_users": 10,
            "coupon_code": "lock-coupon",
            "customer_name": "Tenant Lock",
            "customer_email": "lock@example.com",
            "idempotency_key": "idem-lock-123",
        }
    )

    product_repo.update(
        product["id"],
        {
            "name": "Core Lock Updated",
            "modules": ["execution"],
            "base_max_users": 5,
            "pricing": [{"tenure_months": 12, "amount_paise": 999999}],
        },
    )

    monkeypatch.setattr("app.services.checkout_service.get_secret", lambda *_args, **_kwargs: "secret")
    activated = checkout_service.confirm_checkout(
        {
            "subscription_id": checkout["subscription_id"],
            "razorpay_subscription_id": checkout["razorpay_subscription_id"],
            "razorpay_payment_id": "pay_lock",
            "razorpay_signature": "sig_lock",
        }
    )

    assert activated["product_snapshot"]["name"] == "Core Lock"
    assert activated["product_snapshot"]["modules"] == ["execution", "store"]
    assert activated["product_snapshot"]["pricing"][0]["amount_paise"] == 120000
    assert activated["max_users"] == 10


def test_webhook_payment_capture_activates_subscription(monkeypatch) -> None:
    checkout_service, coupon_repo, product_repo, _subscription_repo, _tenant_repo = _build_service()
    gateway = checkout_service.gateway  # type: ignore[assignment]

    product = product_repo.create(
        {
            "code": "core-webhook",
            "name": "Core Webhook",
            "description": "Webhook plan",
            "modules": ["execution"],
            "base_max_users": 5,
            "pricing": [{"tenure_months": 6, "amount_paise": 60000}],
        }
    )
    coupon_repo.create(
        {
            "code": "webhook-coupon",
            "product_id": product["id"],
            "discount_amount_paise": 5000,
            "exclusive_for_tenant_id": "tenant_3",
            "max_redemptions": 1,
        }
    )

    checkout = checkout_service.create_checkout_intent(
        {
            "tenant_id": "tenant_3",
            "product_id": product["id"],
            "tenure_months": 6,
            "requested_users": 5,
            "coupon_code": "webhook-coupon",
            "customer_name": "Tenant Three",
            "customer_email": "tenant3@example.com",
            "idempotency_key": "idem-webhook-123",
        }
    )

    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_webhook_123",
                    "subscription_id": checkout["razorpay_subscription_id"],
                }
            }
        },
    }
    monkeypatch.setattr("app.services.checkout_service.get_secret", lambda *_args, **_kwargs: "secret")
    monkeypatch.setattr(gateway, "parse_webhook_payload", lambda _raw: payload)

    accepted = checkout_service.handle_webhook(
        event_id="evt_webhook_123",
        raw_body=b"{}",
        signature="sig_123",
    )

    assert accepted is True
    subscription = checkout_service.subscription_repo.get(checkout["subscription_id"])
    assert subscription["status"] == "active"
    assert coupon_repo.get_by_code("webhook-coupon")["redemption_count"] == 1


def test_advance_coupon_creates_new_subscription_version() -> None:
    checkout_service, _coupon_repo, product_repo, subscription_repo, tenant_repo = _build_service()

    tenant = tenant_repo.create(
        {
            "name": "Tenant Four",
            "company_email": "tenant4@example.com",
            "contact_name": "Tenant Four",
        }
    )
    product = product_repo.create(
        {
            "code": "core-versioned",
            "name": "Core Versioned",
            "description": "Versioned plan",
            "modules": ["execution"],
            "base_max_users": 10,
            "pricing": [{"tenure_months": 12, "amount_paise": 120000}],
        }
    )

    base = subscription_repo.create_pending(
        {
            "tenant_id": tenant["id"],
            "product_id": product["id"],
            "product_snapshot": {"id": product["id"], "code": product["code"], "name": product["name"]},
            "modules": ["execution"],
            "max_users": 10,
            "tenure_months": 12,
            "currency": "INR",
            "amount_paise": 120000,
            "coupon_code": None,
            "coupon_snapshot": None,
            "customer_name": "Tenant Four",
            "customer_email": "tenant4@example.com",
            "customer_phone": None,
        }
    )
    active = subscription_repo.activate(
        subscription_id=base["id"],
        start_at=base["created_at"],
        end_at=base["created_at"] + relativedelta(months=12),
        payment_id="pay_base",
    )

    checkout_service.catalog_service.create_coupon(
        {
            "code": "adv-version-1",
            "exclusive_for_tenant_id": tenant["id"],
            "override_max_users": 5,
            "override_tenure_months": 2,
            "override_modules": ["store"],
        }
    )

    current = subscription_repo.find_active_by_tenant(tenant["id"])
    assert current is not None
    assert current["id"] != active["id"]
    assert current["version"] == 2
    assert current["previous_subscription_id"] == active["id"]
    assert current["modules"] == ["execution", "store"]
    assert current["max_users"] == 15
    assert current["tenure_months"] == 14
    assert current["change_reason"] == "advance_coupon"

    historical = subscription_repo.get(active["id"])
    assert historical is not None
    assert historical["status"] == "superseded"
    assert historical["is_current"] is False
