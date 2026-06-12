"""Checkout, billing, and entitlement orchestration service."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import html
import json
import logging
from threading import Thread
import time
from typing import Any

from dateutil.relativedelta import relativedelta
from google.cloud import tasks_v2

from app.core.settings import get_settings
from app.core.secret_manager import get_secret
from app.services.catalog_service import CatalogService
from app.services.email_sender import SmtpEmailSender
from app.services.invoice_service import InvoiceService
from app.services.payment_gateway import RazorpayGateway
from app.services.repositories import (
    IdempotencyRepository,
    ProductRepository,
    SubscriptionRepository,
    WebhookEventRepository,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


logger = logging.getLogger(__name__)
TEST_BYPASS_SIGNATURE = "test_bypass_signature"


class CheckoutService:
    """Creates checkout intents and activates subscriptions."""

    SUBSCRIPTION_NOT_FOUND = "Subscription not found"
    RAZORPAY_SUBSCRIPTION_TOTAL_COUNT = 100
    INVALID_ONBOARDING_LINK = "Invalid or expired onboarding link"

    def __init__(
        self,
        *,
        product_repo: ProductRepository,
        subscription_repo: SubscriptionRepository,
        idempotency_repo: IdempotencyRepository,
        webhook_repo: WebhookEventRepository,
        catalog_service: CatalogService,
        gateway: RazorpayGateway,
        invoice_service: InvoiceService | None = None,
        email_sender: SmtpEmailSender | None = None,
        currency: str = "INR",
        settings=None,
    ) -> None:
        self.product_repo = product_repo
        self.subscription_repo = subscription_repo
        self.idempotency_repo = idempotency_repo
        self.webhook_repo = webhook_repo
        self.catalog_service = catalog_service
        self.gateway = gateway
        self.invoice_service = invoice_service
        self.email_sender = email_sender
        self.currency = currency
        self.settings = settings or get_settings()

    def _is_test_payment_bypass_enabled(self) -> bool:
        return self.settings.environment != "production" and self.settings.checkout_test_payment_bypass_enabled

    def _sync_invoices_if_needed(self, *, subscription: dict) -> dict:
        if self.invoice_service is None:
            return subscription

        has_zoho_invoice = bool(str(subscription.get("zoho_invoice_id") or "").strip())
        if has_zoho_invoice and subscription.get("invoice_email_sent_at"):
            return subscription

        try:
            invoice_state = self.invoice_service.create_and_send(subscription=subscription)
        except ValueError as exc:
            reason = str(exc).strip()
            normalized = reason.lower()
            if "disabled" in normalized:
                logger.info(
                    "Invoice sync skipped during checkout confirmation",
                    extra={
                        "subscription_id": subscription.get("id"),
                        "reason": reason,
                    },
                )
                return subscription

            logger.warning(
                "Invoice sync failed during checkout confirmation",
                extra={
                    "subscription_id": subscription.get("id"),
                    "reason": reason,
                },
            )
            self._record_invoice_sync_failure(subscription=subscription, reason=reason)
            return subscription
        except Exception as exc:  # pragma: no cover - defensive runtime fallback
            logger.exception(
                "Unexpected invoice sync failure during checkout confirmation",
                extra={"subscription_id": subscription.get("id")},
            )
            self._record_invoice_sync_failure(subscription=subscription, reason=str(exc))
            return subscription

        updated = self.subscription_repo.set_invoice_state(subscription["id"], invoice_state)
        if updated is None:
            raise ValueError(self.SUBSCRIPTION_NOT_FOUND)
        return updated

    def _record_invoice_sync_failure(self, *, subscription: dict[str, Any], reason: str) -> None:
        try:
            self.subscription_repo.set_invoice_state(
                subscription["id"],
                {
                    "invoice_sync_status": "failed",
                    "invoice_sync_error": reason,
                },
            )
        except Exception:
            logger.exception(
                "Unable to persist invoice sync failure state",
                extra={"subscription_id": subscription.get("id")},
            )

    def _activate_and_finalize(self, *, subscription: dict, payment_id: str) -> dict:
        coupon_code = subscription.get("coupon_code")
        if coupon_code:
            try:
                self.catalog_service.increment_coupon_redemption(str(coupon_code))
            except ValueError as exc:
                # Do not block activation after a valid payment due to coupon state drift.
                logger.warning(
                    "Coupon redemption increment skipped during activation",
                    extra={
                        "subscription_id": subscription.get("id"),
                        "coupon_code": str(coupon_code),
                        "reason": str(exc),
                    },
                )

        start_at = _now()
        end_at = start_at + relativedelta(months=int(subscription["tenure_months"]))
        activated = self.subscription_repo.activate(
            subscription_id=subscription["id"],
            start_at=start_at,
            end_at=end_at,
            payment_id=payment_id,
        )
        self._enqueue_post_payment_tasks(subscription_id=str(activated.get("id") or ""))
        return activated

    def _enqueue_post_payment_tasks(self, *, subscription_id: str) -> None:
        normalized_id = str(subscription_id or "").strip()
        if not normalized_id:
            return

        if self.settings.post_payment_async_enabled and self.settings.post_payment_async_mode == "cloud_tasks":
            if self._enqueue_post_payment_task_cloud(subscription_id=normalized_id):
                return

        worker = Thread(
            target=self._run_post_payment_tasks,
            kwargs={"subscription_id": normalized_id},
            daemon=True,
            name=f"checkout-post-payment-{normalized_id[:12]}",
        )
        worker.start()

    def _build_post_payment_handler_url(self) -> str | None:
        configured = str(self.settings.post_payment_tasks_handler_url or "").strip()
        if configured:
            return configured
        return None

    def _enqueue_post_payment_task_cloud(self, *, subscription_id: str) -> bool:
        handler_url = self._build_post_payment_handler_url()
        if not handler_url:
            logger.warning(
                "Post-payment Cloud Tasks enqueue skipped: handler URL missing; using thread fallback",
                extra={"subscription_id": subscription_id},
            )
            return False

        try:
            token = get_secret(self.settings.post_payment_tasks_token_secret_id).strip()
            if not token:
                logger.warning(
                    "Post-payment Cloud Tasks enqueue skipped: task token missing; using thread fallback",
                    extra={"subscription_id": subscription_id},
                )
                return False

            client = tasks_v2.CloudTasksClient()
            queue_path = client.queue_path(
                self.settings.gcp_project_id,
                self.settings.post_payment_tasks_location,
                self.settings.post_payment_tasks_queue_id,
            )
            payload = json.dumps({"subscription_id": subscription_id}).encode("utf-8")
            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": handler_url,
                    "headers": {
                        "Content-Type": "application/json",
                        "X-CoreAdmin-Task-Token": token,
                    },
                    "body": payload,
                }
            }
            client.create_task(parent=queue_path, task=task)
            return True
        except Exception:
            logger.exception(
                "Post-payment Cloud Tasks enqueue failed; using thread fallback",
                extra={"subscription_id": subscription_id},
            )
            return False

    def _run_post_payment_tasks(self, *, subscription_id: str) -> None:
        self.process_post_payment_tasks(subscription_id=subscription_id)

    def process_post_payment_tasks(self, *, subscription_id: str) -> None:
        try:
            subscription = self.subscription_repo.get(subscription_id)
            if subscription is None:
                logger.warning(
                    "Post-payment task skipped: subscription missing",
                    extra={"subscription_id": subscription_id},
                )
                return

            updated = self._sync_invoices_if_needed(subscription=subscription)
            if not updated.get("onboarding_email_sent_at"):
                self._send_post_payment_onboarding_email(subscription=updated)
        except Exception:
            logger.exception(
                "Post-payment async processing failed",
                extra={"subscription_id": subscription_id},
            )

    def _resolve_product_pricing(self, product: dict, tenure_months: int) -> int:
        for price_item in product["pricing"]:
            if int(price_item["tenure_months"]) == tenure_months:
                return int(price_item["amount_paise"])
        raise ValueError("Requested tenure is not available for this product")

    @staticmethod
    def _apply_discount(base_amount: int, coupon: dict | None) -> int:
        if coupon is None:
            return base_amount

        amount = base_amount
        discount_percent = coupon.get("discount_percent")
        discount_amount = coupon.get("discount_amount_paise")

        if discount_percent is not None:
            amount = max(0, amount - int((amount * discount_percent) / 100))
        if discount_amount is not None:
            amount = max(0, amount - int(discount_amount))
        return amount

    @staticmethod
    def _resolve_entitlement(
        product: dict,
        requested_users: int | None,
        coupon: dict | None,
    ) -> tuple[list[str], int, int | None]:
        modules = list(product["modules"])
        max_users = int(product["base_max_users"])
        tenure_override: int | None = None

        if requested_users is not None:
            max_users = max(max_users, requested_users)

        if coupon is not None:
            if coupon.get("override_modules"):
                modules = list(coupon["override_modules"])
            if coupon.get("override_max_users") is not None:
                max_users = int(coupon["override_max_users"])
            if coupon.get("override_tenure_months") is not None:
                tenure_override = int(coupon["override_tenure_months"])

        return sorted(set(modules)), max_users, tenure_override

    @staticmethod
    def _build_product_snapshot(product: dict) -> dict:
        monthly = next((item for item in product.get("pricing") or [] if int(item.get("tenure_months") or 0) == 1), None)
        yearly = next((item for item in product.get("pricing") or [] if int(item.get("tenure_months") or 0) == 12), None)
        billing_cycles = None
        if monthly and yearly:
            monthly_amount = int(monthly.get("amount_paise") or 0)
            yearly_amount = int(yearly.get("amount_paise") or 0)
            if monthly_amount > 0 and yearly_amount > 0 and yearly_amount < monthly_amount * 12:
                billing_cycles = {
                    "monthly_amount_paise": monthly_amount,
                    "yearly_amount_paise": yearly_amount,
                    "yearly_discount_percent": round(((monthly_amount * 12 - yearly_amount) / (monthly_amount * 12)) * 100, 2),
                }

        return {
            "id": product["id"],
            "code": product["code"],
            "name": product["name"],
            "description": product.get("description"),
            "features": product.get("features"),
            "modules": list(product.get("modules") or []),
            "base_max_users": int(product["base_max_users"]),
            "pricing": [dict(item) for item in product.get("pricing") or []],
            "billing_cycles": billing_cycles,
            "home_view": product.get("home_view"),
            "checkout_view": product.get("checkout_view"),
        }

    @staticmethod
    def _build_coupon_snapshot(coupon: dict | None) -> dict | None:
        if coupon is None:
            return None
        return {
            "id": coupon["id"],
            "code": coupon["code"],
            "product_id": coupon.get("product_id"),
            "discount_percent": coupon.get("discount_percent"),
            "discount_amount_paise": coupon.get("discount_amount_paise"),
            "override_modules": list(coupon["override_modules"]) if coupon.get("override_modules") else None,
            "override_max_users": coupon.get("override_max_users"),
            "override_tenure_months": coupon.get("override_tenure_months"),
            "exclusive_for_tenant_id": coupon.get("exclusive_for_tenant_id"),
            "valid_from": coupon.get("valid_from"),
            "valid_until": coupon.get("valid_until"),
            "max_redemptions": coupon.get("max_redemptions"),
        }

    @staticmethod
    def _resolve_plan_interval(tenure_months: int) -> tuple[str, int]:
        if tenure_months == 12:
            return "yearly", 1
        return "monthly", max(tenure_months, 1)

    def create_checkout_intent(self, payload: dict) -> dict:
        """Create idempotent checkout intent and pending subscription."""
        operation_key = f"checkout_intent:{payload['tenant_id']}:{payload['idempotency_key']}"
        existing = self.idempotency_repo.get(operation_key)
        if existing is not None:
            return existing

        product = self.product_repo.get(payload["product_id"])
        if product is None:
            raise ValueError("Product not found")

        coupon = self.catalog_service.resolve_coupon(
            coupon_code=payload.get("coupon_code"),
            tenant_id=payload["tenant_id"],
            product_id=payload["product_id"],
        )

        base_amount = self._resolve_product_pricing(product, payload["tenure_months"])
        amount_paise = self._apply_discount(base_amount, coupon)
        if amount_paise <= 0:
            raise ValueError("Final amount must be greater than zero")

        entitlement_modules, entitlement_max_users, override_tenure = self._resolve_entitlement(
            product=product,
            requested_users=payload.get("requested_users"),
            coupon=coupon,
        )
        final_tenure = override_tenure if override_tenure is not None else payload["tenure_months"]

        pending_subscription = self.subscription_repo.create_pending(
            {
                "tenant_id": payload["tenant_id"],
                "product_id": payload["product_id"],
                "product_snapshot": self._build_product_snapshot(product),
                "modules": entitlement_modules,
                "max_users": entitlement_max_users,
                "tenure_months": final_tenure,
                "currency": self.currency,
                "amount_paise": amount_paise,
                "coupon_code": coupon["code"] if coupon else None,
                "coupon_snapshot": self._build_coupon_snapshot(coupon),
                "customer_name": payload["customer_name"],
                "customer_email": payload["customer_email"],
                "customer_phone": payload.get("customer_phone"),
                "company_name": (str(payload.get("company_name") or "").strip() or None),
                "invoice_gstin": (str(payload.get("invoice_gstin") or "").strip().upper() or None),
                "invoice_address": (str(payload.get("invoice_address") or "").strip() or None),
                "invoice_pincode": (str(payload.get("invoice_pincode") or "").strip() or None),
            }
        )

        period, interval = self._resolve_plan_interval(final_tenure)
        if self._is_test_payment_bypass_enabled():
            gateway_subscription_id = f"test_bypass_{pending_subscription['id']}"
        else:
            plan = self.gateway.create_plan(
                payload={
                    "period": period,
                    "interval": interval,
                    "item": {
                        "name": str(product.get("name") or "Core Subscription"),
                        "amount": amount_paise,
                        "currency": self.currency,
                        "description": f"{final_tenure} month recurring subscription",
                    },
                    "notes": {
                        "tenant_id": payload["tenant_id"],
                        "product_id": payload["product_id"],
                        "subscription_id": pending_subscription["id"],
                    },
                }
            )
            gateway_subscription = self.gateway.create_subscription(
                payload={
                    "plan_id": str(plan.get("id") or ""),
                    "customer_notify": 0,
                    "total_count": self.RAZORPAY_SUBSCRIPTION_TOTAL_COUNT,
                    "notes": {
                        "tenant_id": payload["tenant_id"],
                        "product_id": payload["product_id"],
                        "subscription_id": pending_subscription["id"],
                    },
                }
            )

            gateway_subscription_id = str(gateway_subscription.get("id") or "").strip()
        if not gateway_subscription_id:
            raise ValueError("Unable to create recurring subscription")

        persisted_pending = self.subscription_repo.set_razorpay_subscription_id(
            pending_subscription["id"],
            gateway_subscription_id,
        )
        if persisted_pending is None:
            raise ValueError(self.SUBSCRIPTION_NOT_FOUND)

        response = {
            "subscription_id": persisted_pending["id"],
            "razorpay_order_id": None,
            "razorpay_subscription_id": gateway_subscription_id,
            "currency": self.currency,
            "amount_paise": amount_paise,
            "applied_coupon_code": coupon["code"] if coupon else None,
            "entitlement_modules": entitlement_modules,
            "entitlement_max_users": entitlement_max_users,
            "entitlement_tenure_months": final_tenure,
        }
        self.idempotency_repo.set(operation_key, response)
        return response

    @staticmethod
    def _build_public_tenant_id(*, customer_email: str, idempotency_key: str) -> str:
        normalized_email = customer_email.strip().lower()
        normalized_key = idempotency_key.strip()
        digest = sha256(f"{normalized_email}:{normalized_key}".encode("utf-8")).hexdigest()[:24]
        return f"lead_{digest}"

    def create_public_checkout_intent(self, payload: dict) -> dict:
        """Create checkout intent for public sales flow with backend-owned tenant derivation."""
        derived_tenant_id = self._build_public_tenant_id(
            customer_email=str(payload["customer_email"]),
            idempotency_key=str(payload["idempotency_key"]),
        )
        internal_payload = {
            **payload,
            "tenant_id": derived_tenant_id,
        }
        return self.create_checkout_intent(internal_payload)

    @staticmethod
    def _validate_checkout_ids(
        *,
        stored_order_id: str | None,
        received_order_id: str | None,
        stored_gateway_subscription_id: str | None,
        received_gateway_subscription_id: str | None,
    ) -> None:
        if stored_order_id and received_order_id and stored_order_id != received_order_id:
            raise ValueError("Order ID mismatch")
        if (
            stored_gateway_subscription_id
            and received_gateway_subscription_id
            and stored_gateway_subscription_id != received_gateway_subscription_id
        ):
            raise ValueError("Subscription ID mismatch")

    @staticmethod
    def _resolve_signature_references(
        *,
        subscription: dict,
        payload: dict,
    ) -> tuple[str | None, str | None]:
        stored_order_id = str(subscription.get("razorpay_order_id") or "").strip() or None
        stored_gateway_subscription_id = str(subscription.get("razorpay_subscription_id") or "").strip() or None
        received_order_id = str(payload.get("razorpay_order_id") or "").strip() or None
        received_gateway_subscription_id = str(payload.get("razorpay_subscription_id") or "").strip() or None

        CheckoutService._validate_checkout_ids(
            stored_order_id=stored_order_id,
            received_order_id=received_order_id,
            stored_gateway_subscription_id=stored_gateway_subscription_id,
            received_gateway_subscription_id=received_gateway_subscription_id,
        )
        return received_order_id or stored_order_id, received_gateway_subscription_id or stored_gateway_subscription_id

    def confirm_checkout(self, payload: dict) -> dict:
        """Validate Razorpay signature and activate subscription."""
        item = self.subscription_repo.get(payload["subscription_id"])
        if item is None:
            raise ValueError(self.SUBSCRIPTION_NOT_FOUND)
        if item["status"] == "active":
            self._enqueue_post_payment_tasks(subscription_id=str(item.get("id") or ""))
            return item

        if payload.get("test_payment_bypass"):
            if not self._is_test_payment_bypass_enabled():
                raise ValueError("Test payment bypass is not enabled")
            return self._activate_and_finalize(subscription=item, payment_id=payload["razorpay_payment_id"])

        order_id_for_signature, subscription_id_for_signature = self._resolve_signature_references(
            subscription=item,
            payload=payload,
        )

        key_secret = get_secret("razorpay-key-secret")
        valid = self.gateway.verify_checkout_signature(
            payment_id=payload["razorpay_payment_id"],
            received_signature=payload["razorpay_signature"],
            key_secret=key_secret,
                        order_id=order_id_for_signature,
                        subscription_id=subscription_id_for_signature,
        )
        if not valid:
            raise ValueError("Invalid Razorpay signature")
        return self._activate_and_finalize(subscription=item, payment_id=payload["razorpay_payment_id"])

    @staticmethod
    def _urlsafe_b64encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    @staticmethod
    def _urlsafe_b64decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("utf-8"))

    def _build_onboarding_resume_token(self, *, subscription_id: str) -> str:
        payload = {
            "sid": subscription_id,
            "exp": int(time.time()) + 60 * 60 * 24 * 7,
            "v": 1,
        }
        payload_segment = self._urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_secret = get_secret("jwt-signing-key")
        signature = hmac.new(signing_secret.encode("utf-8"), payload_segment.encode("utf-8"), sha256).digest()
        signature_segment = self._urlsafe_b64encode(signature)
        return f"{payload_segment}.{signature_segment}"

    def _validate_onboarding_resume_signature(self, *, payload_segment: str, signature_segment: str) -> None:
        signing_secret = get_secret("jwt-signing-key")
        expected_signature = hmac.new(signing_secret.encode("utf-8"), payload_segment.encode("utf-8"), sha256).digest()
        provided_signature = self._urlsafe_b64decode(signature_segment)
        if not hmac.compare_digest(expected_signature, provided_signature):
            raise ValueError(self.INVALID_ONBOARDING_LINK)

    def _decode_onboarding_resume_payload(self, *, payload_segment: str) -> dict[str, Any]:
        try:
            payload_raw = self._urlsafe_b64decode(payload_segment)
            payload = json.loads(payload_raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError(self.INVALID_ONBOARDING_LINK) from exc

        if not isinstance(payload, dict):
            raise ValueError(self.INVALID_ONBOARDING_LINK)
        return payload

    def _resolve_subscription_from_resume_payload(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        subscription_id = str(payload.get("sid") or "").strip()
        expires_at = int(payload.get("exp") or 0)
        if not subscription_id or expires_at <= int(time.time()):
            raise ValueError(self.INVALID_ONBOARDING_LINK)

        subscription = self.subscription_repo.get(subscription_id)
        if subscription is None:
            raise ValueError("Subscription not found")
        if subscription.get("status") != "active":
            raise ValueError("Subscription must be active before onboarding")
        if not str(subscription.get("razorpay_payment_id") or "").strip():
            raise ValueError("Verified payment is required before onboarding")
        return subscription

    def resolve_onboarding_resume_token(self, *, token: str) -> dict[str, Any]:
        token_value = str(token or "").strip()
        if not token_value or "." not in token_value:
            raise ValueError(self.INVALID_ONBOARDING_LINK)

        payload_segment, signature_segment = token_value.split(".", 1)
        if not payload_segment or not signature_segment:
            raise ValueError(self.INVALID_ONBOARDING_LINK)

        self._validate_onboarding_resume_signature(
            payload_segment=payload_segment,
            signature_segment=signature_segment,
        )
        payload = self._decode_onboarding_resume_payload(payload_segment=payload_segment)
        subscription = self._resolve_subscription_from_resume_payload(payload=payload)
        subscription_id = str(subscription.get("id") or "").strip()

        return {
            "subscription_id": subscription_id,
            "customer_name": str(subscription.get("customer_name") or "").strip(),
            "customer_email": str(subscription.get("customer_email") or "").strip().lower(),
            "customer_phone": str(subscription.get("customer_phone") or "").strip() or None,
            "selected_plan": str((subscription.get("product_snapshot") or {}).get("code") or "core").strip().lower(),
            "company_name": str(subscription.get("company_name") or "").strip() or None,
        }

    def _build_onboarding_url(self, *, subscription_id: str) -> str:
        resume_token = self._build_onboarding_resume_token(subscription_id=subscription_id)
        return f"https://core.tuskus.com/app/onboarding?resume={resume_token}"

    def _build_onboarding_email_content(self, *, subscription: dict) -> tuple[str, str, str]:
        customer_name = str(subscription.get("customer_name") or "Customer").strip()
        company_name = str(subscription.get("company_name") or "your organisation").strip()
        product_name = str((subscription.get("product_snapshot") or {}).get("name") or "Core").strip()
        subscription_id = str(subscription.get("id") or "").strip()
        onboarding_url = self._build_onboarding_url(subscription_id=subscription_id)

        settings = self.email_sender.settings if self.email_sender is not None else None
        support_email = str(getattr(settings, "support_email", "") or "")
        safe_support = html.escape(support_email)
        safe_name = html.escape(customer_name)
        safe_company = html.escape(company_name)
        safe_product = html.escape(product_name)
        safe_url = html.escape(onboarding_url)
        safe_subscription_id = html.escape(subscription_id)

        subject = f"Payment confirmed for {product_name} - complete your Core onboarding"
        body_text = (
            f"Hi {customer_name},\n\n"
            f"Thank you for your payment. Your {product_name} subscription is now active.\n"
            f"Subscription ID: {subscription_id}\n\n"
            f"To activate your Core workspace for {company_name}, please complete onboarding:\n"
            f"{onboarding_url}\n\n"
            f"If you need help, contact us at {support_email}."
        )
        body_html = f"""
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#eaf0ff;font-family:'Segoe UI',Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:28px 12px;">
      <tr><td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0"
          style="width:100%;max-width:560px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 16px 48px rgba(15,23,42,0.12);">
          <tr>
            <td style="background:linear-gradient(135deg,#0f172a,#1d4ed8);padding:28px 32px;">
                            <p style="margin:0;color:#dbeafe;font-size:12px;letter-spacing:0.6px;text-transform:uppercase;font-weight:700;">Core Subscription</p>
                            <h1 style="margin:8px 0 0;color:#ffffff;font-size:24px;line-height:1.3;">Payment received. Next, complete onboarding.</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:30px 32px 12px;">
                            <p style="margin:0 0 16px;color:#1e293b;font-size:15px;line-height:1.6;">Hi <strong>{safe_name}</strong>,</p>
              <p style="margin:0 0 16px;color:#1e293b;font-size:15px;line-height:1.6;">
                                Thank you for your payment for <strong>{safe_product}</strong>. Your workspace for <strong>{safe_company}</strong> is ready to activate.
              </p>
              <p style="margin:0 0 24px;color:#334155;font-size:14px;line-height:1.6;">
                                Please verify GST details, complete OTP verification, and finish onboarding to start using Core.
              </p>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;margin:0 0 24px;">
                                <tr>
                                    <td style="padding:12px 14px;color:#334155;font-size:13px;line-height:1.5;">
                                        <strong style="color:#0f172a;">Subscription ID:</strong> {safe_subscription_id}
                                    </td>
                                </tr>
                            </table>
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr>
                                    <td style="background:#1d4ed8;border-radius:999px;">
                                        <a href="{safe_url}" style="display:inline-block;padding:14px 28px;color:#ffffff;font-size:15px;font-weight:700;text-decoration:none;">Complete onboarding</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 28px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #e2e8f0;padding-top:16px;">
                <tr>
                  <td style="color:#475569;font-size:12px;line-height:1.6;">Need help? Contact <a href="mailto:{safe_support}" style="color:#1e40af;text-decoration:underline;font-weight:700;">{safe_support}</a>.</td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""
        return subject, body_text, body_html

    def _send_onboarding_email(self, *, to_email: str, subject: str, body_text: str, body_html: str) -> None:
        self.email_sender.send_email(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )

    def _send_post_payment_onboarding_email(self, *, subscription: dict) -> None:
        """Send a post-payment email prompting the customer to proceed with onboarding."""
        if self.email_sender is None:
            return

        customer_email = str(subscription.get("customer_email") or "").strip().lower()
        if not customer_email:
            return

        try:
            settings = self.email_sender.settings
            subject, body_text, body_html = self._build_onboarding_email_content(subscription=subscription)
            self._send_onboarding_email(
                to_email=customer_email,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
            )

            test_email = str(getattr(settings, "onboarding_test_email_target", "") or "").strip().lower()
            if test_email and test_email != customer_email:
                self._send_onboarding_email(
                    to_email=test_email,
                    subject=subject,
                    body_text=body_text,
                    body_html=body_html,
                )
            self.subscription_repo.set_invoice_state(
                str(subscription.get("id") or ""),
                {
                    "onboarding_email_sent_at": _now(),
                    "onboarding_email_error": None,
                },
            )
        except Exception:
            logger.exception(
                "Failed to send post-payment onboarding email",
                extra={"subscription_id": subscription.get("id")},
            )
            try:
                self.subscription_repo.set_invoice_state(
                    str(subscription.get("id") or ""),
                    {
                        "onboarding_email_error": "Failed to send post-payment onboarding email",
                    },
                )
            except Exception:
                logger.exception(
                    "Unable to persist onboarding email failure state",
                    extra={"subscription_id": subscription.get("id")},
                )

    def _extract_webhook_ids(self, raw_body: bytes) -> tuple[str, str | None, str | None, str | None, str | None]:
        payload = self.gateway.parse_webhook_payload(raw_body)
        event_type = str(payload.get("event") or "")
        order_id = None
        payment_id = None
        gateway_subscription_id = None
        gateway_subscription_status = None

        payload_block = payload.get("payload")
        if isinstance(payload_block, dict):
            payment_block = payload_block.get("payment")
            if isinstance(payment_block, dict):
                entity = payment_block.get("entity")
                if isinstance(entity, dict):
                    order_id = entity.get("order_id")
                    payment_id = entity.get("id")
                    gateway_subscription_id = entity.get("subscription_id")

            subscription_block = payload_block.get("subscription")
            if isinstance(subscription_block, dict):
                subscription_entity = subscription_block.get("entity")
                if isinstance(subscription_entity, dict):
                    gateway_subscription_id = gateway_subscription_id or subscription_entity.get("id")
                    gateway_subscription_status = str(subscription_entity.get("status") or "").strip() or None

        return event_type, order_id, payment_id, gateway_subscription_id, gateway_subscription_status

    def _renew_active_subscription(self, *, subscription: dict, payment_id: str | None) -> None:
        end_at = subscription.get("end_at")
        now = _now()
        if end_at is not None and end_at > now:
            next_start = end_at
        else:
            next_start = now
        next_end = next_start + relativedelta(months=int(subscription["tenure_months"]))
        latest_payment_id = str(payment_id or subscription.get("razorpay_payment_id") or "")
        self.subscription_repo.activate(
            subscription_id=str(subscription["id"]),
            start_at=subscription.get("start_at") or now,
            end_at=next_end,
            payment_id=latest_payment_id,
        )
        # Force a fresh invoice sync for each successful recurring capture.
        self.subscription_repo.set_invoice_state(
            str(subscription["id"]),
            {
                "razorpay_invoice_id": "",
                "zoho_invoice_id": "",
                "zoho_invoice_number": "",
                "invoice_email_sent_at": None,
                "invoice_sync_status": "pending",
                "invoice_sync_error": None,
            },
        )

    def _apply_webhook_subscription_state(
        self,
        *,
        gateway_subscription_id: str | None,
        gateway_subscription_status: str | None,
    ) -> None:
        if not gateway_subscription_id:
            return

        subscription = self.subscription_repo.find_by_gateway_subscription_id(gateway_subscription_id)
        if subscription is None:
            return

        normalized = str(gateway_subscription_status or "").strip().lower()
        if normalized in {"cancelled", "halted", "paused", "completed"}:
            self.subscription_repo.update_status(str(subscription["id"]), "cancelled")

    def _apply_webhook_capture(
        self,
        *,
        order_id: str | None,
        payment_id: str | None,
        gateway_subscription_id: str | None,
    ) -> None:
        subscription = None
        if gateway_subscription_id:
            subscription = self.subscription_repo.find_by_gateway_subscription_id(gateway_subscription_id)
        if subscription is None and order_id:
            subscription = self.subscription_repo.find_by_order_id(order_id)
        if subscription is None:
            return
        if subscription.get("status") == "active":
            self._renew_active_subscription(subscription=subscription, payment_id=payment_id)
            self._enqueue_post_payment_tasks(subscription_id=str(subscription.get("id") or ""))
            return

        self._activate_and_finalize(subscription=subscription, payment_id=str(payment_id or ""))

    def handle_webhook(self, *, event_id: str, raw_body: bytes, signature: str) -> bool:
        """Deduplicate and validate webhook signatures."""
        if self.webhook_repo.seen(event_id):
            return True

        webhook_secret = get_secret("razorpay-webhook-secret")
        valid = self.gateway.verify_webhook_signature(
            raw_body=raw_body,
            received_signature=signature,
            webhook_secret=webhook_secret,
        )
        if not valid:
            return False

        event_type, order_id, payment_id, gateway_subscription_id, gateway_subscription_status = self._extract_webhook_ids(raw_body)
        if event_type == "payment.captured":
            self._apply_webhook_capture(
                order_id=str(order_id) if order_id else None,
                payment_id=payment_id,
                gateway_subscription_id=str(gateway_subscription_id) if gateway_subscription_id else None,
            )
        elif event_type in {"subscription.cancelled", "subscription.halted", "subscription.paused", "subscription.completed"}:
            self._apply_webhook_subscription_state(
                gateway_subscription_id=str(gateway_subscription_id) if gateway_subscription_id else None,
                gateway_subscription_status=gateway_subscription_status,
            )

        self.webhook_repo.mark(event_id)
        return True
