"""Firestore-backed repositories for CoreAdmin domain entities."""

from __future__ import annotations

from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from hashlib import sha256
import secrets
import string
from typing import Any
from uuid import uuid4

from google.cloud import firestore
from google.cloud.firestore_v1 import Increment

from app.core.firebase import get_firestore_client


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return _now()


def _generate_public_tenant_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


class FirestoreProductRepository:
    """Products persisted in Firestore."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        product_id = f"prd_{uuid4().hex}"
        code = str(payload["code"]).upper()
        now = _now()
        batch = self.db.batch()
        index_ref = self.db.collection("product_code_index").document(code)
        product_ref = self.db.collection("products").document(product_id)
        if index_ref.get().exists:
            raise ValueError("Product code already exists")
        batch.set(index_ref, {"product_id": product_id, "created_at": now})
        batch.set(
            product_ref,
            {
                "id": product_id,
                **payload,
                "code": code,
                "created_at": now,
                "updated_at": now,
            },
        )
        batch.commit()
        return self.get(product_id) or {}

    def list(self) -> list[dict[str, Any]]:
        docs = self.db.collection("products").order_by("created_at").stream()
        return [self._normalize(doc.to_dict() or {}) for doc in docs]

    def get(self, product_id: str) -> dict[str, Any] | None:
        snap = self.db.collection("products").document(product_id).get()
        if not snap.exists:
            return None
        return self._normalize(snap.to_dict() or {})

    def update(self, product_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get(product_id)
        if current is None:
            return None

        data = dict(payload)
        now = _now()
        product_ref = self.db.collection("products").document(product_id)
        old_code = str(current["code"]).upper()

        if "code" in data and data["code"] is not None:
            new_code = str(data["code"]).upper()
            data["code"] = new_code
            if new_code != old_code:
                new_index_ref = self.db.collection("product_code_index").document(new_code)
                if new_index_ref.get().exists:
                    raise ValueError("Product code already exists")
                old_index_ref = self.db.collection("product_code_index").document(old_code)
                batch = self.db.batch()
                batch.delete(old_index_ref)
                batch.set(new_index_ref, {"product_id": product_id, "created_at": now})
                batch.update(product_ref, {**data, "updated_at": now})
                batch.commit()
                return self.get(product_id)

        product_ref.update({**data, "updated_at": now})
        return self.get(product_id)

    def delete(self, product_id: str) -> bool:
        current = self.get(product_id)
        if current is None:
            return False

        code = str(current["code"]).upper()
        batch = self.db.batch()
        batch.delete(self.db.collection("products").document(product_id))
        batch.delete(self.db.collection("product_code_index").document(code))
        batch.commit()
        return True

    @staticmethod
    def _normalize(data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data)
        data["created_at"] = _ts(data.get("created_at"))
        data["updated_at"] = _ts(data.get("updated_at"))
        return data


class FirestoreCouponRepository:
    """Coupons persisted in Firestore."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        coupon_id = f"cpn_{uuid4().hex}"
        code = str(payload["code"]).upper()
        now = _now()
        batch = self.db.batch()
        index_ref = self.db.collection("coupon_code_index").document(code)
        coupon_ref = self.db.collection("coupons").document(coupon_id)
        if index_ref.get().exists:
            raise ValueError("Coupon code already exists")
        batch.set(index_ref, {"coupon_id": coupon_id, "created_at": now})
        batch.set(
            coupon_ref,
            {
                "id": coupon_id,
                **payload,
                "code": code,
                "status": "active",
                "paused_at": None,
                "deleted_at": None,
                "redemption_count": 0,
                "created_at": now,
                "updated_at": now,
            },
        )
        batch.commit()
        return self.get_by_id(coupon_id) or {}

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        index = self.db.collection("coupon_code_index").document(code.upper()).get()
        if not index.exists:
            return None
        coupon_id = (index.to_dict() or {}).get("coupon_id")
        if not coupon_id:
            return None
        return self.get_by_id(str(coupon_id))

    def get_by_id(self, coupon_id: str) -> dict[str, Any] | None:
        snap = self.db.collection("coupons").document(coupon_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data["created_at"] = _ts(data.get("created_at"))
        data["updated_at"] = _ts(data.get("updated_at"))
        data["paused_at"] = _ts(data.get("paused_at")) if data.get("paused_at") else None
        data["deleted_at"] = _ts(data.get("deleted_at")) if data.get("deleted_at") else None
        return data

    def reserve_redemption(self, coupon_id: str) -> dict[str, Any]:
        coupon_ref = self.db.collection("coupons").document(coupon_id)
        transaction = self.db.transaction()

        @firestore.transactional
        def _reserve(txn):
            snap = coupon_ref.get(transaction=txn)
            if not snap.exists:
                raise ValueError("Invalid coupon code")
            data = snap.to_dict() or {}
            if data.get("status") != "active":
                raise ValueError("Coupon is not active")
            redemption_count = int(data.get("redemption_count") or 0)
            max_redemptions = data.get("max_redemptions")
            if max_redemptions is not None and redemption_count >= int(max_redemptions):
                raise ValueError("Coupon redemption limit reached")
            txn.update(
                coupon_ref,
                {
                    "redemption_count": Increment(1),
                    "updated_at": _now(),
                },
            )

        _reserve(transaction)
        return self.get_by_id(coupon_id) or {}

    def pause(self, coupon_id: str) -> dict[str, Any] | None:
        current = self.get_by_id(coupon_id)
        if current is None:
            return None
        if current.get("status") == "deleted":
            raise ValueError("Coupon not found")
        if current.get("status") == "paused":
            return current
        now = _now()
        self.db.collection("coupons").document(coupon_id).update(
            {
                "status": "paused",
                "paused_at": now,
                "updated_at": now,
            }
        )
        return self.get_by_id(coupon_id)

    def soft_delete(self, coupon_id: str) -> dict[str, Any] | None:
        current = self.get_by_id(coupon_id)
        if current is None:
            return None
        if current.get("status") == "deleted":
            return current
        now = _now()
        self.db.collection("coupons").document(coupon_id).update(
            {
                "status": "deleted",
                "deleted_at": now,
                "updated_at": now,
            }
        )
        return self.get_by_id(coupon_id)

    def list(self) -> list[dict[str, Any]]:
        docs = self.db.collection("coupons").order_by("created_at").stream()
        results = []
        for doc in docs:
            data = doc.to_dict() or {}
            data["created_at"] = _ts(data.get("created_at"))
            results.append(data)
        return results


class FirestoreSubscriptionRepository:
    """Checkout subscriptions persisted in Firestore."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    def create_pending(self, payload: dict[str, Any]) -> dict[str, Any]:
        subscription_id = f"sub_{uuid4().hex}"
        now = _now()
        self.db.collection("subscriptions").document(subscription_id).set(
            {
                "id": subscription_id,
                **payload,
                "root_subscription_id": subscription_id,
                "previous_subscription_id": None,
                "version": 1,
                "is_current": True,
                "change_reason": payload.get("change_reason") or "checkout_create",
                "superseded_at": None,
                "status": "pending_payment",
                "start_at": None,
                "end_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        return self.get(subscription_id) or {}

    def get(self, subscription_id: str) -> dict[str, Any] | None:
        snap = self.db.collection("subscriptions").document(subscription_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data["start_at"] = _ts(data.get("start_at"))
        data["end_at"] = _ts(data.get("end_at"))
        data["created_at"] = _ts(data.get("created_at"))
        data["updated_at"] = _ts(data.get("updated_at"))
        data["superseded_at"] = _ts(data.get("superseded_at"))
        return data

    def find_by_order_id(self, order_id: str) -> dict[str, Any] | None:
        query = (
            self.db.collection("subscriptions")
            .where("razorpay_order_id", "==", order_id)
            .limit(1)
            .stream()
        )
        for doc in query:
            data = doc.to_dict() or {}
            data["start_at"] = _ts(data.get("start_at"))
            data["end_at"] = _ts(data.get("end_at"))
            data["created_at"] = _ts(data.get("created_at"))
            data["updated_at"] = _ts(data.get("updated_at"))
            data["superseded_at"] = _ts(data.get("superseded_at"))
            return data
        return None

    def find_by_gateway_subscription_id(self, gateway_subscription_id: str) -> dict[str, Any] | None:
        query = (
            self.db.collection("subscriptions")
            .where("razorpay_subscription_id", "==", gateway_subscription_id)
            .limit(1)
            .stream()
        )
        for doc in query:
            data = doc.to_dict() or {}
            data["start_at"] = _ts(data.get("start_at"))
            data["end_at"] = _ts(data.get("end_at"))
            data["created_at"] = _ts(data.get("created_at"))
            data["updated_at"] = _ts(data.get("updated_at"))
            data["superseded_at"] = _ts(data.get("superseded_at"))
            return data
        return None

    def set_razorpay_order_id(self, subscription_id: str, order_id: str) -> dict[str, Any] | None:
        current = self.get(subscription_id)
        if current is None:
            return None
        self.db.collection("subscriptions").document(subscription_id).update(
            {
                "razorpay_order_id": order_id,
                "updated_at": _now(),
            }
        )
        return self.get(subscription_id)

    def set_razorpay_subscription_id(self, subscription_id: str, gateway_subscription_id: str) -> dict[str, Any] | None:
        current = self.get(subscription_id)
        if current is None:
            return None
        self.db.collection("subscriptions").document(subscription_id).update(
            {
                "razorpay_subscription_id": gateway_subscription_id,
                "updated_at": _now(),
            }
        )
        return self.get(subscription_id)

    def set_invoice_state(self, subscription_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get(subscription_id)
        if current is None:
            return None
        data = dict(payload)
        data["updated_at"] = _now()
        self.db.collection("subscriptions").document(subscription_id).update(data)
        return self.get(subscription_id)

    def find_active_by_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        query = (
            self.db.collection("subscriptions")
            .where("tenant_id", "==", tenant_id)
            .where("status", "==", "active")
            .where("is_current", "==", True)
            .limit(1)
            .stream()
        )
        for doc in query:
            data = doc.to_dict() or {}
            data["start_at"] = _ts(data.get("start_at"))
            data["end_at"] = _ts(data.get("end_at"))
            data["created_at"] = _ts(data.get("created_at"))
            data["updated_at"] = _ts(data.get("updated_at"))
            data["superseded_at"] = _ts(data.get("superseded_at"))
            return data
        return None

    def activate(
        self,
        subscription_id: str,
        start_at: datetime,
        end_at: datetime,
        payment_id: str,
    ) -> dict[str, Any]:
        self.db.collection("subscriptions").document(subscription_id).update(
            {
                "status": "active",
                "start_at": start_at,
                "end_at": end_at,
                "razorpay_payment_id": payment_id,
                "is_current": True,
                "updated_at": _now(),
            }
        )
        return self.get(subscription_id) or {}

    def list(self) -> list[dict[str, Any]]:
        docs = self.db.collection("subscriptions").order_by("created_at").stream()
        results = []
        for doc in docs:
            data = doc.to_dict() or {}
            data["start_at"] = _ts(data.get("start_at"))
            data["end_at"] = _ts(data.get("end_at"))
            data["created_at"] = _ts(data.get("created_at"))
            data["updated_at"] = _ts(data.get("updated_at"))
            data["superseded_at"] = _ts(data.get("superseded_at"))
            results.append(data)
        return results

    def update_status(self, subscription_id: str, status: str) -> dict[str, Any] | None:
        current = self.get(subscription_id)
        if current is None:
            return None
        self.db.collection("subscriptions").document(subscription_id).update(
            {"status": status, "updated_at": _now()}
        )
        return self.get(subscription_id)

    def create_version(self, previous_subscription_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        previous = self.get(previous_subscription_id)
        if previous is None:
            raise ValueError("Subscription not found")

        now = _now()
        self.db.collection("subscriptions").document(previous_subscription_id).update(
            {
                "status": "superseded",
                "is_current": False,
                "superseded_at": now,
                "updated_at": now,
            }
        )

        subscription_id = f"sub_{uuid4().hex}"
        self.db.collection("subscriptions").document(subscription_id).set(
            {
                "id": subscription_id,
                **payload,
                "root_subscription_id": str(previous.get("root_subscription_id") or previous["id"]),
                "previous_subscription_id": previous["id"],
                "version": int(previous.get("version") or 1) + 1,
                "is_current": True,
                "change_reason": payload.get("change_reason") or "amendment",
                "superseded_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        return self.get(subscription_id) or {}


class FirestoreIdempotencyRepository:
    """Idempotency key persistence."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    @staticmethod
    def _key(operation_key: str) -> str:
        return sha256(operation_key.encode("utf-8")).hexdigest()

    def get(self, operation_key: str) -> dict[str, Any] | None:
        snap = self.db.collection("idempotency_keys").document(self._key(operation_key)).get()
        if not snap.exists:
            return None

        data = snap.to_dict() or {}
        # Backward compatibility: prefer wrapped payload, but support legacy direct shape.
        response = data.get("response")
        if isinstance(response, dict):
            return response
        return data if isinstance(data, dict) else None

    def set(self, operation_key: str, response: dict[str, Any]) -> None:
        self.db.collection("idempotency_keys").document(self._key(operation_key)).set(
            {
                "response": response,
                "created_at": _now(),
            }
        )


class FirestoreRateLimitRepository:
    """Rate limit windows persisted in Firestore for distributed enforcement."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    @staticmethod
    def _key(raw_key: str) -> str:
        return sha256(raw_key.encode("utf-8")).hexdigest()

    def consume(self, *, key: str, limit: int, window_seconds: int, now: datetime) -> tuple[bool, int]:
        doc_ref = self.db.collection("rate_limits").document(self._key(key))
        transaction = self.db.transaction()

        @firestore.transactional
        def _consume(txn):
            snap = doc_ref.get(transaction=txn)
            if not snap.exists:
                txn.set(doc_ref, {"window_start": now, "count": 1, "updated_at": now})
                return True, 0

            data = snap.to_dict() or {}
            window_start = _ts(data.get("window_start"))
            count = int(data.get("count") or 0)
            elapsed = (now - window_start).total_seconds()

            if elapsed >= window_seconds:
                txn.set(doc_ref, {"window_start": now, "count": 1, "updated_at": now}, merge=True)
                return True, 0

            if count >= limit:
                retry_after = max(1, int(window_seconds - elapsed))
                return False, retry_after

            txn.update(doc_ref, {"count": count + 1, "updated_at": now})
            return True, 0

        return _consume(transaction)


class FirestoreWebhookEventRepository:
    """Processed webhook event tracking."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    def seen(self, event_id: str) -> bool:
        return self.db.collection("webhook_events").document(event_id).get().exists

    def mark(self, event_id: str) -> None:
        self.db.collection("webhook_events").document(event_id).set(
            {"event_id": event_id, "created_at": _now()}
        )


class FirestoreTenantRepository:
    """Tenant records persisted in Firestore."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        tenant_id = _generate_public_tenant_id()
        while self.db.collection("tenants").document(tenant_id).get().exists:
            tenant_id = _generate_public_tenant_id()
        now = _now()
        self.db.collection("tenants").document(tenant_id).set(
            {
                "id": tenant_id,
                **payload,
                "status": payload.get("status", "active"),
                "created_at": now,
                "updated_at": now,
            }
        )
        return self.get(tenant_id) or {}

    def list(self) -> list[dict[str, Any]]:
        docs = self.db.collection("tenants").order_by("created_at").stream()
        results = []
        for doc in docs:
            data = doc.to_dict() or {}
            data["created_at"] = _ts(data.get("created_at"))
            data["updated_at"] = _ts(data.get("updated_at"))
            results.append(data)
        return results

    def get(self, tenant_id: str) -> dict[str, Any] | None:
        snap = self.db.collection("tenants").document(tenant_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data["created_at"] = _ts(data.get("created_at"))
        data["updated_at"] = _ts(data.get("updated_at"))
        return data

    def update(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get(tenant_id)
        if current is None:
            return None
        payload = {k: v for k, v in payload.items() if v is not None}
        payload["updated_at"] = _now()
        self.db.collection("tenants").document(tenant_id).update(payload)
        return self.get(tenant_id)


class FirestoreGstPoolRepository:
    """GST verification payloads persisted in Firestore gst_pool collection."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    def get(self, gstin: str) -> dict[str, Any] | None:
        key = str(gstin).strip().upper()
        snap = self.db.collection("gst_pool").document(key).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        for field in ("created_at", "updated_at"):
            if data.get(field) is not None:
                data[field] = _ts(data.get(field))
        return data

    def set(self, gstin: str, payload: dict[str, Any]) -> dict[str, Any]:
        key = str(gstin).strip().upper()
        current = self.get(key)
        now = _now()
        item = {
            "gstin": key,
            **payload,
            "updated_at": now,
            "created_at": current.get("created_at") if current is not None else now,
        }
        self.db.collection("gst_pool").document(key).set(item)
        return self.get(key) or {}


class FirestoreOtpChallengeRepository:
    """OTP challenges persisted in Firestore."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        challenge_id = str(payload["id"])
        self.db.collection("otp_challenges").document(challenge_id).set(payload)
        return self.get(challenge_id) or {}

    def get(self, challenge_id: str) -> dict[str, Any] | None:
        snap = self.db.collection("otp_challenges").document(challenge_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data["created_at"] = _ts(data.get("created_at"))
        data["updated_at"] = _ts(data.get("updated_at"))
        data["expires_at"] = _ts(data.get("expires_at"))
        resend_at = data.get("resend_available_at")
        if resend_at is not None:
            data["resend_available_at"] = _ts(resend_at)
        verified_at = data.get("verified_at")
        if verified_at is not None:
            data["verified_at"] = _ts(verified_at)
        return data

    def update(self, challenge_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get(challenge_id)
        if current is None:
            return None
        self.db.collection("otp_challenges").document(challenge_id).update(payload)
        return self.get(challenge_id)

    def get_active(self, *, channel: str, target_hash: str, purpose: str, now: datetime) -> dict[str, Any] | None:
        query = (
            self.db.collection("otp_challenges")
            .where(filter=firestore.FieldFilter("channel", "==", channel))
            .where(filter=firestore.FieldFilter("target_hash", "==", target_hash))
            .where(filter=firestore.FieldFilter("purpose", "==", purpose))
            .where(filter=firestore.FieldFilter("status", "==", "active"))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(5)
            .stream()
        )
        for doc in query:
            data = self.get(doc.id)
            if data is None:
                continue
            if data.get("expires_at") and data["expires_at"] >= now:
                return data
        return None

    def count_recent_sends(
        self,
        *,
        channel: str,
        target_hash: str,
        purpose: str,
        since: datetime,
    ) -> int:
        query = (
            self.db.collection("otp_challenges")
            .where(filter=firestore.FieldFilter("channel", "==", channel))
            .where(filter=firestore.FieldFilter("target_hash", "==", target_hash))
            .where(filter=firestore.FieldFilter("purpose", "==", purpose))
            .where(filter=firestore.FieldFilter("created_at", ">=", since))
            .stream()
        )
        return sum(1 for _ in query)


class FirestoreOnboardingSessionRepository:
    """Sales onboarding sessions persisted in Firestore."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload["id"])
        self.db.collection("onboarding_sessions").document(session_id).set(payload)
        return self.get(session_id) or {}

    def get(self, session_id: str) -> dict[str, Any] | None:
        snap = self.db.collection("onboarding_sessions").document(session_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        for key in ("created_at", "updated_at", "expires_at", "verified_at"):
            if data.get(key) is not None:
                data[key] = _ts(data.get(key))
        return data

    def update(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get(session_id)
        if current is None:
            return None
        self.db.collection("onboarding_sessions").document(session_id).update(payload)
        return self.get(session_id)

    def get_latest_by_subscription(self, subscription_id: str) -> dict[str, Any] | None:
        query = (
            self.db.collection("onboarding_sessions")
            .where(filter=firestore.FieldFilter("subscription_id", "==", subscription_id))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        for doc in query:
            return self.get(doc.id)
        return None

    def get_latest_by_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        query = (
            self.db.collection("onboarding_sessions")
            .where(filter=firestore.FieldFilter("tenant_id", "==", tenant_id))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        for doc in query:
            return self.get(doc.id)
        return None


class FirestoreSuperAdminRepository:
    """Stores super admin assignment and invitations in Firestore."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    def get_current(self) -> dict[str, Any] | None:
        snap = self.db.collection("super_admin").document("current").get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        for key in ("assigned_at", "updated_at"):
            if data.get(key) is not None:
                data[key] = _ts(data.get(key))
        return data

    def set_current(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        data["updated_at"] = _now()
        self.db.collection("super_admin").document("current").set(data)
        return self.get_current() or {}

    def create_invitation(self, payload: dict[str, Any]) -> dict[str, Any]:
        invitation_id = str(payload["id"])
        self.db.collection("super_admin_invitations").document(invitation_id).set(payload)
        return self.get_invitation(invitation_id) or {}

    def get_invitation(self, invitation_id: str) -> dict[str, Any] | None:
        snap = self.db.collection("super_admin_invitations").document(invitation_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        for key in ("invited_at", "expires_at", "responded_at"):
            if data.get(key) is not None:
                data[key] = _ts(data.get(key))
        return data

    def update_invitation(self, invitation_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self.get_invitation(invitation_id) is None:
            return None
        self.db.collection("super_admin_invitations").document(invitation_id).update(payload)
        return self.get_invitation(invitation_id)

    def list_invitations(self, limit: int = 10) -> list[dict[str, Any]]:
        query = (
            self.db.collection("super_admin_invitations")
            .order_by("invited_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        items: list[dict[str, Any]] = []
        for doc in query:
            invitation = self.get_invitation(doc.id)
            if invitation is not None:
                items.append(invitation)
        return items

    def get_pending_invitation(self) -> dict[str, Any] | None:
        query = (
            self.db.collection("super_admin_invitations")
            .where(filter=firestore.FieldFilter("status", "==", "pending"))
            .stream()
        )
        latest: dict[str, Any] | None = None
        for doc in query:
            invitation = self.get_invitation(doc.id)
            if invitation is None:
                continue
            if latest is None:
                latest = invitation
                continue
            invited_at = invitation.get("invited_at")
            latest_invited_at = latest.get("invited_at")
            if invited_at is not None and (latest_invited_at is None or invited_at > latest_invited_at):
                latest = invitation
        return latest


class FirestorePortalAccessInvitationRepository:
    """Stores admin portal onboarding invitations in Firestore."""

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        invitation_id = str(payload["id"])
        self.db.collection("portal_access_invitations").document(invitation_id).set(payload)
        return self.get(invitation_id) or {}

    def get(self, invitation_id: str) -> dict[str, Any] | None:
        snap = self.db.collection("portal_access_invitations").document(invitation_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        for key in ("invited_at", "expires_at", "responded_at"):
            if data.get(key) is not None:
                data[key] = _ts(data.get(key))
        return data

    def update(self, invitation_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self.get(invitation_id) is None:
            return None
        self.db.collection("portal_access_invitations").document(invitation_id).update(payload)
        return self.get(invitation_id)

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        query = (
            self.db.collection("portal_access_invitations")
            .order_by("invited_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        items: list[dict[str, Any]] = []
        for doc in query:
            invitation = self.get(doc.id)
            if invitation is not None:
                items.append(invitation)
        return items

    def list_pending_for_email(self, email: str) -> list[dict[str, Any]]:
        query = (
            self.db.collection("portal_access_invitations")
            .where(filter=firestore.FieldFilter("invitee_email", "==", str(email).strip().lower()))
            .where(filter=firestore.FieldFilter("status", "==", "pending"))
            .stream()
        )
        items: list[dict[str, Any]] = []
        for doc in query:
            invitation = self.get(doc.id)
            if invitation is not None:
                items.append(invitation)
        return sorted(
            items,
            key=lambda invitation: invitation.get("invited_at") or _now(),
            reverse=True,
        )
