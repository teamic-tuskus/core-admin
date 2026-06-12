"""Schemas for robust email OTP delivery and verification."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, Field, field_validator

OtpChannel = Literal["email"]


class OtpSendRequest(BaseModel):
    """Request payload to create and dispatch an OTP challenge."""

    channel: OtpChannel
    target: str = Field(min_length=5, max_length=128)
    purpose: str = Field(min_length=3, max_length=64)

    @field_validator("target")
    @classmethod
    def validate_target_format(cls, value: str, info):
        channel = info.data.get("channel")
        target = value.strip()
        if channel == "email":
            try:
                parsed = validate_email(target, check_deliverability=False)
            except EmailNotValidError as exc:
                raise ValueError("Invalid email address") from exc
            return parsed.normalized
        raise ValueError("Only email OTP channel is supported")


class OtpSendResponse(BaseModel):
    """Metadata returned when OTP dispatch is accepted."""

    challenge_id: str
    channel: OtpChannel
    masked_target: str
    expires_at: datetime
    resend_available_at: datetime


class OtpVerifyRequest(BaseModel):
    """Request payload to verify an OTP challenge."""

    challenge_id: str = Field(min_length=8, max_length=64)
    otp_code: str = Field(min_length=4, max_length=12)


class OtpVerifyResponse(BaseModel):
    """Verification result payload."""

    verified: bool
    purpose: str
    channel: OtpChannel
    target: str
    verified_at: datetime
