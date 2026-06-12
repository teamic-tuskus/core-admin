"""Administrative management workflows for tenants and subscriptions."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import html
import hmac
import json
import logging
from urllib.parse import quote
from urllib.parse import urlparse
from uuid import uuid4

from app.core.auth import AuthenticatedPrincipal
from app.core.firebase import get_firebase_auth
from app.core.secret_manager import get_secret
from app.core.settings import get_settings
from app.services.email_sender import SmtpEmailSender
from app.services.payment_gateway import RazorpayGateway
from app.services.repositories import (
    PortalAccessInvitationRepository,
    SubscriptionRepository,
    SuperAdminRepository,
    TenantRepository,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


TENANT_NOT_FOUND = "Tenant not found"
SUBSCRIPTION_NOT_FOUND = "Subscription not found"
INVITATION_NOT_FOUND = "Invitation not found"
INVITATION_TOKEN_INVALID = "Invitation token is invalid or expired"
MANAGER_ACCESS_SCOPE_VALUES = {"product", "coupon", "advance_coupon", "both", "all"}
UNSUPPORTED_ROLE = "Unsupported role"


logger = logging.getLogger(__name__)


def _normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def _canonical_portal_url() -> str:
    return "https://coreadmin.tuskus.com"


def _is_super_admin(principal: AuthenticatedPrincipal) -> bool:
    role = str(principal.claims.get("role") or "").lower()
    roles = principal.claims.get("roles")
    if role == "super_admin":
        return True
    if isinstance(roles, list):
        return any(str(item).lower() == "super_admin" for item in roles)
    return False


class AdminService:
    """Tenant and subscription lifecycle operations."""

    def __init__(
        self,
        tenant_repo: TenantRepository,
        subscription_repo: SubscriptionRepository,
        super_admin_repo: SuperAdminRepository,
        portal_access_invitation_repo: PortalAccessInvitationRepository,
        email_sender: SmtpEmailSender,
        gateway: RazorpayGateway | None = None,
    ) -> None:
        self.tenant_repo = tenant_repo
        self.subscription_repo = subscription_repo
        self.super_admin_repo = super_admin_repo
        self.portal_access_invitation_repo = portal_access_invitation_repo
        self.email_sender = email_sender
        self.gateway = gateway or RazorpayGateway()
        self.settings = get_settings()

    def create_tenant(self, payload: dict) -> dict:
        return self.tenant_repo.create(
            {
                "name": payload["name"],
                "company_email": payload["company_email"],
                "contact_name": payload["contact_name"],
                "phone": payload.get("phone"),
                "status": "active",
            }
        )

    def list_tenants(self) -> list[dict]:
        return self.tenant_repo.list()

    def update_tenant(self, tenant_id: str, payload: dict) -> dict:
        tenant = self.tenant_repo.update(tenant_id, payload)
        if tenant is None:
            raise ValueError(TENANT_NOT_FOUND)
        return tenant

    def get_tenant(self, tenant_id: str) -> dict:
        tenant = self.tenant_repo.get(tenant_id)
        if tenant is None:
            raise ValueError(TENANT_NOT_FOUND)
        return tenant

    def list_subscriptions(self) -> list[dict]:
        return self.subscription_repo.list()

    def get_subscription(self, subscription_id: str) -> dict:
        subscription = self.subscription_repo.get(subscription_id)
        if subscription is None:
            raise ValueError(SUBSCRIPTION_NOT_FOUND)
        return subscription

    def update_subscription_status(self, subscription_id: str, status: str) -> dict:
        subscription = self.subscription_repo.update_status(subscription_id, status)
        if subscription is None:
            raise ValueError(SUBSCRIPTION_NOT_FOUND)
        return subscription

    def reconcile_subscription(self, subscription_id: str) -> dict:
        subscription = self.subscription_repo.get(subscription_id)
        if subscription is None:
            raise ValueError(SUBSCRIPTION_NOT_FOUND)

        order_id = subscription.get("razorpay_order_id")
        gateway_subscription_id = subscription.get("razorpay_subscription_id")
        payment_id = subscription.get("razorpay_payment_id")
        gateway_state = None

        if payment_id:
            gateway_state = self.gateway.fetch_payment(str(payment_id))
        elif gateway_subscription_id:
            gateway_state = self.gateway.fetch_subscription(str(gateway_subscription_id))
        elif order_id:
            gateway_state = self.gateway.fetch_order(str(order_id))

        status = str((gateway_state or {}).get("status") or subscription.get("status") or "pending_payment")
        if status in {"captured", "paid"} and subscription.get("status") != "active":
            start_at = subscription.get("start_at") or _now()
            end_at = subscription.get("end_at") or (start_at + _months(subscription["tenure_months"]))
            subscription = self.subscription_repo.activate(
                subscription_id=subscription_id,
                start_at=start_at,
                end_at=end_at,
                payment_id=str(payment_id or (gateway_state or {}).get("id") or ""),
            )
        elif status in {"failed", "refunded", "cancelled"}:
            updated = self.subscription_repo.update_status(subscription_id, status)
            if updated is not None:
                subscription = updated

        subscription["gateway_status"] = status
        subscription["reconciled_at"] = _now()
        return subscription

    def get_super_admin_state(self) -> dict:
        pending = self._get_pending_invitation()
        return {
            "current_super_admin": self.super_admin_repo.get_current(),
            "pending_invitation": pending,
            "recent_invitations": self.super_admin_repo.list_invitations(limit=8),
        }

    def get_portal_access_state(self) -> dict:
        return {
            "operators": self._list_portal_operators(),
            "invitations": self.portal_access_invitation_repo.list(limit=30),
        }

    def get_my_portal_access_invitation(self, principal: AuthenticatedPrincipal) -> dict | None:
        email = _normalize_email(principal.email)
        if not email:
            return None

        invitations = self.portal_access_invitation_repo.list_pending_for_email(email)
        for invitation in invitations:
            if self._is_expired(invitation):
                self.portal_access_invitation_repo.update(
                    str(invitation["id"]),
                    {
                        "status": "expired",
                        "responded_at": _now(),
                        "response_actor_uid": principal.uid,
                        "response_actor_email": email,
                        "response_note": "expired",
                    },
                )
                continue
            return invitation

        return None

    def create_portal_access_invitation(
        self,
        *,
        invitee_email: str,
        invitee_name: str | None = None,
        invitee_designation: str | None = None,
        invitee_agent_number: str | None = None,
        invitee_phone: str | None = None,
        role: str,
        access_scope: str | None,
        normal_coupon_max_discount_percent: int | None = None,
        principal: AuthenticatedPrincipal,
    ) -> dict:
        role_normalized = str(role or "admin").strip().lower()
        if role_normalized not in {"admin", "manager", "super_admin"}:
            raise ValueError(UNSUPPORTED_ROLE)

        inviter_email = _normalize_email(principal.email)
        invitee = _normalize_email(invitee_email)
        normalized_name = str(invitee_name or "").strip() or invitee.split("@")[0].replace(".", " ").title()
        normalized_designation = str(invitee_designation or "").strip() or "Operator"
        normalized_agent_number = str(invitee_agent_number or "").strip().upper() or f"AG-{uuid4().hex[:8].upper()}"
        normalized_phone = "".join(ch for ch in str(invitee_phone or "") if ch.isdigit())
        if not invitee:
            raise ValueError("Invitee email is required")
        if role_normalized in {"admin", "manager"}:
            if normal_coupon_max_discount_percent is None:
                normal_coupon_max_discount_percent = 30

        if role_normalized == "super_admin":
            if not _is_super_admin(principal):
                raise ValueError("Only super admin can invite a super admin")
            return self.create_super_admin_invitation(invitee_email=invitee, principal=principal)

        normalized_scope = self._normalize_module_access_scope(access_scope)
        permissions = self._permissions_for_role(role=role_normalized, access_scope=normalized_scope)

        pending_for_email = self.portal_access_invitation_repo.list_pending_for_email(invitee)
        for pending in pending_for_email:
            if not self._is_expired(pending):
                raise ValueError("This user already has a pending invitation")

        existing_invitations = self.portal_access_invitation_repo.list(limit=300)
        for existing in existing_invitations:
            if str(existing.get("invitee_agent_number") or "").strip().upper() == normalized_agent_number:
                if str(existing.get("status") or "") == "pending":
                    raise ValueError("This agent number already has a pending invitation")

        now = _now()
        invitation = self.portal_access_invitation_repo.create(
            {
                "id": f"pai_{uuid4().hex}",
                "invitee_email": invitee,
                "invitee_name": normalized_name,
                "invitee_designation": normalized_designation,
                "invitee_agent_number": normalized_agent_number,
                "invitee_phone": normalized_phone or None,
                "role": role_normalized,
                "access_scope": normalized_scope,
                "normal_coupon_max_discount_percent": normal_coupon_max_discount_percent,
                "permissions": permissions,
                "status": "pending",
                "invited_at": now,
                "expires_at": now + _days(self.settings.super_admin_invitation_expiry_days),
                "invited_by_uid": principal.uid,
                "invited_by_email": inviter_email,
                "responded_at": None,
                "response_actor_uid": None,
                "response_actor_email": None,
                "response_note": None,
                "resend_count": 0,
                "resend_audit": [],
            }
        )

        delivery_status = self._send_portal_access_invitation_with_retry(invitation)

        return {"invitation": invitation, "delivery_status": delivery_status}

    def accept_portal_access_invitation_by_token(self, *, portal_token: str, principal: AuthenticatedPrincipal) -> dict:
        invitation = self._resolve_portal_invitation_token(portal_token)
        invitation_id = str(invitation.get("id") or "")
        if not invitation_id:
            raise ValueError(INVITATION_TOKEN_INVALID)
        return self.accept_portal_access_invitation(invitation_id=invitation_id, principal=principal)

    def accept_portal_access_invitation(self, *, invitation_id: str, principal: AuthenticatedPrincipal) -> dict:
        invitation = self._load_portal_access_actionable_invitation(invitation_id=invitation_id, principal=principal)

        role = str(invitation.get("role") or "admin").strip().lower()
        invitation_permissions = invitation.get("permissions")
        permissions = (
            sorted({str(item).lower() for item in invitation_permissions})
            if isinstance(invitation_permissions, list)
            else self._permissions_for_role(role=role, access_scope=str(invitation.get("access_scope") or ""))
        )
        self._set_operator_claim_and_profile(
            uid=principal.uid,
            role=role,
            permissions=permissions,
            full_name=str(invitation.get("invitee_name") or "").strip(),
            designation=str(invitation.get("invitee_designation") or "").strip(),
            agent_number=str(invitation.get("invitee_agent_number") or "").strip().upper(),
            normal_coupon_max_discount_percent=invitation.get("normal_coupon_max_discount_percent"),
        )

        updated = self.portal_access_invitation_repo.update(
            invitation_id,
            {
                "status": "accepted",
                "responded_at": _now(),
                "response_actor_uid": principal.uid,
                "response_actor_email": _normalize_email(principal.email),
                "response_note": "accepted",
            },
        )
        if updated is None:
            raise ValueError(INVITATION_NOT_FOUND)

        return {"invitation": updated}

    def reject_portal_access_invitation(self, *, invitation_id: str, principal: AuthenticatedPrincipal) -> dict:
        self._load_portal_access_actionable_invitation(invitation_id=invitation_id, principal=principal)
        updated = self.portal_access_invitation_repo.update(
            invitation_id,
            {
                "status": "rejected",
                "responded_at": _now(),
                "response_actor_uid": principal.uid,
                "response_actor_email": _normalize_email(principal.email),
                "response_note": "rejected",
            },
        )
        if updated is None:
            raise ValueError(INVITATION_NOT_FOUND)

        return {"invitation": updated}

    def reject_portal_access_invitation_by_token(self, *, portal_token: str, principal: AuthenticatedPrincipal) -> dict:
        invitation = self._resolve_portal_invitation_token(portal_token)
        invitation_id = str(invitation.get("id") or "")
        if not invitation_id:
            raise ValueError(INVITATION_TOKEN_INVALID)
        return self.reject_portal_access_invitation(invitation_id=invitation_id, principal=principal)

    def cancel_portal_access_invitation(self, *, invitation_id: str, principal: AuthenticatedPrincipal) -> dict:
        invitation = self.portal_access_invitation_repo.get(invitation_id)
        if invitation is None:
            raise ValueError(INVITATION_NOT_FOUND)
        if invitation.get("status") != "pending":
            raise ValueError("Only pending invitations can be cancelled")

        invitee_email = _normalize_email(invitation.get("invitee_email"))
        if invitee_email:
            self._deprovision_pending_invitee_if_unactivated(invitee_email=invitee_email)

        updated = self.portal_access_invitation_repo.update(
            invitation_id,
            {
                "status": "cancelled",
                "responded_at": _now(),
                "response_actor_uid": principal.uid,
                "response_actor_email": _normalize_email(principal.email),
                "response_note": "cancelled_by_admin",
            },
        )
        if updated is None:
            raise ValueError(INVITATION_NOT_FOUND)
        return {"invitation": updated}

    def _deprovision_pending_invitee_if_unactivated(self, *, invitee_email: str) -> None:
        auth_client = get_firebase_auth()
        uid = self._find_user_uid_by_email(auth_client=auth_client, email=invitee_email)
        if not uid:
            return

        try:
            user = auth_client.get_user(uid)
        except Exception:
            return

        claims = dict(user.custom_claims or {})
        role = self._extract_effective_role(claims)
        portal_permissions = claims.get("portal_permissions")
        has_permissions = isinstance(portal_permissions, list) and len(portal_permissions) > 0

        # Keep active users intact; this cleanup is only for invited users not yet activated.
        if role or has_permissions:
            return

        if hasattr(auth_client, "revoke_refresh_tokens"):
            auth_client.revoke_refresh_tokens(uid)

        if hasattr(auth_client, "update_user"):
            auth_client.update_user(uid, disabled=True)

        if hasattr(auth_client, "delete_user"):
            auth_client.delete_user(uid)

    def _find_user_uid_by_email(self, *, auth_client, email: str) -> str | None:
        normalized = _normalize_email(email)
        if not normalized:
            return None

        if hasattr(auth_client, "get_user_by_email"):
            try:
                user = auth_client.get_user_by_email(normalized)
                return str(getattr(user, "uid", "") or "") or None
            except Exception:
                return None

        page = auth_client.list_users()
        while page is not None:
            for user in page.users:
                if _normalize_email(getattr(user, "email", "")) == normalized:
                    return str(getattr(user, "uid", "") or "") or None
            page = page.get_next_page()

        return None

    def resend_portal_access_invitation(self, *, invitation_id: str, principal: AuthenticatedPrincipal) -> dict:
        invitation = self.portal_access_invitation_repo.get(invitation_id)
        if invitation is None:
            raise ValueError(INVITATION_NOT_FOUND)
        if invitation.get("status") != "pending":
            raise ValueError("Only pending invitations can be resent")
        if self._is_expired(invitation):
            raise ValueError("Cannot resend an expired invitation")

        now = _now()
        self._assert_portal_resend_allowed(invitation=invitation, now=now)

        delivery_status = self._send_portal_access_invitation_with_retry(invitation)

        resend_audit = list(invitation.get("resend_audit") or [])
        resend_audit.append(
            {
                "sent_at": now,
                "sent_by_uid": principal.uid,
                "sent_by_agent_number": self._agent_number_from_principal(principal),
                "sent_by_email": _normalize_email(principal.email),
                "delivery_status": delivery_status,
            }
        )
        updated = self.portal_access_invitation_repo.update(
            invitation_id,
            {
                "resend_count": int(invitation.get("resend_count") or 0) + 1,
                "resend_audit": resend_audit,
            },
        )
        if updated is None:
            raise ValueError(INVITATION_NOT_FOUND)
        return {"invitation": updated, "delivery_status": delivery_status}

    def update_operator_access(
        self,
        *,
        target_uid: str,
        action: str,
        access_scope: str | None = None,
        principal: AuthenticatedPrincipal,
    ) -> dict:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"set_admin", "set_manager", "remove_access"}:
            raise ValueError("Unsupported operator action")

        if normalized_action == "remove_access" and principal.uid == target_uid:
            raise ValueError("You cannot remove your own access")

        auth_client = get_firebase_auth()
        target_user = auth_client.get_user(target_uid)
        claims = dict(target_user.custom_claims or {})
        current_role = self._extract_effective_role(claims)
        if current_role == "super_admin":
            current = self.super_admin_repo.get_current()
            if current and str(current.get("uid") or "") == target_uid:
                raise ValueError("Use super admin transfer flow for the active super admin")

        if normalized_action == "set_admin":
            normalized_scope = self._normalize_module_access_scope(access_scope)
            permissions = self._permissions_for_role(role="admin", access_scope=normalized_scope)
            self._set_operator_claim(uid=target_uid, role="admin", permissions=permissions)
            target_user = auth_client.get_user(target_uid)
            claims = dict(target_user.custom_claims or {})
            return {"uid": target_uid, "agent_number": str(claims.get("agent_number") or ""), "role": "admin", "permissions": permissions}

        if normalized_action == "set_manager":
            normalized_scope = self._normalize_module_access_scope(access_scope)
            permissions = self._permissions_for_role(role="manager", access_scope=normalized_scope)
            self._set_operator_claim(uid=target_uid, role="manager", permissions=permissions)
            target_user = auth_client.get_user(target_uid)
            claims = dict(target_user.custom_claims or {})
            return {"uid": target_uid, "agent_number": str(claims.get("agent_number") or ""), "role": "manager", "permissions": permissions}

        removed_agent_number = str(claims.get("agent_number") or "")
        removed_email = _normalize_email(getattr(target_user, "email", ""))
        self._deprovision_operator(uid=target_uid, invitee_email=removed_email)
        return {"uid": target_uid, "agent_number": removed_agent_number, "role": "none", "permissions": []}

    def get_my_super_admin_invitation(self, principal: AuthenticatedPrincipal) -> dict | None:
        email = _normalize_email(principal.email)
        if not email:
            return None
        invitations = self.super_admin_repo.list_invitations(limit=20)
        for invitation in invitations:
            if invitation.get("status") != "pending":
                continue
            if _normalize_email(invitation.get("invitee_email")) != email:
                continue
            if self._is_expired(invitation):
                self.super_admin_repo.update_invitation(
                    str(invitation["id"]),
                    {
                        "status": "expired",
                        "responded_at": _now(),
                        "response_actor_email": email,
                        "response_actor_uid": principal.uid,
                    },
                )
                continue
            return invitation
        return None

    def create_super_admin_invitation(self, *, invitee_email: str, principal: AuthenticatedPrincipal) -> dict:
        inviter_email = _normalize_email(principal.email)
        if not inviter_email:
            raise ValueError("Authenticated email is required")

        current = self.super_admin_repo.get_current()
        current_email = _normalize_email((current or {}).get("email"))

        if current_email and current_email != inviter_email:
            raise ValueError("Only the current super admin can assign the next super admin")

        candidate_email = _normalize_email(invitee_email)
        if not candidate_email:
            raise ValueError("Invitee email is required")

        if candidate_email == current_email:
            raise ValueError("Selected user is already the super admin")

        pending = self._get_pending_invitation()
        if pending is not None:
            raise ValueError("A super admin invitation is already pending")

        now = _now()
        invitation_id = f"sai_{uuid4().hex}"
        invitation = self.super_admin_repo.create_invitation(
            {
                "id": invitation_id,
                "invitee_email": candidate_email,
                "status": "pending",
                "invited_at": now,
                "expires_at": now + _days(self.settings.super_admin_invitation_expiry_days),
                "invited_by_uid": principal.uid,
                "invited_by_email": inviter_email,
                "responded_at": None,
                "response_actor_uid": None,
                "response_actor_email": None,
                "response_note": None,
                "resend_count": 0,
                "resend_audit": [],
            }
        )

        delivery_status = self._send_super_admin_invitation_with_retry(invitation)

        return {"invitation": invitation, "delivery_status": delivery_status}

    def accept_super_admin_invitation(self, *, invitation_id: str, principal: AuthenticatedPrincipal) -> dict:
        invitation = self._load_actionable_invitation(invitation_id=invitation_id, principal=principal)
        now = _now()

        accepted = self.super_admin_repo.update_invitation(
            invitation_id,
            {
                "status": "accepted",
                "responded_at": now,
                "response_actor_uid": principal.uid,
                "response_actor_email": _normalize_email(principal.email),
                "response_note": "accepted",
            },
        )
        if accepted is None:
            raise ValueError(INVITATION_NOT_FOUND)

        previous = self.super_admin_repo.get_current()
        current = self.super_admin_repo.set_current(
            {
                "uid": principal.uid,
                "email": _normalize_email(principal.email),
                "display_name": str(principal.claims.get("name") or ""),
                "assigned_at": now,
                "assigned_by_uid": invitation.get("invited_by_uid"),
                "assigned_by_email": invitation.get("invited_by_email"),
            }
        )

        self._apply_super_admin_claim_transfer(previous=previous, next_uid=principal.uid)

        return {"invitation": accepted, "current_super_admin": current}

    def reject_super_admin_invitation(self, *, invitation_id: str, principal: AuthenticatedPrincipal) -> dict:
        self._load_actionable_invitation(invitation_id=invitation_id, principal=principal)
        rejected = self.super_admin_repo.update_invitation(
            invitation_id,
            {
                "status": "rejected",
                "responded_at": _now(),
                "response_actor_uid": principal.uid,
                "response_actor_email": _normalize_email(principal.email),
                "response_note": "rejected",
            },
        )
        if rejected is None:
            raise ValueError(INVITATION_NOT_FOUND)

        return {"invitation": rejected, "current_super_admin": self.super_admin_repo.get_current()}

    def cancel_super_admin_invitation(self, *, invitation_id: str, principal: AuthenticatedPrincipal) -> dict:
        invitation = self.super_admin_repo.get_invitation(invitation_id)
        if invitation is None:
            raise ValueError(INVITATION_NOT_FOUND)
        if invitation.get("status") != "pending":
            raise ValueError("Only pending invitations can be cancelled")

        updated = self.super_admin_repo.update_invitation(
            invitation_id,
            {
                "status": "cancelled",
                "responded_at": _now(),
                "response_actor_uid": principal.uid,
                "response_actor_email": _normalize_email(principal.email),
                "response_note": "cancelled_by_admin",
            },
        )
        if updated is None:
            raise ValueError(INVITATION_NOT_FOUND)
        return {"invitation": updated, "current_super_admin": self.super_admin_repo.get_current()}

    def resend_super_admin_invitation(self, *, invitation_id: str, principal: AuthenticatedPrincipal) -> dict:
        invitation = self.super_admin_repo.get_invitation(invitation_id)
        if invitation is None:
            raise ValueError(INVITATION_NOT_FOUND)
        if invitation.get("status") != "pending":
            raise ValueError("Only pending invitations can be resent")
        if self._is_expired(invitation):
            raise ValueError("Cannot resend an expired invitation")

        delivery_status = self._send_super_admin_invitation_with_retry(invitation)

        resend_audit = list(invitation.get("resend_audit") or [])
        resend_audit.append(
            {
                "sent_at": _now(),
                "sent_by_uid": principal.uid,
                "sent_by_email": _normalize_email(principal.email),
                "delivery_status": delivery_status,
            }
        )
        updated = self.super_admin_repo.update_invitation(
            invitation_id,
            {
                "resend_count": int(invitation.get("resend_count") or 0) + 1,
                "resend_audit": resend_audit,
            },
        )
        if updated is None:
            raise ValueError(INVITATION_NOT_FOUND)
        return {
            "invitation": updated,
            "delivery_status": delivery_status,
            "current_super_admin": self.super_admin_repo.get_current(),
        }

    def _load_actionable_invitation(self, *, invitation_id: str, principal: AuthenticatedPrincipal) -> dict:
        invitation = self.super_admin_repo.get_invitation(invitation_id)
        if invitation is None:
            raise ValueError(INVITATION_NOT_FOUND)

        if invitation.get("status") != "pending":
            raise ValueError("Invitation is no longer actionable")

        principal_email = _normalize_email(principal.email)
        invitee_email = _normalize_email(invitation.get("invitee_email"))
        if not principal_email or principal_email != invitee_email:
            raise ValueError("Only the invited user can respond")

        if self._is_expired(invitation):
            self.super_admin_repo.update_invitation(
                invitation_id,
                {
                    "status": "expired",
                    "responded_at": _now(),
                    "response_actor_email": principal_email,
                    "response_note": "expired",
                },
            )
            raise ValueError("Invitation expired")

        return invitation

    def _apply_super_admin_claim_transfer(self, *, previous: dict | None, next_uid: str) -> None:
        previous_uid = str((previous or {}).get("uid") or "")
        if previous_uid and previous_uid != next_uid:
            self._set_super_admin_claim(uid=previous_uid, is_super_admin=False)
        self._set_super_admin_claim(uid=next_uid, is_super_admin=True)

    def _set_super_admin_claim(self, *, uid: str, is_super_admin: bool) -> None:
        auth_client = get_firebase_auth()
        user = auth_client.get_user(uid)
        claims = dict(user.custom_claims or {})

        roles_raw = claims.get("roles")
        roles = {str(item).lower() for item in roles_raw} if isinstance(roles_raw, list) else set()

        role = str(claims.get("role") or "").lower()

        if is_super_admin:
            roles.update({"admin", "super_admin"})
            claims["role"] = "super_admin"
        else:
            roles.discard("super_admin")
            if role == "super_admin":
                claims["role"] = "admin" if "admin" in roles else ""

        if roles:
            claims["roles"] = sorted(roles)
        else:
            claims.pop("roles", None)

        if not claims.get("role"):
            claims.pop("role", None)

        auth_client.set_custom_user_claims(uid, claims)

    def _send_super_admin_invitation_email(self, invitation: dict) -> None:
        portal_base_url = self._resolve_portal_base_url()
        invitation_id = str(invitation["id"])
        open_link = f"{portal_base_url}/users?superAdminInvite={invitation_id}"

        self.email_sender.send_email(
            to_email=str(invitation["invitee_email"]),
            subject="Super Admin invitation - CoreAdmin",
            body_text=(
                "You have been invited to become the Super Admin for CoreAdmin.\n\n"
                f"Open this link to review and respond: {open_link}\n\n"
                "After signing in with this same email address, open Users > Super Admin Control "
                "and choose Accept or Reject.\n"
            ),
            body_html=self._build_invitation_email_html(
                heading="Super Admin invitation",
                message="You have been invited to become the Super Admin for CoreAdmin.",
                cta_label="Review Super Admin Invitation",
                cta_url=open_link,
                secondary_note="After signing in with this same email address, open Users > Super Admin Control and choose Accept or Reject.",
            ),
        )

    def _send_portal_access_invitation_email(self, invitation: dict) -> None:
        portal_base_url = self._resolve_portal_base_url()
        invitation_token = self._build_portal_invitation_token(invitation)
        invitee_email = str(invitation.get("invitee_email") or "").strip().lower()
        open_link = f"{portal_base_url}/invite?portalToken={quote(invitation_token)}&inviteeEmail={quote(invitee_email)}"

        self.email_sender.send_email(
            to_email=str(invitation["invitee_email"]),
            subject="Admin portal access invitation - CoreAdmin",
            body_text=(
                "You have been invited to access the CoreAdmin portal.\n\n"
                f"Open this link to review and respond: {open_link}\n\n"
                "Use this onboarding page to create/set your password, sign in with the same email address, and activate your access.\n"
            ),
                        body_html=self._build_invitation_email_html(
                                heading="Admin portal access invitation",
                                message="You have been invited to access the CoreAdmin portal.",
                                cta_label="Open Invitation",
                                cta_url=open_link,
                                secondary_note="Use this onboarding page to create/set your password, sign in with the same email address, and activate your access.",
                        ),
        )

    def _send_portal_access_invitation_with_retry(self, invitation: dict) -> str:
        try:
            self._send_portal_access_invitation_email(invitation)
            return "sent"
        except Exception as first_exc:
            logger.warning("Portal invitation email send failed; retrying once", exc_info=first_exc)

        try:
            self._send_portal_access_invitation_email(invitation)
            return "sent"
        except Exception:
            logger.exception("Portal invitation email send failed after retry")
            return "failed"

    def _send_super_admin_invitation_with_retry(self, invitation: dict) -> str:
        try:
            self._send_super_admin_invitation_email(invitation)
            return "sent"
        except Exception as first_exc:
            logger.warning("Super admin invitation email send failed; retrying once", exc_info=first_exc)

        try:
            self._send_super_admin_invitation_email(invitation)
            return "sent"
        except Exception:
            logger.exception("Super admin invitation email send failed after retry")
            return "failed"

    def _resolve_portal_base_url(self) -> str:
        configured = str(self.settings.coreadmin_portal_base_url or "").strip().rstrip("/")
        if not configured:
            return _canonical_portal_url()
        if not configured.startswith(("http://", "https://")):
            configured = f"https://{configured}"

        parsed = urlparse(configured)
        host = (parsed.hostname or "").lower()
        if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
            return _canonical_portal_url()
        if not parsed.scheme or not parsed.netloc:
            return _canonical_portal_url()
        return configured

    def _portal_invitation_signing_key(self) -> bytes:
        secret_value = get_secret(self.settings.otp_hash_pepper_secret_id)
        return secret_value.encode("utf-8")

    @staticmethod
    def _b64url_encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _b64url_decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))

    def _build_portal_invitation_token(self, invitation: dict) -> str:
        invitation_id = str(invitation.get("id") or "")
        invitee_email = _normalize_email(invitation.get("invitee_email"))
        expires_at = invitation.get("expires_at")
        if not invitation_id or not invitee_email or not isinstance(expires_at, datetime):
            raise ValueError(INVITATION_TOKEN_INVALID)

        payload = {
            "v": 1,
            "typ": "portal_access",
            "iid": invitation_id,
            "em": invitee_email,
            "exp": int(expires_at.timestamp()),
            "iat": int(_now().timestamp()),
            "nonce": uuid4().hex,
        }

        header = {"alg": "HS256", "typ": "JWT"}
        header_b64 = self._b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_b64 = self._b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        signature = hmac.new(self._portal_invitation_signing_key(), signing_input, hashlib.sha256).digest()
        signature_b64 = self._b64url_encode(signature)
        return f"{header_b64}.{payload_b64}.{signature_b64}"

    def _resolve_portal_invitation_token(self, token: str) -> dict:
        normalized = str(token or "").strip()
        if not normalized:
            raise ValueError(INVITATION_TOKEN_INVALID)

        parts = normalized.split(".")
        if len(parts) != 3:
            raise ValueError(INVITATION_TOKEN_INVALID)

        header_b64, payload_b64, signature_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(self._portal_invitation_signing_key(), signing_input, hashlib.sha256).digest()
        try:
            provided_sig = self._b64url_decode(signature_b64)
        except Exception as exc:
            raise ValueError(INVITATION_TOKEN_INVALID) from exc
        if not hmac.compare_digest(expected_sig, provided_sig):
            raise ValueError(INVITATION_TOKEN_INVALID)

        try:
            payload_raw = self._b64url_decode(payload_b64)
            payload = json.loads(payload_raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError(INVITATION_TOKEN_INVALID) from exc

        if payload.get("typ") != "portal_access":
            raise ValueError(INVITATION_TOKEN_INVALID)

        expires_at_epoch = int(payload.get("exp") or 0)
        if expires_at_epoch <= int(_now().timestamp()):
            raise ValueError(INVITATION_TOKEN_INVALID)

        invitation_id = str(payload.get("iid") or "")
        expected_email = _normalize_email(payload.get("em"))
        if not invitation_id or not expected_email:
            raise ValueError(INVITATION_TOKEN_INVALID)

        invitation = self.portal_access_invitation_repo.get(invitation_id)
        if invitation is None:
            raise ValueError(INVITATION_TOKEN_INVALID)
        if invitation.get("status") != "pending":
            raise ValueError(INVITATION_TOKEN_INVALID)
        if self._is_expired(invitation):
            raise ValueError(INVITATION_TOKEN_INVALID)

        invitee_email = _normalize_email(invitation.get("invitee_email"))
        if invitee_email != expected_email:
            raise ValueError(INVITATION_TOKEN_INVALID)

        return invitation

    def _assert_portal_resend_allowed(self, *, invitation: dict, now: datetime) -> None:
        resend_audit_raw = list(invitation.get("resend_audit") or [])
        resend_times: list[datetime] = []
        for entry in resend_audit_raw:
            sent_at = entry.get("sent_at") if isinstance(entry, dict) else None
            if isinstance(sent_at, datetime):
                resend_times.append(sent_at)

        if resend_times:
            latest = max(resend_times)
            retry_after_seconds = self.settings.portal_invitation_resend_cooldown_seconds - int((now - latest).total_seconds())
            if retry_after_seconds > 0:
                raise ValueError(f"Cannot resend yet. Try again in {retry_after_seconds} seconds")

        window_seconds = 3600
        recent_count = 0
        for sent_at in resend_times:
            age_seconds = (now - sent_at).total_seconds()
            if 0 <= age_seconds <= window_seconds:
                recent_count += 1
        if recent_count >= self.settings.portal_invitation_resend_max_per_hour:
            raise ValueError("Cannot resend invitation now. Hourly resend limit reached")

    def _build_invitation_email_html(
        self,
        *,
        heading: str,
        message: str,
        cta_label: str,
        cta_url: str,
        secondary_note: str,
    ) -> str:
        safe_heading = html.escape(heading)
        safe_message = html.escape(message)
        safe_cta_label = html.escape(cta_label)
        safe_cta_url = html.escape(cta_url, quote=True)
        safe_secondary_note = html.escape(secondary_note)
        safe_support_email = html.escape(self.settings.support_email)

        return f"""
