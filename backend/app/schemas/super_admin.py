"""Schemas for super admin assignment and invitation lifecycle."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InvitationResendAuditEvent(BaseModel):
    sent_at: datetime
    sent_by_uid: str
    sent_by_email: str
    delivery_status: str


class SuperAdminAssignmentResponse(BaseModel):
    uid: str
    email: str
    display_name: str | None = None
    assigned_at: datetime
    assigned_by_uid: str | None = None
    assigned_by_email: str | None = None
    updated_at: datetime


class SuperAdminInvitationResponse(BaseModel):
    id: str
    invitee_email: str
    status: str
    invited_at: datetime
    expires_at: datetime
    invited_by_uid: str
    invited_by_email: str
    responded_at: datetime | None = None
    response_actor_uid: str | None = None
    response_actor_email: str | None = None
    response_note: str | None = None
    resend_count: int = 0
    resend_audit: list[InvitationResendAuditEvent] = []


class SuperAdminStateResponse(BaseModel):
    current_super_admin: SuperAdminAssignmentResponse | None = None
    pending_invitation: SuperAdminInvitationResponse | None = None
    recent_invitations: list[SuperAdminInvitationResponse] = []


class SuperAdminInviteRequest(BaseModel):
    invitee_email: str = Field(min_length=3, max_length=255)


class SuperAdminInviteResponse(BaseModel):
    invitation: SuperAdminInvitationResponse
    delivery_status: str


class SuperAdminInvitationActionResponse(BaseModel):
    invitation: SuperAdminInvitationResponse
    current_super_admin: SuperAdminAssignmentResponse | None = None
