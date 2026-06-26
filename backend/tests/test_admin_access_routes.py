"""API route tests for admin access invitation endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes.admin import router as admin_router
from app.core.auth import require_admin
from app.core.settings import get_settings
from app.services.admin_container import get_admin_service


class _FakeAdminService:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.last_invite_payload: dict[str, str | None] | None = None
        self._invitation = {
            "id": "pai_001",
            "invitee_email": "ops@example.com",
            "role": "admin",
            "access_scope": "both",
            "permissions": ["products", "coupons", "users"],
            "status": "pending",
            "invited_at": now,
            "expires_at": now,
            "invited_by_uid": "uid_admin",
            "invited_by_email": "admin@example.com",
            "responded_at": None,
            "response_actor_uid": None,
            "response_actor_email": None,
            "response_note": None,
            "resend_count": 0,
            "resend_audit": [],
        }

    def create_portal_access_invitation(
        self,
        *,
        invitee_email: str,
        role: str,
        access_scope: str | None,
        principal,
        invitee_name: str | None = None,
        invitee_designation: str | None = None,
        invitee_agent_number: str | None = None,
        normal_coupon_max_discount_percent: int | None = None,
    ) -> dict:
        self.last_invite_payload = {
            "invitee_email": invitee_email,
            "role": role,
            "access_scope": access_scope,
            "invitee_name": invitee_name,
            "invitee_designation": invitee_designation,
            "invitee_agent_number": invitee_agent_number,
            "normal_coupon_max_discount_percent": normal_coupon_max_discount_percent,
        }
        invitation = {**self._invitation, "invitee_email": invitee_email, "role": role, "access_scope": access_scope or "both"}
        return {"invitation": invitation, "delivery_status": "sent"}

    def get_portal_access_state(self) -> dict:
        return {"operators": [], "invitations": []}


def _build_client(service: _FakeAdminService) -> TestClient:
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1")

    app.dependency_overrides[require_admin] = lambda: type(
        "Principal",
        (),
        {"uid": "uid_admin", "email": "admin@example.com", "claims": {"role": "admin", "roles": ["admin"]}},
    )()
    app.dependency_overrides[get_admin_service] = lambda: service
    app.dependency_overrides[get_settings] = lambda: type(
        "Settings", (), {"max_portal_operators": 50}
    )()

    return TestClient(app)


def test_send_access_invite_posts_admin_with_product_scope() -> None:
    service = _FakeAdminService()
    client = _build_client(service)

    response = client.post(
        "/api/v1/admin/access/invitations",
        json={
            "invitee_email": "product.admin@example.com",
            "invitee_name": "Product Admin",
            "invitee_designation": "Admin",
            "invitee_agent_number": "AG-2001",
            "role": "admin",
            "access_scope": "product",
            "normal_coupon_max_discount_percent": 30,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["delivery_status"] == "sent"
    assert payload["invitation"]["invitee_email"] == "product.admin@example.com"
    assert payload["invitation"]["role"] == "admin"
    assert payload["invitation"]["access_scope"] == "product"

    assert service.last_invite_payload == {
        "invitee_email": "product.admin@example.com",
        "role": "admin",
        "access_scope": "product",
        "invitee_name": "Product Admin",
        "invitee_designation": "Admin",
        "invitee_agent_number": "AG-2001",
        "normal_coupon_max_discount_percent": 30,
    }


def test_send_access_invite_posts_manager_with_coupon_scope() -> None:
    service = _FakeAdminService()
    client = _build_client(service)

    response = client.post(
        "/api/v1/admin/access/invitations",
        json={
            "invitee_email": "coupon.manager@example.com",
            "invitee_name": "Coupon Manager",
            "invitee_designation": "Manager",
            "invitee_agent_number": "AG-2002",
            "role": "manager",
            "access_scope": "coupon",
            "normal_coupon_max_discount_percent": 30,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["delivery_status"] == "sent"
    assert payload["invitation"]["invitee_email"] == "coupon.manager@example.com"
    assert payload["invitation"]["role"] == "manager"
    assert payload["invitation"]["access_scope"] == "coupon"

    assert service.last_invite_payload == {
        "invitee_email": "coupon.manager@example.com",
        "role": "manager",
        "access_scope": "coupon",
        "invitee_name": "Coupon Manager",
        "invitee_designation": "Manager",
        "invitee_agent_number": "AG-2002",
        "normal_coupon_max_discount_percent": 30,
    }
