"""Admin routes for tenant and subscription management."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthenticatedPrincipal, get_current_principal, require_admin
from app.schemas.access_onboarding import (
    PortalAccessInvitationActionResponse,
    PortalAccessInvitationResponse,
    PortalAccessInviteRequest,
    PortalAccessInviteResponse,
    PortalAccessInvitationTokenActionRequest,
    PortalOperatorAccessUpdateRequest,
    PortalOperatorAccessUpdateResponse,
    PortalAccessStateResponse,
)
from app.schemas.super_admin import (
    SuperAdminInvitationActionResponse,
    SuperAdminInviteRequest,
    SuperAdminInviteResponse,
    SuperAdminInvitationResponse,
    SuperAdminStateResponse,
)
from app.schemas.tenant import (
    SubscriptionAdminResponse,
    TenantCreateRequest,
    TenantResponse,
    TenantUpdateRequest,
    SubscriptionStatusUpdateRequest,
)
from app.services.admin_container import get_admin_service
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["admin"])


def _public_admin_error(exc: ValueError) -> str:
    message = str(exc).strip()
    if not message:
        return "Request could not be completed."
    allowed_prefixes = (
        "Only ",
        "Cannot ",
    )
    allowed_exact = {
        "Tenant not found",
        "Subscription not found",
        "Invitation not found",
        "Invalid tenant payload",
        "Invalid status value",
        "Unsupported role",
        "Unsupported operator action",
        "This user already has a pending invitation",
        "This agent number already has a pending invitation",
        "Only pending invitations can be cancelled",
        "Only pending invitations can be resent",
        "Cannot resend an expired invitation",
        "Cannot resend invitation now. Hourly resend limit reached",
        "Invitation is no longer actionable",
        "Invitation expired",
        "Invitation token is invalid or expired",
        "You cannot remove your own access",
        "You cannot demote your own account",
    }
    if message in allowed_exact:
        return message
    if any(message.startswith(prefix) for prefix in allowed_prefixes):
        return message
    return "Request could not be completed."


@router.post("/tenants", responses={400: {"description": "Invalid tenant payload"}})
async def create_tenant(
    payload: TenantCreateRequest,
    _: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> TenantResponse:
    try:
        item = admin_service.create_tenant(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return TenantResponse(**item)


@router.get("/tenants")
async def list_tenants(
    _: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> list[TenantResponse]:
    return [TenantResponse(**item) for item in admin_service.list_tenants()]


@router.patch("/tenants/{tenant_id}", responses={404: {"description": "Tenant not found"}})
async def update_tenant(
    tenant_id: str,
    payload: TenantUpdateRequest,
    _: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> TenantResponse:
    try:
        item = admin_service.update_tenant(tenant_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=_public_admin_error(exc)) from exc
    return TenantResponse(**item)


@router.get("/subscriptions")
async def list_subscriptions(
    _: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> list[SubscriptionAdminResponse]:
    return [SubscriptionAdminResponse(**item) for item in admin_service.list_subscriptions()]


@router.patch(
    "/subscriptions/{subscription_id}/status",
    responses={404: {"description": "Subscription not found"}},
)
async def update_subscription_status(
    subscription_id: str,
    status_payload: SubscriptionStatusUpdateRequest,
    _: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> SubscriptionAdminResponse:
    try:
        item = admin_service.update_subscription_status(subscription_id, status_payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=_public_admin_error(exc)) from exc
    return SubscriptionAdminResponse(**item)


@router.post(
    "/subscriptions/{subscription_id}/reconcile",
    responses={404: {"description": "Subscription not found"}},
)
async def reconcile_subscription(
    subscription_id: str,
    _: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> SubscriptionAdminResponse:
    try:
        item = admin_service.reconcile_subscription(subscription_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=_public_admin_error(exc)) from exc
    return SubscriptionAdminResponse(**item)


@router.get("/super-admin")
async def get_super_admin_state(
    _: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> SuperAdminStateResponse:
    return SuperAdminStateResponse(**admin_service.get_super_admin_state())


@router.post(
    "/super-admin/invitations",
    responses={400: {"description": "Super admin invitation failed"}},
)
async def invite_super_admin(
    payload: SuperAdminInviteRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> SuperAdminInviteResponse:
    try:
        item = admin_service.create_super_admin_invitation(
            invitee_email=payload.invitee_email,
            principal=principal,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return SuperAdminInviteResponse(**item)


@router.get("/super-admin/invitations/me")
async def get_my_super_admin_invitation(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> SuperAdminInvitationResponse | None:
    item = admin_service.get_my_super_admin_invitation(principal=principal)
    return SuperAdminInvitationResponse(**item) if item else None


@router.post(
    "/super-admin/invitations/{invitation_id}/accept",
    responses={400: {"description": "Invitation accept failed"}},
)
async def accept_super_admin_invitation(
    invitation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> SuperAdminInvitationActionResponse:
    try:
        item = admin_service.accept_super_admin_invitation(invitation_id=invitation_id, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return SuperAdminInvitationActionResponse(**item)


@router.post(
    "/super-admin/invitations/{invitation_id}/reject",
    responses={400: {"description": "Invitation reject failed"}},
)
async def reject_super_admin_invitation(
    invitation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> SuperAdminInvitationActionResponse:
    try:
        item = admin_service.reject_super_admin_invitation(invitation_id=invitation_id, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return SuperAdminInvitationActionResponse(**item)


@router.post(
    "/super-admin/invitations/{invitation_id}/cancel",
    responses={400: {"description": "Invitation cancel failed"}},
)
async def cancel_super_admin_invitation(
    invitation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> SuperAdminInvitationActionResponse:
    try:
        item = admin_service.cancel_super_admin_invitation(invitation_id=invitation_id, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return SuperAdminInvitationActionResponse(**item)


@router.post(
    "/super-admin/invitations/{invitation_id}/resend",
    responses={400: {"description": "Invitation resend failed"}},
)
async def resend_super_admin_invitation(
    invitation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> SuperAdminInviteResponse:
    try:
        item = admin_service.resend_super_admin_invitation(invitation_id=invitation_id, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return SuperAdminInviteResponse(**item)


@router.get("/access")
async def get_portal_access_state(
    _: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> PortalAccessStateResponse:
    return PortalAccessStateResponse(**admin_service.get_portal_access_state())


@router.post(
    "/access/invitations",
    responses={400: {"description": "Portal access invitation failed"}},
)
async def invite_portal_access(
    payload: PortalAccessInviteRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> PortalAccessInviteResponse:
    try:
        invite_payload = payload.model_dump(exclude_none=True)
        item = admin_service.create_portal_access_invitation(principal=principal, **invite_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return PortalAccessInviteResponse(**item)


@router.get("/access/invitations/me")
async def get_my_portal_access_invitation(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> PortalAccessInvitationResponse | None:
    item = admin_service.get_my_portal_access_invitation(principal=principal)
    return PortalAccessInvitationResponse(**item) if item else None


@router.post(
    "/access/invitations/{invitation_id}/accept",
    responses={400: {"description": "Invitation accept failed"}},
)
async def accept_portal_access_invitation(
    invitation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> PortalAccessInvitationActionResponse:
    try:
        item = admin_service.accept_portal_access_invitation(invitation_id=invitation_id, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return PortalAccessInvitationActionResponse(**item)


@router.post(
    "/access/invitations/token/accept",
    responses={400: {"description": "Invitation accept failed"}},
)
async def accept_portal_access_invitation_by_token(
    payload: PortalAccessInvitationTokenActionRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> PortalAccessInvitationActionResponse:
    try:
        item = admin_service.accept_portal_access_invitation_by_token(portal_token=payload.portal_token, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return PortalAccessInvitationActionResponse(**item)


@router.post(
    "/access/invitations/{invitation_id}/reject",
    responses={400: {"description": "Invitation reject failed"}},
)
async def reject_portal_access_invitation(
    invitation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> PortalAccessInvitationActionResponse:
    try:
        item = admin_service.reject_portal_access_invitation(invitation_id=invitation_id, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return PortalAccessInvitationActionResponse(**item)


@router.post(
    "/access/invitations/token/reject",
    responses={400: {"description": "Invitation reject failed"}},
)
async def reject_portal_access_invitation_by_token(
    payload: PortalAccessInvitationTokenActionRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> PortalAccessInvitationActionResponse:
    try:
        item = admin_service.reject_portal_access_invitation_by_token(portal_token=payload.portal_token, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return PortalAccessInvitationActionResponse(**item)


@router.post(
    "/access/invitations/{invitation_id}/cancel",
    responses={400: {"description": "Invitation cancel failed"}},
)
async def cancel_portal_access_invitation(
    invitation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> PortalAccessInvitationActionResponse:
    try:
        item = admin_service.cancel_portal_access_invitation(invitation_id=invitation_id, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return PortalAccessInvitationActionResponse(**item)


@router.post(
    "/access/invitations/{invitation_id}/resend",
    responses={400: {"description": "Invitation resend failed"}},
)
async def resend_portal_access_invitation(
    invitation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> PortalAccessInviteResponse:
    try:
        item = admin_service.resend_portal_access_invitation(invitation_id=invitation_id, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return PortalAccessInviteResponse(**item)


@router.patch(
    "/access/operators/{uid}",
    responses={400: {"description": "Portal operator update failed"}},
)
async def update_portal_operator_access(
    uid: str,
    payload: PortalOperatorAccessUpdateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    admin_service: Annotated[AdminService, Depends(get_admin_service)],
) -> PortalOperatorAccessUpdateResponse:
    try:
        update_payload = payload.model_dump(exclude_none=True)
        item = admin_service.update_operator_access(target_uid=uid, principal=principal, **update_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_admin_error(exc)) from exc
    return PortalOperatorAccessUpdateResponse(**item)
