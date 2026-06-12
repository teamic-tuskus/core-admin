"""Schemas for admin portal access onboarding workflows."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InvitationResendAuditEvent(BaseModel):
    sent_at: datetime
    sent_by_uid: str | None = None
    sent_by_agent_number: str | None = None
    sent_by_email: str
    delivery_status: str


class PortalOperatorResponse(BaseModel):
    uid: str
    agent_number: str
    email: str
    full_name: str | None = None
    display_name: str | None = None
    designation: str | None = None
    role: str
    permissions: list[str] = []
    disabled: bool
    created_at: datetime | None = None
    last_sign_in_at: datetime | None = None


class PortalAccessInvitationResponse(BaseModel):
    id: str
    invitee_email: str
    invitee_name: str | None = None
    invitee_designation: str | None = None
    invitee_agent_number: str | None = None
    invitee_phone: str | None = None
    role: str
    access_scope: str | None = None
    normal_coupon_max_discount_percent: int | None = None
    normal_coupon_max_discount_amount_paise: int | None = None
    permissions: list[str] = []
    status: str
    invited_at: datetime
    expires_at: datetime
    invited_by_uid: str | None = None
    invited_by_email: str
    responded_at: datetime | None = None
    response_actor_uid: str | None = None
    response_actor_email: str | None = None
    response_note: str | None = None
    resend_count: int = 0
    resend_audit: list[InvitationResendAuditEvent] = []


class PortalAccessStateResponse(BaseModel):
    operators: list[PortalOperatorResponse]
    invitations: list[PortalAccessInvitationResponse]


class PortalAccessInviteRequest(BaseModel):
    invitee_email: str = Field(min_length=3, max_length=255)
    invitee_name: str | None = Field(default=None, max_length=120)
    invitee_designation: str | None = Field(default=None, max_length=120)
    invitee_agent_number: str | None = Field(default=None, max_length=32)
    invitee_phone: str | None = Field(default=None, max_length=32)
    role: str = Field(default="admin", max_length=32)
    access_scope: str | None = Field(default=None, max_length=24)
    normal_coupon_max_discount_percent: int | None = Field(default=None, ge=1, le=100)


class PortalAccessInviteResponse(BaseModel):
    invitation: PortalAccessInvitationResponse
    delivery_status: str


class PortalAccessInvitationActionResponse(BaseModel):
    invitation: PortalAccessInvitationResponse


class PortalAccessInvitationTokenActionRequest(BaseModel):
    portal_token: str = Field(min_length=16, max_length=4096)


class PortalOperatorAccessUpdateRequest(BaseModel):
    action: str = Field(min_length=3, max_length=32)
    access_scope: str | None = Field(default=None, max_length=24)


class PortalOperatorAccessUpdateResponse(BaseModel):
    uid: str
    agent_number: str
    role: str
    permissions: list[str] = []