<!doctype html>
<html>
    <body style=\"margin:0;padding:0;background:#eef2ff;font-family:'Segoe UI',Arial,sans-serif;\">
        <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"padding:28px 12px;\">
            <tr>
                <td align=\"center\">
                    <table role=\"presentation\" width=\"620\" cellpadding=\"0\" cellspacing=\"0\" style=\"width:100%;max-width:620px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 18px 44px rgba(15,23,42,0.12);\">
                        <tr>
                            <td style=\"background:linear-gradient(135deg,#0f172a,#1d4ed8);padding:30px 32px;\">
                                <p style=\"margin:0;color:#bfdbfe;font-size:12px;letter-spacing:0.8px;text-transform:uppercase;font-weight:800;\">CoreAdmin</p>
                                <h1 style=\"margin:8px 0 0;color:#ffffff;font-size:24px;line-height:1.3;\">{safe_heading}</h1>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"padding:28px 32px 10px;\">
                                <p style=\"margin:0;color:#1e293b;font-size:15px;line-height:1.7;\">{safe_message}</p>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"padding:8px 32px 8px;\">
                                <a href=\"{safe_cta_url}\" style=\"display:inline-block;background:#1d4ed8;color:#ffffff;text-decoration:none;font-size:14px;font-weight:700;padding:12px 18px;border-radius:10px;\">{safe_cta_label}</a>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"padding:8px 32px 8px;\">
                                <p style=\"margin:0;color:#334155;font-size:13px;line-height:1.7;\">{safe_secondary_note}</p>
                            </td>
                        </tr>
                        <tr>
                            <td style=\"padding:12px 32px 28px;\">
                                <p style=\"margin:0;color:#475569;font-size:12px;line-height:1.6;\">Need help? Contact <a href=\"mailto:{safe_support_email}\" style=\"color:#1d4ed8;font-weight:700;\">{safe_support_email}</a>.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
