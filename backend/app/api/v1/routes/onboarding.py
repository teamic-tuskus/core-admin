"""Sales onboarding routes used by CoreSalesWeb checkout flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import secrets
from typing import Annotated
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette import status

from app.core.firebase import get_firestore_client
from app.core.secret_manager import get_secret
from app.core.settings import get_settings
from app.schemas.onboarding import (
    GstVerifyRequest,
    GstVerifyResponse,
    OnboardingCompleteRequest,
    OnboardingCompleteResponse,
    OnboardingCredentialsRequest,
    OnboardingCredentialsResponse,
    OnboardingOtpSendRequest,
    OnboardingOtpSendResponse,
    OnboardingOtpVerifyRequest,
    OnboardingOtpVerifyResponse,
)
from app.services.container import get_onboarding_service, get_rate_limiter
from app.services.onboarding_service import OnboardingService
from app.services.rate_limiter import RateLimiterService

router = APIRouter(prefix="/onboarding", tags=["onboarding"])
INVALID_SETUP_TOKEN_MESSAGE = "Invalid or expired account setup token."
ACCOUNT_PROVISIONING_UNAVAILABLE_MESSAGE = "Account provisioning is temporarily unavailable."


def _client_subject(request: Request) -> str:
    """Use trusted edge IP first and avoid trusting user-controlled forwarding chains."""
    cf_ip = request.headers.get("cf-connecting-ip", "").strip()
    if cf_ip:
        return cf_ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _enforce_limit(
    *,
    request: Request,
    rate_limiter: RateLimiterService,
    route_key: str,
    limit: int,
    window_seconds: int,
) -> None:
    decision = rate_limiter.check(
        route_key=route_key,
        subject=_client_subject(request),
        limit=limit,
        window_seconds=window_seconds,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again shortly.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


def _public_onboarding_error(exc: ValueError, fallback: str) -> str:
    message = str(exc).strip()
    if not message:
        return fallback
    allowed_prefixes = (
        "Please wait ",
        "Too many OTP requests",
        "Invalid OTP",
    )
    allowed_exact = {
        "Invalid GSTIN",
        "GST verification service is temporarily unavailable. Please try again shortly.",
        "Subscription not found",
        "Business email is required for OTP delivery",
        "Phone is required for OTP delivery",
        "OTP delivery is temporarily unavailable. Please try again shortly.",
        "Phone OTP is required",
        "OTP session not found",
        "OTP session expired",
        "OTP verification locked due to too many failed attempts",
        "OTP verification is required before onboarding completion",
        "Subscription must be active before onboarding completion",
        "Verified payment is required before onboarding completion",
        "Subscription limits sync failed. Please retry onboarding completion.",
    }
    if message in allowed_exact:
        return message
    if any(message.startswith(prefix) for prefix in allowed_prefixes):
        return message
    return fallback


def _normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def _issue_credentials_setup_token() -> tuple[str, str, datetime]:
    raw_token = secrets.token_urlsafe(32)
    token_hash = sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=20)
    return raw_token, token_hash, expires_at


def _validate_credentials_setup_token(*, tenant_id: str, email: str, setup_token: str) -> None:
    db = get_firestore_client()
    tenant = db.collection("tenants").document(tenant_id).get()
    if not tenant.exists:
        raise HTTPException(status_code=400, detail=INVALID_SETUP_TOKEN_MESSAGE)

    data = tenant.to_dict() or {}
    expected_email = _normalize_email(str(data.get("credentials_setup_email") or ""))
    expected_hash = str(data.get("credentials_setup_token_hash") or "")
    expires_at = data.get("credentials_setup_token_expires_at")
    used_at = data.get("credentials_setup_token_used_at")

    if not expected_email or expected_email != _normalize_email(email):
        raise HTTPException(status_code=400, detail=INVALID_SETUP_TOKEN_MESSAGE)
    if not expected_hash:
        raise HTTPException(status_code=400, detail=INVALID_SETUP_TOKEN_MESSAGE)
    if used_at is not None:
        raise HTTPException(status_code=400, detail=INVALID_SETUP_TOKEN_MESSAGE)
    if not isinstance(expires_at, datetime) or datetime.now(tz=timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail=INVALID_SETUP_TOKEN_MESSAGE)

    provided_hash = sha256(setup_token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(expected_hash, provided_hash):
        raise HTTPException(status_code=400, detail=INVALID_SETUP_TOKEN_MESSAGE)


def _mark_credentials_setup_token_used(*, tenant_id: str) -> None:
    db = get_firestore_client()
    now = datetime.now(tz=timezone.utc)
    db.collection("tenants").document(tenant_id).set(
        {
            "credentials_setup_token_used_at": now,
            "updated_at": now,
        },
        merge=True,
    )


@router.post("/gst/verify", responses={400: {"description": "GST verification failed"}})
async def verify_gst(
    request: Request,
    payload: GstVerifyRequest,
    onboarding_service: Annotated[OnboardingService, Depends(get_onboarding_service)],
    rate_limiter: Annotated[RateLimiterService, Depends(get_rate_limiter)],
) -> GstVerifyResponse:
    _enforce_limit(
        request=request,
        rate_limiter=rate_limiter,
        route_key="onboarding_gst_verify",
        limit=40,
        window_seconds=300,
    )
    try:
        item = onboarding_service.verify_gst(
            subscription_id=payload.subscription_id,
            gstin=payload.gstin,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_public_onboarding_error(exc, "Unable to verify GST details."),
        ) from exc
    return GstVerifyResponse(**item)


@router.post(
    "/otp/send",
    responses={400: {"description": "OTP send failed"}, 429: {"description": "Too many OTP requests"}},
    response_model_exclude_none=True,
)
async def send_otp(
    request: Request,
    payload: OnboardingOtpSendRequest,
    onboarding_service: Annotated[OnboardingService, Depends(get_onboarding_service)],
    rate_limiter: Annotated[RateLimiterService, Depends(get_rate_limiter)],
) -> OnboardingOtpSendResponse:
    _enforce_limit(
        request=request,
        rate_limiter=rate_limiter,
        route_key="onboarding_otp_send",
        limit=10,
        window_seconds=300,
    )
    try:
        item = onboarding_service.send_dual_otp(
            subscription_id=payload.subscription_id,
            gstin=payload.gstin,
            transaction_id=payload.transaction_id,
            otp_channel=payload.otp_channel,
        )
    except ValueError as exc:
        message = _public_onboarding_error(exc, "Unable to send OTP.")
        status_code = 429 if message.lower().startswith("please wait") or "too many" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return OnboardingOtpSendResponse(**item)


@router.post("/otp/verify", responses={400: {"description": "OTP verification failed"}})
async def verify_otp(
    request: Request,
    payload: OnboardingOtpVerifyRequest,
    onboarding_service: Annotated[OnboardingService, Depends(get_onboarding_service)],
    rate_limiter: Annotated[RateLimiterService, Depends(get_rate_limiter)],
) -> OnboardingOtpVerifyResponse:
    _enforce_limit(
        request=request,
        rate_limiter=rate_limiter,
        route_key="onboarding_otp_verify",
        limit=15,
        window_seconds=300,
    )
    try:
        item = onboarding_service.verify_dual_otp(
            otp_session_id=payload.otp_session_id,
            otp_code=payload.otp_code,
            email_otp=payload.email_otp,
            phone_otp=payload.phone_otp,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_public_onboarding_error(exc, "Unable to verify OTP."),
        ) from exc
    return OnboardingOtpVerifyResponse(**item)


@router.post("/complete", responses={400: {"description": "Onboarding completion failed"}})
async def complete_onboarding(
    request: Request,
    payload: OnboardingCompleteRequest,
    onboarding_service: Annotated[OnboardingService, Depends(get_onboarding_service)],
    rate_limiter: Annotated[RateLimiterService, Depends(get_rate_limiter)],
) -> OnboardingCompleteResponse:
    _enforce_limit(
        request=request,
        rate_limiter=rate_limiter,
        route_key="onboarding_complete",
        limit=10,
        window_seconds=300,
    )
    try:
        item = onboarding_service.complete_onboarding(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_public_onboarding_error(exc, "Unable to complete onboarding."),
        ) from exc

    tenant_id = str(item.get("tenant_id") or "")
    super_admin_email = _normalize_email(str(item.get("super_admin_email") or ""))
    if not tenant_id or not super_admin_email:
        raise HTTPException(status_code=400, detail="Unable to complete onboarding.")

    setup_token, setup_token_hash, setup_token_expires_at = _issue_credentials_setup_token()
    db = get_firestore_client()
    db.collection("tenants").document(tenant_id).set(
        {
            "super_admin_email": super_admin_email,
            "credentials_setup_email": super_admin_email,
            "credentials_setup_token_hash": setup_token_hash,
            "credentials_setup_token_expires_at": setup_token_expires_at,
            "credentials_setup_token_used_at": None,
            "updated_at": datetime.now(tz=timezone.utc),
        },
        merge=True,
    )

    item["super_admin_email"] = super_admin_email
    item["credentials_setup_token"] = setup_token
    item["credentials_setup_token_expires_at"] = setup_token_expires_at
    
    # Return with explicit field assignment to ensure credentials_setup_token is included
    return OnboardingCompleteResponse(
        tenant_id=item["tenant_id"],
        super_admin_email=item["super_admin_email"],
        onboarding_status=item["onboarding_status"],
        completed_at=item["completed_at"],
        credentials_setup_token=setup_token,
        credentials_setup_token_expires_at=setup_token_expires_at,
    )


@router.post(
    "/credentials",
    responses={400: {"description": "Account setup failed"}, 503: {"description": "Account provisioning unavailable"}},
)
async def setup_credentials(
    request: Request,
    payload: OnboardingCredentialsRequest,
    rate_limiter: Annotated[RateLimiterService, Depends(get_rate_limiter)],
) -> OnboardingCredentialsResponse:
    """Create or update the super admin Firebase Auth account in Core using Firebase REST API."""
    _enforce_limit(
        request=request,
        rate_limiter=rate_limiter,
        route_key="onboarding_credentials",
        limit=10,
        window_seconds=300,
    )
    settings = get_settings()
    try:
        api_key = get_secret(settings.core_firebase_api_key_secret_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=ACCOUNT_PROVISIONING_UNAVAILABLE_MESSAGE) from exc

    normalized_email = payload.email.strip().lower()
    if "@" not in normalized_email or "." not in normalized_email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Invalid email address.")

    _validate_credentials_setup_token(
        tenant_id=payload.tenant_id,
        email=normalized_email,
        setup_token=payload.setup_token,
    )

    body = json.dumps(
        {
            "email": normalized_email,
            "password": payload.password,
            "returnSecureToken": False,
        }
    ).encode("utf-8")
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        db = get_firestore_client()
        db.collection("tenants").document(payload.tenant_id).set(
            {
                "super_admin_email": normalized_email,
                "updated_at": datetime.now(tz=timezone.utc),
            },
            merge=True,
        )
        _mark_credentials_setup_token_used(tenant_id=payload.tenant_id)
        return OnboardingCredentialsResponse(email=normalized_email, account_created=True)
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(err_body).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        if "EMAIL_EXISTS" in detail:
            db = get_firestore_client()
            db.collection("tenants").document(payload.tenant_id).set(
                {
                    "super_admin_email": normalized_email,
                    "updated_at": datetime.now(tz=timezone.utc),
                },
                merge=True,
            )
            _mark_credentials_setup_token_used(tenant_id=payload.tenant_id)
            return OnboardingCredentialsResponse(email=normalized_email, account_created=False)
        if "WEAK_PASSWORD" in detail:
            raise HTTPException(
                status_code=400,
                detail="Password is too weak. Use at least 8 characters.",
            ) from exc
        if "INVALID_EMAIL" in detail:
            raise HTTPException(status_code=400, detail="Invalid email address.") from exc
        raise HTTPException(status_code=400, detail="Account setup failed. Please try again.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=ACCOUNT_PROVISIONING_UNAVAILABLE_MESSAGE) from exc
