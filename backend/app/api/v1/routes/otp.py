"""Public OTP routes for email verification."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.otp import OtpSendRequest, OtpSendResponse, OtpVerifyRequest, OtpVerifyResponse
from app.services.container import get_otp_service
from app.services.otp_service import OtpError, OtpService

router = APIRouter(prefix="/otp", tags=["otp"])


def _public_otp_error(exc: Exception, fallback: str) -> str:
    message = str(exc).strip()
    if not message:
        return fallback
    allowed_prefixes = (
        "Please wait ",
        "Too many OTP requests",
        "Invalid OTP",
    )
    allowed_exact = {
        "OTP challenge not found",
        "OTP challenge is no longer active",
        "OTP has expired",
        "OTP verification locked due to too many failed attempts",
    }
    if message in allowed_exact:
        return message
    if any(message.startswith(prefix) for prefix in allowed_prefixes):
        return message
    return fallback


@router.post("/send", responses={400: {"description": "OTP send failed"}, 429: {"description": "Too many OTP requests"}})
async def send_otp(
    payload: OtpSendRequest,
    otp_service: Annotated[OtpService, Depends(get_otp_service)],
) -> OtpSendResponse:
    try:
        item = otp_service.send_otp(
            channel=payload.channel,
            target=payload.target,
            purpose=payload.purpose,
        )
    except OtpError as exc:
        raise HTTPException(status_code=429, detail=_public_otp_error(exc, "Unable to send OTP.")) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=_public_otp_error(exc, "Unable to send OTP.")) from exc
    return OtpSendResponse(**item)


@router.post("/verify", responses={400: {"description": "OTP verification failed"}})
async def verify_otp(
    payload: OtpVerifyRequest,
    otp_service: Annotated[OtpService, Depends(get_otp_service)],
) -> OtpVerifyResponse:
    try:
        item = otp_service.verify_otp(
            challenge_id=payload.challenge_id,
            otp_code=payload.otp_code,
        )
    except OtpError as exc:
        raise HTTPException(status_code=400, detail=_public_otp_error(exc, "Unable to verify OTP.")) from exc
    return OtpVerifyResponse(**item)
