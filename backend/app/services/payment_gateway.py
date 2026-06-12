"""Razorpay payment gateway wrapper."""

from __future__ import annotations

import hmac
import json
from hashlib import sha256
from typing import Any

from app.core.secret_manager import get_secret


class RazorpayGateway:
    """Creates Razorpay orders and validates signatures."""

    def __init__(self) -> None:
        self._client: Any | None = None

    def _get_client(self):
        if self._client is None:
            import razorpay

            key_id = get_secret("razorpay-key-id")
            key_secret = get_secret("razorpay-key-secret")
            self._client = razorpay.Client(auth=(key_id, key_secret))
        return self._client

    def create_order(
        self,
        *,
        amount_paise: int,
        currency: str,
        receipt: str,
        notes: dict[str, str],
    ) -> dict[str, Any]:
        """Create Razorpay order from authoritative backend amount."""
        payload = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "notes": notes,
        }
        return self._get_client().order.create(data=payload)

    def create_plan(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a Razorpay recurring plan."""
        return self._get_client().plan.create(data=payload)

    def create_subscription(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a Razorpay subscription instance."""
        return self._get_client().subscription.create(data=payload)

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        """Fetch a Razorpay order by id."""
        return self._get_client().order.fetch(order_id)

    def fetch_payment(self, payment_id: str) -> dict[str, Any]:
        """Fetch a Razorpay payment by id."""
        return self._get_client().payment.fetch(payment_id)

    def fetch_subscription(self, subscription_id: str) -> dict[str, Any]:
        """Fetch a Razorpay subscription by id."""
        return self._get_client().subscription.fetch(subscription_id)

    def create_invoice(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a Razorpay invoice record."""
        return self._get_client().invoice.create(data=payload)

    @staticmethod
    def verify_checkout_signature(
        *,
        payment_id: str,
        received_signature: str,
        key_secret: str,
        order_id: str | None = None,
        subscription_id: str | None = None,
    ) -> bool:
        """Verify Razorpay checkout signature for order or subscription checkout."""
        candidates: list[str] = []
        if order_id:
            candidates.append(f"{order_id}|{payment_id}")
        if subscription_id:
            candidates.append(f"{payment_id}|{subscription_id}")
            candidates.append(f"{subscription_id}|{payment_id}")

        for payload in candidates:
            expected_signature = hmac.new(
                key_secret.encode("utf-8"),
                payload.encode("utf-8"),
                sha256,
            ).hexdigest()
            if hmac.compare_digest(expected_signature, received_signature):
                return True
        return False

    @staticmethod
    def verify_payment_signature(
        *,
        order_id: str,
        payment_id: str,
        received_signature: str,
        key_secret: str,
    ) -> bool:
        """Verify Razorpay checkout signature from frontend callback payload."""
        signed_payload = f"{order_id}|{payment_id}".encode("utf-8")
        expected_signature = hmac.new(
            key_secret.encode("utf-8"),
            signed_payload,
            sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_signature, received_signature)

    @staticmethod
    def verify_webhook_signature(
        *,
        raw_body: bytes,
        received_signature: str,
        webhook_secret: str,
    ) -> bool:
        """Verify Razorpay webhook signature from raw request body."""
        expected_signature = hmac.new(
            webhook_secret.encode("utf-8"),
            raw_body,
            sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_signature, received_signature)

    @staticmethod
    def parse_webhook_payload(raw_body: bytes) -> dict[str, Any]:
        """Parse webhook payload safely."""
        return json.loads(raw_body.decode("utf-8"))