</html>
"""

    def _load_portal_access_actionable_invitation(
        self,
        *,
        invitation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> dict:
        invitation = self.portal_access_invitation_repo.get(invitation_id)
        if invitation is None:
            raise ValueError(INVITATION_NOT_FOUND)

        if invitation.get("status") != "pending":
            raise ValueError("Invitation is no longer actionable")

        principal_email = _normalize_email(principal.email)
        invitee_email = _normalize_email(invitation.get("invitee_email"))
        if not principal_email or principal_email != invitee_email:
            raise ValueError("Only the invited user can respond")

        if self._is_expired(invitation):
            self.portal_access_invitation_repo.update(
                invitation_id,
                {
                    "status": "expired",
                    "responded_at": _now(),
                    "response_actor_uid": principal.uid,
                    "response_actor_email": principal_email,
                    "response_note": "expired",
                },
            )
            raise ValueError("Invitation expired")

        return invitation

    def _set_operator_claim(self, *, uid: str, role: str, permissions: list[str]) -> None:
        auth_client = get_firebase_auth()
        user = auth_client.get_user(uid)
        claims = dict(user.custom_claims or {})

        roles_raw = claims.get("roles")
        roles = {str(item).lower() for item in roles_raw} if isinstance(roles_raw, list) else set()

        if role == "super_admin":
            roles.discard("manager")
            roles.update({"admin", "super_admin"})
            claims["role"] = "super_admin"
        elif role == "admin":
            roles.discard("manager")
            roles.add("admin")
            claims["role"] = "admin"
        elif role == "manager":
            roles.discard("admin")
            roles.discard("super_admin")
            roles.add("manager")
            claims["role"] = "manager"
        else:
            raise ValueError(UNSUPPORTED_ROLE)

        claims["roles"] = sorted(roles)
        claims["portal_permissions"] = sorted({str(item).lower() for item in permissions})
        auth_client.set_custom_user_claims(uid, claims)

    def _set_operator_claim_and_profile(
        self,
        *,
        uid: str,
        role: str,
        permissions: list[str],
        full_name: str,
        designation: str,
        agent_number: str,
        normal_coupon_max_discount_percent: int | None,
    ) -> None:
        auth_client = get_firebase_auth()
        user = auth_client.get_user(uid)
        claims = dict(user.custom_claims or {})

        roles_raw = claims.get("roles")
        roles = {str(item).lower() for item in roles_raw} if isinstance(roles_raw, list) else set()

        if role == "super_admin":
            roles.discard("manager")
            roles.update({"admin", "super_admin"})
            claims["role"] = "super_admin"
        elif role == "admin":
            roles.discard("manager")
            roles.add("admin")
            claims["role"] = "admin"
        elif role == "manager":
            roles.discard("admin")
            roles.discard("super_admin")
            roles.add("manager")
            claims["role"] = "manager"
        else:
            raise ValueError(UNSUPPORTED_ROLE)

        claims["roles"] = sorted(roles)
        claims["portal_permissions"] = sorted({str(item).lower() for item in permissions})
        if full_name:
            claims["full_name"] = full_name
        if designation:
            claims["designation"] = designation
        if agent_number:
            claims["agent_number"] = agent_number
        claims["normal_coupon_max_discount_percent"] = normal_coupon_max_discount_percent
        claims.pop("normal_coupon_max_discount_amount_paise", None)
        auth_client.set_custom_user_claims(uid, claims)

    def _clear_operator_claim(self, *, uid: str) -> None:
        auth_client = get_firebase_auth()
        user = auth_client.get_user(uid)
        claims = dict(user.custom_claims or {})
        roles_raw = claims.get("roles")
        roles = {str(item).lower() for item in roles_raw} if isinstance(roles_raw, list) else set()

        roles.discard("admin")
        roles.discard("super_admin")
        roles.discard("manager")

        role = str(claims.get("role") or "").lower()
        if role in {"admin", "super_admin"}:
            claims.pop("role", None)

        if roles:
            claims["roles"] = sorted(roles)
        else:
            claims.pop("roles", None)

        claims.pop("portal_permissions", None)

        auth_client.set_custom_user_claims(uid, claims)

    def _deprovision_operator(self, *, uid: str, invitee_email: str) -> None:
        auth_client = get_firebase_auth()

        # Remove role/permission claims first so authz is denied even if delete fails.
        self._clear_operator_claim(uid=uid)

        if hasattr(auth_client, "revoke_refresh_tokens"):
            auth_client.revoke_refresh_tokens(uid)

        if hasattr(auth_client, "update_user"):
            auth_client.update_user(uid, disabled=True)

        if hasattr(auth_client, "delete_user"):
            auth_client.delete_user(uid)

        if invitee_email:
            pending = self.portal_access_invitation_repo.list_pending_for_email(invitee_email)
            for invitation in pending:
                self.portal_access_invitation_repo.update(
                    str(invitation.get("id") or ""),
                    {
                        "status": "cancelled",
                        "responded_at": _now(),
                        "response_actor_uid": "system",
                        "response_actor_email": "system@coreadmin",
                        "response_note": "access_removed",
                    },
                )

    def _list_portal_operators(self) -> list[dict]:
        auth_client = get_firebase_auth()
        page = auth_client.list_users()
        operators: list[dict] = []

        while page is not None:
            for user in page.users:
                effective_role = self._extract_effective_role(dict(user.custom_claims or {}))
                if not effective_role:
                    continue
                operators.append(self._map_operator(user=user, role=effective_role))

            page = page.get_next_page()

        return sorted(operators, key=lambda item: (item["role"] != "super_admin", item["email"]))

    @staticmethod
    def _extract_effective_role(claims: dict) -> str:
        roles_raw = claims.get("roles")
        roles = {str(item).lower() for item in roles_raw} if isinstance(roles_raw, list) else set()
        role = str(claims.get("role") or "").lower()

        if role == "super_admin" or "super_admin" in roles:
            return "super_admin"
        if role == "admin" or "admin" in roles:
            return "admin"
        if role == "manager" or "manager" in roles:
            return "manager"
        return ""

    @staticmethod
    def _normalize_module_access_scope(access_scope: str | None) -> str | None:
        normalized = str(access_scope or "").strip().lower()
        if not normalized:
            return "both"
        if normalized not in MANAGER_ACCESS_SCOPE_VALUES:
            raise ValueError("Module access scope must be product, coupon, advance_coupon, both, or all")
        return normalized

    @staticmethod
    def _permissions_for_role(*, role: str, access_scope: str | None) -> list[str]:
        if role not in {"admin", "manager", "super_admin"}:
            raise ValueError(UNSUPPORTED_ROLE)

        normalized_scope = str(access_scope or "").strip().lower()
        if normalized_scope not in MANAGER_ACCESS_SCOPE_VALUES:
            raise ValueError("Module access scope must be product, coupon, advance_coupon, both, or all")

        permissions: set[str] = set()
        if normalized_scope in {"product", "both", "all"}:
            permissions.add("products")
        if normalized_scope in {"coupon", "both", "all"}:
            permissions.add("coupons")
        if normalized_scope in {"advance_coupon", "all"}:
            permissions.add("advance_coupons")
            permissions.add("coupons")

        if role in {"admin", "super_admin"}:
            permissions.add("users")

        return sorted(permissions)

    @staticmethod
    def _timestamp_from_ms(value: int | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)

    def _map_operator(self, *, user, role: str) -> dict:
        metadata = getattr(user, "user_metadata", None)
        created_at = self._timestamp_from_ms(getattr(metadata, "creation_timestamp", None))
        last_sign_in_at = self._timestamp_from_ms(getattr(metadata, "last_sign_in_timestamp", None))
        claims = dict(user.custom_claims or {})
        raw_permissions = claims.get("portal_permissions")
        permissions = sorted({str(item).lower() for item in raw_permissions}) if isinstance(raw_permissions, list) else []
        full_name = str(claims.get("full_name") or user.display_name or "").strip() or None
        designation = str(claims.get("designation") or "").strip() or None
        agent_number = str(claims.get("agent_number") or "").strip().upper()
        if not agent_number:
            agent_number = f"AG-{str(user.uid)[-6:].upper()}"

        return {
            "uid": user.uid,
            "agent_number": agent_number,
            "email": user.email or "",
            "full_name": full_name,
            "display_name": user.display_name,
            "designation": designation,
            "role": role,
            "permissions": permissions,
            "disabled": bool(user.disabled),
            "created_at": created_at,
            "last_sign_in_at": last_sign_in_at,
        }

    @staticmethod
    def _agent_number_from_principal(principal: AuthenticatedPrincipal) -> str | None:
        value = principal.claims.get("agent_number")
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
        return None

    def _get_pending_invitation(self) -> dict | None:
        pending = self.super_admin_repo.get_pending_invitation()
        if pending is None:
            return None
        if self._is_expired(pending):
            self.super_admin_repo.update_invitation(
                str(pending["id"]),
                {
                    "status": "expired",
                    "responded_at": _now(),
                    "response_note": "expired",
                },
            )
            return None
        return pending

    @staticmethod
    def _is_expired(invitation: dict) -> bool:
        expires_at = invitation.get("expires_at")
        if expires_at is None:
            return False
        return _now() > expires_at


def _months(value: int):
    from dateutil.relativedelta import relativedelta

    return relativedelta(months=int(value))


def _days(value: int):
    from dateutil.relativedelta import relativedelta

    return relativedelta(days=int(value))
