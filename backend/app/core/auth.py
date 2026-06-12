"""Firebase authentication and authorization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.firebase import get_firebase_auth

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Minimal authenticated identity payload."""

    uid: str
    email: str | None
    claims: dict


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedPrincipal:
    """Verify Firebase ID token and return the authenticated principal."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        auth_client = get_firebase_auth()
        decoded = auth_client.verify_id_token(credentials.credentials, check_revoked=True)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    uid = str(decoded.get("uid") or decoded.get("user_id") or "")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")

    # Enforce authorization from the latest server-side custom claims, not stale token payload.
    try:
        user = auth_client.get_user(uid)
        latest_claims = dict(user.custom_claims or {})
    except Exception:
        latest_claims = {}

    merged_claims = dict(decoded)
    merged_claims.update(latest_claims)

    return AuthenticatedPrincipal(
        uid=uid,
        email=decoded.get("email"),
        claims=merged_claims,
    )


def require_admin(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
    """Require super-admin or admin access."""
    role = str(principal.claims.get("role") or "").lower()
    roles = principal.claims.get("roles")
    is_admin = role in {"admin", "super_admin"}
    if isinstance(roles, list):
        is_admin = is_admin or any(str(item).lower() in {"admin", "super_admin"} for item in roles)
    if not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return principal


def _principal_permissions(principal: AuthenticatedPrincipal) -> set[str]:
    permissions_raw = principal.claims.get("portal_permissions")
    permissions = {str(item).lower() for item in permissions_raw} if isinstance(permissions_raw, list) else set()

    role = str(principal.claims.get("role") or "").lower()
    roles_raw = principal.claims.get("roles")
    roles = {str(item).lower() for item in roles_raw} if isinstance(roles_raw, list) else set()

    if role in {"admin", "super_admin"} or "admin" in roles or "super_admin" in roles:
        permissions.add("users")

    if role == "super_admin" or "super_admin" in roles:
        permissions.update({"products", "coupons", "advance_coupons"})

    return permissions


def require_portal_permission(permission: str) -> Callable[[AuthenticatedPrincipal], AuthenticatedPrincipal]:
    normalized_permission = permission.strip().lower()

    def dependency(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
        permissions = _principal_permissions(principal)
        if normalized_permission not in permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return principal

    return dependency


require_products_access = require_portal_permission("products")
require_coupons_access = require_portal_permission("coupons")
