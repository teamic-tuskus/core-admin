"""Tests for CoreAdmin administrative workflows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from urllib.parse import parse_qs, urlparse

from app.core.auth import AuthenticatedPrincipal
from app.services.admin_service import AdminService
from app.services.repositories import (
    PortalAccessInvitationRepository,
    SubscriptionRepository,
    SuperAdminRepository,
    TenantRepository,
)


class _FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send_email(self, *, to_email: str, subject: str, body_text: str, body_html: str | None = None) -> None:
        self.sent.append({"to_email": to_email, "subject": subject, "body_text": body_text, "body_html": body_html or ""})


class _FakeUser:
    def __init__(self, claims: dict | None = None) -> None:
        self.custom_claims = claims or {}
        self.uid = "uid_test"
        self.email = "test@example.com"
        self.display_name = "Test User"
        self.disabled = False
        self.user_metadata = type("Meta", (), {"creation_timestamp": 0, "last_sign_in_timestamp": 0})()


class _FakePage:
    def __init__(self, users: list[_FakeUser]) -> None:
        self.users = users

    def get_next_page(self):
        return None


class _FakeFirebaseAuth:
    def __init__(self) -> None:
        self.claims_by_uid = {
            "uid_old": {"role": "super_admin", "roles": ["admin", "super_admin"]},
            "uid_new": {"role": "admin", "roles": ["admin"]},
            "uid_admin": {"role": "admin", "roles": ["admin"]},
            "uid_manager": {"role": "manager", "roles": ["manager"], "portal_permissions": ["products"]},
            "uid_user": {"role": "viewer", "roles": ["viewer"]},
        }
        self.email_by_uid = {uid: f"{uid}@example.com" for uid in self.claims_by_uid}
        self.deleted_uids: set[str] = set()
        self.disabled_uids: set[str] = set()
        self.revoked_uids: set[str] = set()

    def get_user(self, uid: str) -> _FakeUser:
        if uid in self.deleted_uids:
            raise ValueError("User not found")
        user = _FakeUser(self.claims_by_uid.get(uid, {}))
        user.uid = uid
        user.email = self.email_by_uid.get(uid, f"{uid}@example.com")
        user.disabled = uid in self.disabled_uids
        return user

    def get_user_by_email(self, email: str) -> _FakeUser:
        normalized = email.strip().lower()
        for uid, mapped_email in self.email_by_uid.items():
            if mapped_email.lower() == normalized:
                return self.get_user(uid)
        raise ValueError("User not found")

    def set_custom_user_claims(self, uid: str, claims: dict | None) -> None:
        self.claims_by_uid[uid] = claims or {}

    def list_users(self):
        users = []
        for uid, claims in self.claims_by_uid.items():
            if uid in self.deleted_uids:
                continue
            user = _FakeUser(claims)
            user.uid = uid
            user.email = self.email_by_uid.get(uid, f"{uid}@example.com")
            user.disabled = uid in self.disabled_uids
            users.append(user)
        return _FakePage(users)

    def revoke_refresh_tokens(self, uid: str) -> None:
        self.revoked_uids.add(uid)

    def update_user(self, uid: str, *, disabled: bool | None = None):
        if disabled:
            self.disabled_uids.add(uid)

    def delete_user(self, uid: str) -> None:
        self.deleted_uids.add(uid)
        self.claims_by_uid.pop(uid, None)

    def add_user(self, *, uid: str, email: str, claims: dict | None = None) -> None:
        self.claims_by_uid[uid] = claims or {}
        self.email_by_uid[uid] = email


class _LaggyClaimsFirebaseAuth(_FakeFirebaseAuth):
    """Simulates Firebase returning stale claims once after a claims write."""

    def __init__(self) -> None:
        super().__init__()
        self._stale_once_by_uid: dict[str, dict] = {}

    def get_user(self, uid: str) -> _FakeUser:
        if uid in self.deleted_uids:
            raise ValueError("User not found")
        claims = self._stale_once_by_uid.pop(uid, self.claims_by_uid.get(uid, {}))
        user = _FakeUser(dict(claims))
        user.uid = uid
        user.email = self.email_by_uid.get(uid, f"{uid}@example.com")
        user.disabled = uid in self.disabled_uids
        return user

    def set_custom_user_claims(self, uid: str, claims: dict | None) -> None:
        previous = dict(self.claims_by_uid.get(uid, {}))
        self._stale_once_by_uid[uid] = previous
        self.claims_by_uid[uid] = claims or {}


def _build_service() -> AdminService:
    os.environ.setdefault("COREADMIN_GCP_PROJECT_ID", "core-admin-test")
    email_sender = _FakeEmailSender()
    return AdminService(
        tenant_repo=TenantRepository(),
        subscription_repo=SubscriptionRepository(),
        super_admin_repo=SuperAdminRepository(),
        portal_access_invitation_repo=PortalAccessInvitationRepository(),
        email_sender=email_sender,  # type: ignore[arg-type]
    )


def test_create_and_update_tenant() -> None:
    service = _build_service()
    tenant = service.create_tenant(
        {
            "name": "Alpha Build Pvt Ltd",
            "company_email": "ops@alpha.example.com",
            "contact_name": "Asha Kumar",
            "phone": "+91-9999999999",
        }
    )

    assert tenant["status"] == "active"
    updated = service.update_tenant(tenant["id"], {"status": "suspended", "phone": "+91-8888888888"})
    assert updated["status"] == "suspended"
    assert updated["phone"] == "+91-8888888888"


def test_list_and_reconcile_subscription() -> None:
    service = _build_service()
    subscription = service.subscription_repo.create_pending(
        {
            "tenant_id": "ten_123",
            "product_id": "prd_123",
            "product_snapshot": {
                "id": "prd_123",
                "code": "CORE-GROWTH",
                "name": "Core Growth",
                "description": "Growth plan",
                "modules": ["execution", "store"],
                "base_max_users": 10,
                "pricing": [{"tenure_months": 12, "amount_paise": 100000}],
            },
            "modules": ["execution"],
            "max_users": 10,
            "tenure_months": 12,
            "currency": "INR",
            "amount_paise": 100000,
            "coupon_code": None,
            "coupon_snapshot": None,
            "customer_name": "Demo Tenant",
            "customer_email": "demo@example.com",
        }
    )

    listed = service.list_subscriptions()
    assert listed[0]["id"] == subscription["id"]
    assert listed[0]["product_snapshot"]["code"] == "CORE-GROWTH"

    status_updated = service.update_subscription_status(subscription["id"], "suspended")
    assert status_updated["status"] == "suspended"

    reconciled = service.reconcile_subscription(subscription["id"])
    assert "reconciled_at" in reconciled


def test_super_admin_invitation_accept_transfers_ownership(monkeypatch) -> None:
    service = _build_service()

    fake_auth = _FakeFirebaseAuth()
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)

    service.super_admin_repo.set_current(
        {
            "uid": "uid_old",
            "email": "old@example.com",
            "display_name": "Old Admin",
            "assigned_at": datetime.now(UTC),
            "assigned_by_uid": "uid_old",
            "assigned_by_email": "old@example.com",
        }
    )

    invitation = service.create_super_admin_invitation(
        invitee_email="new@example.com",
        principal=AuthenticatedPrincipal(
            uid="uid_old",
            email="old@example.com",
            claims={"role": "super_admin", "roles": ["super_admin", "admin"]},
        ),
    )["invitation"]

    result = service.accept_super_admin_invitation(
        invitation_id=invitation["id"],
        principal=AuthenticatedPrincipal(
            uid="uid_new",
            email="new@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )

    assert result["current_super_admin"]["email"] == "new@example.com"
    assert fake_auth.claims_by_uid["uid_new"]["role"] == "super_admin"
    assert "super_admin" not in fake_auth.claims_by_uid["uid_old"].get("roles", [])


def test_super_admin_invitation_can_be_rejected() -> None:
    service = _build_service()

    invitation = service.create_super_admin_invitation(
        invitee_email="invitee@example.com",
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )["invitation"]

    result = service.reject_super_admin_invitation(
        invitation_id=invitation["id"],
        principal=AuthenticatedPrincipal(
            uid="uid_invitee",
            email="invitee@example.com",
            claims={"role": "viewer"},
        ),
    )

    assert result["invitation"]["status"] == "rejected"


def test_portal_access_invitation_accept_sets_admin_claim(monkeypatch) -> None:
    service = _build_service()
    fake_auth = _FakeFirebaseAuth()
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)

    invitation = service.create_portal_access_invitation(
        invitee_email="user@example.com",
        invitee_name="User One",
        invitee_designation="Sales",
        invitee_agent_number="AG-1001",
        role="admin",
        access_scope=None,
        normal_coupon_max_discount_percent=30,
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )["invitation"]

    result = service.accept_portal_access_invitation(
        invitation_id=invitation["id"],
        principal=AuthenticatedPrincipal(
            uid="uid_user",
            email="user@example.com",
            claims={"role": "viewer", "roles": ["viewer"]},
        ),
    )

    assert result["invitation"]["status"] == "accepted"
    assert fake_auth.claims_by_uid["uid_user"]["role"] == "admin"
    assert "admin" in fake_auth.claims_by_uid["uid_user"]["roles"]
    assert sorted(fake_auth.claims_by_uid["uid_user"]["portal_permissions"]) == ["coupons", "products", "users"]


def test_accept_portal_access_invitation_sets_claims_atomically_under_stale_reads(monkeypatch) -> None:
    service = _build_service()

    fake_auth = _LaggyClaimsFirebaseAuth()
    fake_auth.add_user(uid="uid_user", email="portal.user@example.com", claims={"role": "viewer", "roles": ["viewer"]})
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)

    principal_admin = AuthenticatedPrincipal(uid="uid_admin", email="admin@example.com", claims={"role": "admin"})
    invitation = service.create_portal_access_invitation(
        invitee_email="portal.user@example.com",
        invitee_name="Portal User",
        invitee_designation="Ops",
        invitee_agent_number="AG-2001",
        invitee_phone="+919900000000",
        role="admin",
        access_scope="both",
        principal=principal_admin,
    )["invitation"]

    principal_user = AuthenticatedPrincipal(uid="uid_user", email="portal.user@example.com", claims={"role": "viewer"})
    service.accept_portal_access_invitation(invitation_id=invitation["id"], principal=principal_user)

    claims = fake_auth.claims_by_uid["uid_user"]
    assert claims["role"] == "admin"
    assert sorted(claims["portal_permissions"]) == ["coupons", "products", "users"]
    assert claims["agent_number"] == "AG-2001"
    assert claims["designation"] == "Ops"


def test_portal_access_invitation_accept_sets_admin_with_coupon_only_scope(monkeypatch) -> None:
    service = _build_service()
    fake_auth = _FakeFirebaseAuth()
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)

    invitation = service.create_portal_access_invitation(
        invitee_email="admin-coupon@example.com",
        invitee_name="Admin Coupon",
        invitee_designation="Sales",
        invitee_agent_number="AG-1002",
        role="admin",
        access_scope="coupon",
        normal_coupon_max_discount_percent=30,
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )["invitation"]

    result = service.accept_portal_access_invitation(
        invitation_id=invitation["id"],
        principal=AuthenticatedPrincipal(
            uid="uid_user",
            email="admin-coupon@example.com",
            claims={"role": "viewer", "roles": ["viewer"]},
        ),
    )

    assert result["invitation"]["status"] == "accepted"
    assert fake_auth.claims_by_uid["uid_user"]["role"] == "admin"
    assert sorted(fake_auth.claims_by_uid["uid_user"]["portal_permissions"]) == ["coupons", "users"]


def test_portal_access_invitation_accept_sets_manager_scoped_claim(monkeypatch) -> None:
    service = _build_service()
    fake_auth = _FakeFirebaseAuth()
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)

    invitation = service.create_portal_access_invitation(
        invitee_email="manager@example.com",
        invitee_name="Manager One",
        invitee_designation="Manager",
        invitee_agent_number="AG-1003",
        role="manager",
        access_scope="coupon",
        normal_coupon_max_discount_percent=30,
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )["invitation"]

    result = service.accept_portal_access_invitation(
        invitation_id=invitation["id"],
        principal=AuthenticatedPrincipal(
            uid="uid_user",
            email="manager@example.com",
            claims={"role": "viewer", "roles": ["viewer"]},
        ),
    )

    assert result["invitation"]["status"] == "accepted"
    assert fake_auth.claims_by_uid["uid_user"]["role"] == "manager"
    assert sorted(fake_auth.claims_by_uid["uid_user"]["portal_permissions"]) == ["coupons"]


def test_get_portal_access_state_lists_operators(monkeypatch) -> None:
    service = _build_service()
    fake_auth = _FakeFirebaseAuth()
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)

    state = service.get_portal_access_state()

    assert any(item["role"] == "admin" for item in state["operators"])


def test_portal_invitation_resend_and_cancel(monkeypatch) -> None:
    service = _build_service()
    fake_auth = _FakeFirebaseAuth()
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)
    monkeypatch.setattr("app.services.admin_service.get_secret", lambda *_args, **_kwargs: "test-signing-key")
    fake_auth.add_user(uid="uid_pending", email="ops@example.com", claims={})

    created = service.create_portal_access_invitation(
        invitee_email="ops@example.com",
        invitee_name="Ops User",
        invitee_designation="Ops",
        invitee_agent_number="AG-1004",
        role="admin",
        access_scope=None,
        normal_coupon_max_discount_percent=30,
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )["invitation"]

    resent = service.resend_portal_access_invitation(
        invitation_id=created["id"],
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )["invitation"]
    assert int(resent.get("resend_count") or 0) == 1

    cancelled = service.cancel_portal_access_invitation(
        invitation_id=created["id"],
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )["invitation"]
    assert cancelled["status"] == "cancelled"
    assert "uid_pending" in fake_auth.deleted_uids


def test_portal_invitation_email_uses_invite_onboarding_link(monkeypatch) -> None:
    service = _build_service()
    monkeypatch.setattr("app.services.admin_service.get_secret", lambda *_args, **_kwargs: "test-signing-key")

    service.create_portal_access_invitation(
        invitee_email="new.operator@example.com",
        invitee_name="New Operator",
        invitee_designation="Ops",
        invitee_agent_number="AG-1005",
        role="admin",
        access_scope="both",
        normal_coupon_max_discount_percent=30,
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )["invitation"]

    sent_messages = getattr(service.email_sender, "sent", [])
    assert sent_messages
    assert "/invite?portalToken=" in sent_messages[-1]["body_text"]
    assert "inviteeEmail=new.operator%40example.com" in sent_messages[-1]["body_text"]
    assert "localhost" not in sent_messages[-1]["body_text"]
    assert "https://coreadmin.tuskus.com/invite?portalToken=" in sent_messages[-1]["body_text"]
    assert "CoreAdmin" in sent_messages[-1]["body_html"]
    assert "Open Invitation" in sent_messages[-1]["body_html"]


def test_portal_invitation_accept_by_token(monkeypatch) -> None:
    service = _build_service()
    fake_auth = _FakeFirebaseAuth()
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)
    monkeypatch.setattr("app.services.admin_service.get_secret", lambda *_args, **_kwargs: "test-signing-key")

    service.create_portal_access_invitation(
        invitee_email="new.operator@example.com",
        invitee_name="New Operator",
        invitee_designation="Ops",
        invitee_agent_number="AG-1006",
        role="admin",
        access_scope="both",
        normal_coupon_max_discount_percent=30,
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )

    sent_messages = getattr(service.email_sender, "sent", [])
    assert sent_messages
    body_text = sent_messages[-1]["body_text"]
    invite_link = body_text.split("respond: ", 1)[1].split("\n", 1)[0].strip()
    parsed = urlparse(invite_link)
    portal_token = parse_qs(parsed.query).get("portalToken", [""])[0]

    result = service.accept_portal_access_invitation_by_token(
        portal_token=portal_token,
        principal=AuthenticatedPrincipal(
            uid="uid_user",
            email="new.operator@example.com",
            claims={"role": "viewer", "roles": ["viewer"]},
        ),
    )

    assert result["invitation"]["status"] == "accepted"


def test_portal_invitation_resend_throttle_blocks_rapid_resend(monkeypatch) -> None:
    service = _build_service()
    fake_auth = _FakeFirebaseAuth()
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)
    monkeypatch.setattr("app.services.admin_service.get_secret", lambda *_args, **_kwargs: "test-signing-key")

    created = service.create_portal_access_invitation(
        invitee_email="throttle@example.com",
        invitee_name="Throttle User",
        invitee_designation="Ops",
        invitee_agent_number="AG-1007",
        role="admin",
        access_scope="both",
        normal_coupon_max_discount_percent=30,
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )["invitation"]

    service.resend_portal_access_invitation(
        invitation_id=created["id"],
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )

    try:
        service.resend_portal_access_invitation(
            invitation_id=created["id"],
            principal=AuthenticatedPrincipal(
                uid="uid_admin",
                email="admin@example.com",
                claims={"role": "admin", "roles": ["admin"]},
            ),
        )
        assert False, "Expected resend cooldown guard"
    except ValueError as exc:
        assert "Cannot resend yet" in str(exc)

    # Move timestamps outside cooldown and max-window checks to validate recovery.
    invitation = service.portal_access_invitation_repo.get(created["id"]) or {}
    resend_audit = list(invitation.get("resend_audit") or [])
    resend_audit[0]["sent_at"] = datetime.now(UTC) - timedelta(hours=2)
    service.portal_access_invitation_repo.update(created["id"], {"resend_audit": resend_audit})

    recovered = service.resend_portal_access_invitation(
        invitation_id=created["id"],
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )["invitation"]
    assert int(recovered.get("resend_count") or 0) == 2


def test_update_operator_access_remove(monkeypatch) -> None:
    service = _build_service()
    fake_auth = _FakeFirebaseAuth()
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)

    result = service.update_operator_access(
        target_uid="uid_user",
        action="remove_access",
        access_scope=None,
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )

    assert result["role"] == "none"
    assert "uid_user" in fake_auth.deleted_uids
    assert "uid_user" in fake_auth.disabled_uids
    assert "uid_user" in fake_auth.revoked_uids


def test_update_operator_access_set_manager(monkeypatch) -> None:
    service = _build_service()
    fake_auth = _FakeFirebaseAuth()
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)

    result = service.update_operator_access(
        target_uid="uid_user",
        action="set_manager",
        access_scope="both",
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )

    assert result["role"] == "manager"
    assert sorted(result["permissions"]) == ["coupons", "products"]
    assert fake_auth.claims_by_uid["uid_user"]["role"] == "manager"


def test_update_operator_access_set_admin_with_product_only_scope(monkeypatch) -> None:
    service = _build_service()
    fake_auth = _FakeFirebaseAuth()
    monkeypatch.setattr("app.services.admin_service.get_firebase_auth", lambda: fake_auth)

    result = service.update_operator_access(
        target_uid="uid_user",
        action="set_admin",
        access_scope="product",
        principal=AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={"role": "admin", "roles": ["admin"]},
        ),
    )

    assert result["role"] == "admin"
    assert sorted(result["permissions"]) == ["products", "users"]
