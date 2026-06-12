"""Schemas for sales onboarding flow after checkout payment."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class GstVerifyRequest(BaseModel):
    subscription_id: str = Field(min_length=8, max_length=128)
    gstin: str = Field(min_length=15, max_length=15)

    @field_validator("gstin")
    @classmethod
    def normalize_gstin(cls, value: str) -> str:
        return value.strip().upper()


class GstProfileResponse(BaseModel):
    """Minimal GST profile surface exposed to the public checkout flow.

    Only the organisation name, masked contact details, and registered address
    (used to prefill the location step) are returned. Full taxpayer details are
    retained server-side and never sent to the client.
    """

    gstin: str
    organisation_name: str
    masked_email: str | None = None
    masked_phone: str | None = None
    address: str | None = None


class GstVerifyResponse(BaseModel):
    transaction_id: str
    data: GstProfileResponse


class OnboardingOtpSendRequest(BaseModel):
    subscription_id: str = Field(min_length=8, max_length=128)
    gstin: str = Field(min_length=15, max_length=15)
    transaction_id: str | None = Field(default=None, max_length=128)
    otp_channel: Literal["email", "sms"] | None = Field(default="email")


class OnboardingOtpSendResponse(BaseModel):
    otp_session_id: str
    otp_channel: Literal["email", "sms"] | None = None
    masked_target: str | None = None


class OnboardingOtpVerifyRequest(BaseModel):
    otp_session_id: str = Field(min_length=8, max_length=128)
    otp_code: str | None = Field(default=None, min_length=4, max_length=12)
    # Legacy dual-OTP fields kept for backward compat; ignored when otp_code is set
    email_otp: str | None = Field(default=None, min_length=4, max_length=12)
    phone_otp: str | None = Field(default=None, min_length=4, max_length=12)


class OnboardingOtpVerifyResponse(BaseModel):
    verified: bool


class OnboardingCompleteRequest(BaseModel):
    subscription_id: str = Field(min_length=8, max_length=128)
    selected_plan: str = Field(min_length=2, max_length=64)
    billing_contact: dict[str, Any]
    gst_profile: dict[str, Any]
    head_office_location: dict[str, Any]
    role_assignment: dict[str, Any]


class OnboardingCompleteResponse(BaseModel):
    tenant_id: str
    super_admin_email: str
    onboarding_status: str
    completed_at: datetime
    credentials_setup_token: str
    credentials_setup_token_expires_at: datetime


class OnboardingCredentialsRequest(BaseModel):
    tenant_id: str = Field(min_length=4, max_length=64)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    setup_token: str = Field(min_length=16, max_length=512)


class OnboardingCredentialsResponse(BaseModel):
    email: str
    account_created: bool
