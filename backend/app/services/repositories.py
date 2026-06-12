"""In-memory repositories for CoreAdmin domain entities."""

from __future__ import annotations

from datetime import datetime, timezone
import secrets
import string
from threading import RLock
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _generate_public_tenant_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


class ProductRepository:
    """Stores product catalog entries."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._products: dict[str, dict[str, Any]] = {}
        self._product_by_code: dict[str, str] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            product_id = f"prd_{uuid4().hex}"
            code = str(payload["code"]).upper()
            if code in self._product_by_code:
                raise ValueError("Product code already exists")
            now = _now()
            item = {
                "id": product_id,
                **payload,
                "code": code,
                "created_at": now,
            }
            self._products[product_id] = item
            self._product_by_code[code] = product_id
            return item

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._products.values(), key=lambda item: item["created_at"])

    def get(self, product_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._products.get(product_id)

    def update(self, product_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            item = self._products.get(product_id)
            if item is None:
                return None

            if "code" in payload and payload["code"] is not None:
                new_code = str(payload["code"]).upper()
                old_code = str(item["code"]).upper()
                if new_code != old_code:
                    existing = self._product_by_code.get(new_code)
                    if existing is not None and existing != product_id:
                        raise ValueError("Product code already exists")
                    self._product_by_code.pop(old_code, None)
                    self._product_by_code[new_code] = product_id
                payload = {**payload, "code": new_code}

            item.update(payload)
            return item

    def delete(self, product_id: str) -> bool:
        with self._lock:
            item = self._products.pop(product_id, None)
            if item is None:
                return False
            self._product_by_code.pop(str(item.get("code", "")).upper(), None)
            return True


class CouponRepository:
    """Stores coupon and redemption metadata."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._coupons: dict[str, dict[str, Any]] = {}
        self._coupon_by_code: dict[str, str] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            coupon_id = f"cpn_{uuid4().hex}"
            now = _now()
            code = payload["code"].upper()
            if code in self._coupon_by_code:
                raise ValueError("Coupon code already exists")
            item = {
                "id": coupon_id,
                **payload,
                "code": code,
                "status": "active",
                "paused_at": None,
                "deleted_at": None,
                "redemption_count": 0,
                "created_at": now,
                "updated_at": now,
            }
            self._coupons[coupon_id] = item
            self._coupon_by_code[code] = coupon_id
            return item

    def get_by_id(self, coupon_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._coupons.get(coupon_id)

    def find_by_code(self, code: str) -> dict[str, Any] | None:
        with self._lock:
            coupon_id = self._coupon_by_code.get(code.upper())
            return self._coupons.get(coupon_id) if coupon_id else None

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        return self.find_by_code(code)

    def reserve_redemption(self, coupon_id: str) -> dict[str, Any]:
        with self._lock:
            item = self._coupons.get(coupon_id)
            if item is None:
                raise ValueError("Invalid coupon code")
            if item.get("status") != "active":
                raise ValueError("Coupon is not active")
            max_redemptions = item.get("max_redemptions")
            redemption_count = int(item.get("redemption_count") or 0)
            if max_redemptions is not None and redemption_count >= int(max_redemptions):
                raise ValueError("Coupon redemption limit reached")
            item["redemption_count"] = redemption_count + 1
            item["updated_at"] = _now()
            return item

    def pause(self, coupon_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._coupons.get(coupon_id)
            if item is None:
                return None
            if item.get("status") == "deleted":
                raise ValueError("Coupon not found")
            if item.get("status") == "paused":
                return item
            now = _now()
            item["status"] = "paused"
            item["paused_at"] = now
            item["updated_at"] = now
            return item

    def soft_delete(self, coupon_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._coupons.get(coupon_id)
            if item is None:
                return None
            if item.get("status") == "deleted":
                return item
            now = _now()
            item["status"] = "deleted"
            item["deleted_at"] = now
            item["updated_at"] = now
            return item

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._coupons.values(), key=lambda item: item["created_at"])


class SubscriptionRepository:
    """Stores checkout subscriptions and lifecycle data."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._subscriptions: dict[str, dict[str, Any]] = {}

    def create_pending(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            subscription_id = f"sub_{uuid4().hex}"
            now = _now()
            item = {
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
            self._subscriptions[subscription_id] = item
            return item

    def get(self, subscription_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._subscriptions.get(subscription_id)

    def find_by_order_id(self, order_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._subscriptions.values():
                if item.get("razorpay_order_id") == order_id:
                    return item
            return None

    def find_by_gateway_subscription_id(self, gateway_subscription_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._subscriptions.values():
                if item.get("razorpay_subscription_id") == gateway_subscription_id:
                    return item
            return None

    def set_razorpay_order_id(self, subscription_id: str, order_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._subscriptions.get(subscription_id)
            if item is None:
                return None
            item["razorpay_order_id"] = order_id
            item["updated_at"] = _now()
            return item

    def set_razorpay_subscription_id(self, subscription_id: str, gateway_subscription_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._subscriptions.get(subscription_id)
            if item is None:
                return None
            item["razorpay_subscription_id"] = gateway_subscription_id
            item["updated_at"] = _now()
            return item

    def set_invoice_state(self, subscription_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            item = self._subscriptions.get(subscription_id)
            if item is None:
                return None
            item.update(payload)
            item["updated_at"] = _now()
            return item

    def find_active_by_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        with self._lock:
            active = [
                item
                for item in self._subscriptions.values()
                if item.get("tenant_id") == tenant_id and item.get("status") == "active" and item.get("is_current", True)
            ]
            return max(active, key=lambda item: item["created_at"], default=None)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._subscriptions.values(), key=lambda item: item["created_at"])

    def activate(
        self,
        subscription_id: str,
        start_at: datetime,
        end_at: datetime,
        payment_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            item = self._subscriptions[subscription_id]
            item["status"] = "active"
            item["start_at"] = start_at
            item["end_at"] = end_at
            item["razorpay_payment_id"] = payment_id
            item["is_current"] = True
            item["updated_at"] = _now()
            return item

    def create_version(self, previous_subscription_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            previous = self._subscriptions.get(previous_subscription_id)
            if previous is None:
                raise ValueError("Subscription not found")

            now = _now()
            previous["status"] = "superseded"
            previous["is_current"] = False
            previous["superseded_at"] = now
            previous["updated_at"] = now

            subscription_id = f"sub_{uuid4().hex}"
            item = {
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
            self._subscriptions[subscription_id] = item
            return item

    def update_status(self, subscription_id: str, status: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._subscriptions.get(subscription_id)
            if item is None:
                return None
            item["status"] = status
            item["updated_at"] = _now()
            return item


class IdempotencyRepository:
    """Stores idempotent API responses by operation key."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._responses: dict[str, dict[str, Any]] = {}

    def get(self, operation_key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._responses.get(operation_key)

    def set(self, operation_key: str, response: dict[str, Any]) -> None:
        with self._lock:
            self._responses[operation_key] = response


class RateLimitRepository:
    """Stores per-key rate limit usage windows for request throttling."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._windows: dict[str, dict[str, Any]] = {}

    def consume(self, *, key: str, limit: int, window_seconds: int, now: datetime) -> tuple[bool, int]:
        with self._lock:
            item = self._windows.get(key)
            if item is None:
                self._windows[key] = {"window_start": now, "count": 1}
                return True, 0

            window_start = item["window_start"]
            elapsed = (now - window_start).total_seconds()
            if elapsed >= window_seconds:
                item["window_start"] = now
                item["count"] = 1
                return True, 0

            count = int(item.get("count", 0))
            if count >= limit:
                retry_after = max(1, int(window_seconds - elapsed))
                return False, retry_after

            item["count"] = count + 1
            return True, 0


class WebhookEventRepository:
    """Tracks processed webhook events to avoid duplicate processing."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._events: set[str] = set()

    def seen(self, event_id: str) -> bool:
        with self._lock:
            return event_id in self._events

    def mark(self, event_id: str) -> None:
        with self._lock:
            self._events.add(event_id)


class TenantRepository:
    """Stores CoreAdmin tenants for local/test execution."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._tenants: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            tenant_id = _generate_public_tenant_id()
            while tenant_id in self._tenants:
                tenant_id = _generate_public_tenant_id()
            now = _now()
            item = {
                "id": tenant_id,
                **payload,
                "status": payload.get("status", "active"),
                "created_at": now,
                "updated_at": now,
            }
            self._tenants[tenant_id] = item
            return item

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._tenants.values(), key=lambda item: item["created_at"])

    def get(self, tenant_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._tenants.get(tenant_id)

    def update(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            item = self._tenants.get(tenant_id)
            if item is None:
                return None
            item.update(payload)
            item["updated_at"] = _now()
            return item


class GstPoolRepository:
    """Stores GST verification payloads keyed by GSTIN."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._rows: dict[str, dict[str, Any]] = {}

    def get(self, gstin: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(str(gstin).strip().upper())
            return dict(row) if row is not None else None

    def set(self, gstin: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            key = str(gstin).strip().upper()
            item = {**payload, "gstin": key, "updated_at": _now()}
            if key not in self._rows:
                item["created_at"] = item["updated_at"]
            else:
                item["created_at"] = self._rows[key].get("created_at")
            self._rows[key] = item
            return dict(item)


class OtpChallengeRepository:
    """Stores OTP challenges and rate-limit metadata."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._challenges: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._challenges[payload["id"]] = dict(payload)
            return dict(payload)

    def get(self, challenge_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._challenges.get(challenge_id)
            return dict(item) if item is not None else None

    def update(self, challenge_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            item = self._challenges.get(challenge_id)
            if item is None:
                return None
            item.update(payload)
            return dict(item)

    def get_active(self, *, channel: str, target_hash: str, purpose: str, now: datetime) -> dict[str, Any] | None:
        with self._lock:
            candidates = [
                item
                for item in self._challenges.values()
                if item.get("channel") == channel
                and item.get("target_hash") == target_hash
                and item.get("purpose") == purpose
                and item.get("status") == "active"
                and (item.get("expires_at") is None or item["expires_at"] >= now)
            ]
            latest = max(candidates, key=lambda item: item.get("created_at"), default=None)
            return dict(latest) if latest is not None else None

    def count_recent_sends(
        self,
        *,
        channel: str,
        target_hash: str,
        purpose: str,
        since: datetime,
    ) -> int:
        with self._lock:
            count = 0
            for item in self._challenges.values():
                if item.get("channel") != channel:
                    continue
                if item.get("target_hash") != target_hash:
                    continue
                if item.get("purpose") != purpose:
                    continue
                created_at = item.get("created_at")
                if created_at and created_at >= since:
                    count += 1
            return count


class OnboardingSessionRepository:
    """Stores sales onboarding state and OTP session links."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._sessions[payload["id"]] = dict(payload)
            return dict(payload)

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._sessions.get(session_id)
            return dict(item) if item is not None else None

    def update(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            item = self._sessions.get(session_id)
            if item is None:
                return None
            item.update(payload)
            return dict(item)

    def get_latest_by_subscription(self, subscription_id: str) -> dict[str, Any] | None:
        with self._lock:
            latest: dict[str, Any] | None = None
            for item in self._sessions.values():
                if item.get("subscription_id") != subscription_id:
                    continue
                if latest is None or item.get("created_at") > latest.get("created_at"):
                    latest = item
            return dict(latest) if latest is not None else None

    def get_latest_by_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        with self._lock:
            latest: dict[str, Any] | None = None
            for item in self._sessions.values():
                if item.get("tenant_id") != tenant_id:
                    continue
                if latest is None or item.get("created_at") > latest.get("created_at"):
                    latest = item
            return dict(latest) if latest is not None else None


class SuperAdminRepository:
    """Stores the current super admin assignment and invitation records."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._current: dict[str, Any] | None = None
        self._invitations: dict[str, dict[str, Any]] = {}

    def get_current(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._current) if self._current is not None else None

    def set_current(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            item = dict(payload)
            item["updated_at"] = _now()
            self._current = item
            return dict(item)

    def create_invitation(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            invitation_id = str(payload["id"])
            item = dict(payload)
            self._invitations[invitation_id] = item
            return dict(item)

    def get_invitation(self, invitation_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._invitations.get(invitation_id)
            return dict(item) if item is not None else None

    def update_invitation(self, invitation_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            item = self._invitations.get(invitation_id)
            if item is None:
                return None
            item.update(payload)
            return dict(item)

    def list_invitations(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            items = sorted(
                self._invitations.values(),
                key=lambda invitation: invitation.get("invited_at") or _now(),
                reverse=True,
            )
            return [dict(item) for item in items[:limit]]

    def get_pending_invitation(self) -> dict[str, Any] | None:
        with self._lock:
            pending = [item for item in self._invitations.values() if item.get("status") == "pending"]
            if not pending:
                return None
            latest = max(pending, key=lambda item: item.get("invited_at") or _now())
            return dict(latest)


class PortalAccessInvitationRepository:
    """Stores access onboarding invitations for admin portal users."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._invitations: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            invitation_id = str(payload["id"])
            item = dict(payload)
            self._invitations[invitation_id] = item
            return dict(item)

    def get(self, invitation_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._invitations.get(invitation_id)
            return dict(item) if item is not None else None

    def update(self, invitation_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            item = self._invitations.get(invitation_id)
            if item is None:
                return None
            item.update(payload)
            return dict(item)

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            items = sorted(
                self._invitations.values(),
                key=lambda invitation: invitation.get("invited_at") or _now(),
                reverse=True,
            )
            return [dict(item) for item in items[:limit]]

    def list_pending_for_email(self, email: str) -> list[dict[str, Any]]:
        target = str(email).strip().lower()
        with self._lock:
            pending = [
                item
                for item in self._invitations.values()
                if str(item.get("invitee_email") or "").strip().lower() == target and item.get("status") == "pending"
            ]
            return sorted(pending, key=lambda invitation: invitation.get("invited_at") or _now(), reverse=True)
