"""Public sales routes consumed by CoreSalesWeb."""

from __future__ import annotations

import html
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette import status

from app.schemas.checkout import CheckoutConfirmRequest, CheckoutIntentResponse, SubscriptionResponse
from app.schemas.sales import (
    PublicSalesCheckoutConfigResponse,
    PublicSalesOnboardingResumeResponse,
    PublicSalesProductResponse,
    SalesCheckoutIntentRequest,
    SalesContactRequest,
    SalesContactResponse,
)
from app.core.secret_manager import SecretAccessError, get_secret
from app.core.settings import get_settings
from app.services.catalog_service import CatalogService
from app.services.checkout_service import CheckoutService
from app.services.container import get_catalog_service, get_checkout_service, get_rate_limiter
from app.services.email_sender import SmtpEmailSender
from app.services.rate_limiter import RateLimiterService

router = APIRouter(prefix="/sales", tags=["sales"])
logger = logging.getLogger(__name__)
CHECKOUT_UNAVAILABLE_MESSAGE = "Checkout is temporarily unavailable."


def _normalize_series_order(value: object) -> int:
    try:
        return max(int(value or 100), 1)
    except (TypeError, ValueError):
        return 100


def _client_subject(request: Request) -> str:
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
    subject = _client_subject(request)
    try:
        decision = rate_limiter.check(
            route_key=route_key,
            subject=subject,
            limit=limit,
            window_seconds=window_seconds,
        )
    except Exception as exc:  # pragma: no cover - defensive fallback for rate-limit infra issues
        logger.exception(
            "Rate limiter check failed",
            extra={
                "route": route_key,
                "client_subject": subject,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=CHECKOUT_UNAVAILABLE_MESSAGE,
        ) from exc

    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again shortly.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


def _public_sales_error(exc: ValueError, fallback: str) -> str:
    message = str(exc).strip()
    if not message:
        return fallback
    allowed_exact = {
        "Product not found",
        "Requested tenure is not available for this product",
        "Final amount must be greater than zero",
        "Test payment bypass is not enabled",
        "Invalid coupon code",
        "Coupon is not active",
        "Coupon is not active yet",
        "Coupon has expired",
        "Coupon not applicable for this product",
        "Coupon not applicable for this tenant",
        "Coupon redemption limit reached",
        "Subscription not found",
        "Order ID mismatch",
        "Subscription ID mismatch",
        "Invalid Razorpay signature",
        "Unable to create recurring subscription",
    }
    if message in allowed_exact:
        return message
    return fallback


def _sanitize_text(value: str, max_len: int) -> str:
    return " ".join(str(value).split())[:max_len]


@router.get("/products")
async def list_sales_products(
    request: Request,
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    rate_limiter: Annotated[RateLimiterService, Depends(get_rate_limiter)],
) -> list[PublicSalesProductResponse]:
    """Public product catalog endpoint with a restricted response shape."""
    _enforce_limit(
        request=request,
        rate_limiter=rate_limiter,
        route_key="sales_products",
        limit=120,
        window_seconds=60,
    )
    products = catalog_service.list_products()
    return [
        PublicSalesProductResponse(
            id=item["id"],
            code=item["code"],
            name=item["name"],
            description=item.get("description"),
            features=item.get("features"),
            modules=list(item.get("modules") or []),
            base_max_users=int(item["base_max_users"]),
            base_storage_gb=float(item.get("base_storage_gb") or 5.0),
            pricing=list(item.get("pricing") or []),
            billing_cycles=item.get("billing_cycles"),
            home_view=item.get("home_view"),
            checkout_view=item.get("checkout_view"),
            is_most_popular=bool(item.get("is_most_popular", False)),
            is_live=bool(item.get("is_live", True)),
            series_order=_normalize_series_order(item.get("series_order")),
        )
        for item in products
    ]


@router.get(
    "/checkout/config",
    responses={503: {"description": "Checkout configuration unavailable"}},
)
async def get_sales_checkout_config(
    request: Request,
    rate_limiter: Annotated[RateLimiterService, Depends(get_rate_limiter)],
) -> PublicSalesCheckoutConfigResponse:
    """Return public checkout configuration without exposing internal secret details."""
    _enforce_limit(
        request=request,
        rate_limiter=rate_limiter,
        route_key="sales_checkout_config",
        limit=60,
        window_seconds=60,
    )
    try:
        settings = get_settings()
        test_payment_bypass_enabled = settings.environment != "production" and settings.checkout_test_payment_bypass_enabled
        razorpay_key_id = get_secret("razorpay-key-id").strip() if not test_payment_bypass_enabled else ""
    except SecretAccessError as exc:
        if not (get_settings().environment != "production" and get_settings().checkout_test_payment_bypass_enabled):
            raise HTTPException(status_code=503, detail=CHECKOUT_UNAVAILABLE_MESSAGE) from exc
        razorpay_key_id = ""
        test_payment_bypass_enabled = True

    if not razorpay_key_id and not test_payment_bypass_enabled:
        raise HTTPException(status_code=503, detail=CHECKOUT_UNAVAILABLE_MESSAGE)

    return PublicSalesCheckoutConfigResponse(
        razorpay_key_id=razorpay_key_id,
        test_payment_bypass_enabled=test_payment_bypass_enabled,
    )


@router.post(
    "/checkout/intent",
    responses={
        400: {"description": "Checkout intent failed"},
        503: {"description": "Checkout service temporarily unavailable"},
    },
)
async def create_sales_checkout_intent(
    request: Request,
    payload: SalesCheckoutIntentRequest,
    checkout_service: Annotated[CheckoutService, Depends(get_checkout_service)],
    rate_limiter: Annotated[RateLimiterService, Depends(get_rate_limiter)],
) -> CheckoutIntentResponse:
    """Create checkout intent from the public sales surface with backend-owned tenant derivation."""
    _enforce_limit(
        request=request,
        rate_limiter=rate_limiter,
        route_key="sales_checkout_intent",
        limit=20,
        window_seconds=300,
    )
    try:
        item = checkout_service.create_public_checkout_intent(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_sales_error(exc, "Unable to create checkout intent.")) from exc
    except Exception as exc:  # pragma: no cover - defensive fallback for third-party/runtime faults
        logger.exception(
            "Unexpected checkout intent failure",
            extra={
                "route": "sales_checkout_intent",
                "client_subject": _client_subject(request),
            },
        )
        raise HTTPException(
            status_code=503,
            detail=CHECKOUT_UNAVAILABLE_MESSAGE,
        ) from exc
    return CheckoutIntentResponse(**item)


@router.get(
    "/onboarding/resume",
    responses={400: {"description": "Onboarding resume link is invalid or expired"}},
)
async def resolve_sales_onboarding_resume(
    request: Request,
    token: Annotated[str, Query(min_length=20, max_length=4096)],
    checkout_service: Annotated[CheckoutService, Depends(get_checkout_service)],
    rate_limiter: Annotated[RateLimiterService, Depends(get_rate_limiter)],
) -> PublicSalesOnboardingResumeResponse:
    """Resolve a signed onboarding resume token to backend-authoritative subscription context."""
    _enforce_limit(
        request=request,
        rate_limiter=rate_limiter,
        route_key="sales_onboarding_resume",
        limit=30,
        window_seconds=300,
    )
    try:
        item = checkout_service.resolve_onboarding_resume_token(token=token)
    except ValueError as exc:
        message = _public_sales_error(exc, "Unable to resume onboarding.")
        if message not in {
            "Subscription not found",
            "Invalid or expired onboarding link",
            "Subscription must be active before onboarding",
            "Verified payment is required before onboarding",
        }:
            message = "Unable to resume onboarding."
        raise HTTPException(status_code=400, detail=message) from exc
    return PublicSalesOnboardingResumeResponse(**item)


@router.post("/checkout/confirm", responses={400: {"description": "Checkout confirmation failed"}})
async def confirm_sales_checkout(
    request: Request,
    payload: CheckoutConfirmRequest,
    checkout_service: Annotated[CheckoutService, Depends(get_checkout_service)],
    rate_limiter: Annotated[RateLimiterService, Depends(get_rate_limiter)],
) -> SubscriptionResponse:
    """Confirm sales checkout signature with backend validation only."""
    _enforce_limit(
        request=request,
        rate_limiter=rate_limiter,
        route_key="sales_checkout_confirm",
        limit=30,
        window_seconds=300,
    )
    try:
        item = checkout_service.confirm_checkout(payload.model_dump())
    except ValueError as exc:
        detail = _public_sales_error(exc, "Unable to confirm checkout.")
        logger.warning(
            "Sales checkout confirm rejected: %s",
            detail,
            extra={
                "route": "sales_checkout_confirm",
                "client_subject": _client_subject(request),
                "subscription_id": payload.subscription_id,
                "has_order_id": bool(payload.razorpay_order_id),
                "has_gateway_subscription_id": bool(payload.razorpay_subscription_id),
                "failure_reason": str(exc),
            },
        )
        raise HTTPException(status_code=400, detail=detail) from exc
    return SubscriptionResponse(**item)


@router.post(
    "/contact",
    responses={
        429: {"description": "Too many requests"},
        503: {"description": "Contact service temporarily unavailable"},
    },
)
async def submit_sales_contact(
    request: Request,
    payload: SalesContactRequest,
    rate_limiter: Annotated[RateLimiterService, Depends(get_rate_limiter)],
) -> SalesContactResponse:
    """Accept enterprise/contact submissions and relay to support mailbox."""
    _enforce_limit(
        request=request,
        rate_limiter=rate_limiter,
        route_key="sales_contact",
        limit=8,
        window_seconds=300,
    )

    email_sender = SmtpEmailSender()
    if not email_sender.enabled:
        raise HTTPException(status_code=503, detail="Contact service is temporarily unavailable.")

    clean_first_name = _sanitize_text(payload.first_name, 80)
    clean_last_name = _sanitize_text(payload.last_name, 80)
    clean_phone = _sanitize_text(payload.phone, 32)
    clean_message = str(payload.message).strip()[:2000]

    safe_first_name = html.escape(clean_first_name)
    safe_last_name = html.escape(clean_last_name)
    safe_email = html.escape(str(payload.email))
    safe_phone = html.escape(clean_phone)
    safe_message = html.escape(clean_message).replace("\n", "<br>")

    subject = f"Enterprise inquiry: {clean_first_name} {clean_last_name}".strip()
    body_text = (
        "New enterprise/contact inquiry from Core sales website\n\n"
        f"First name: {clean_first_name}\n"
        f"Last name: {clean_last_name}\n"
        f"Email: {payload.email}\n"
        f"Phone: {clean_phone}\n\n"
        "Message:\n"
        f"{clean_message}\n"
    )
    body_html = (
        "<h2>New enterprise/contact inquiry from Core sales website</h2>"
        f"<p><strong>First name:</strong> {safe_first_name}</p>"
        f"<p><strong>Last name:</strong> {safe_last_name}</p>"
        f"<p><strong>Email:</strong> {safe_email}</p>"
        f"<p><strong>Phone:</strong> {safe_phone}</p>"
        f"<p><strong>Message:</strong><br>{safe_message}</p>"
    )

    try:
        email_sender.send_email(
            to_email="support@tuskus.com",
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
    except Exception as exc:  # pragma: no cover - defensive runtime fallback
        logger.exception(
            "Sales contact email dispatch failed",
            extra={"route": "sales_contact", "client_subject": _client_subject(request)},
        )
        raise HTTPException(status_code=503, detail="Contact service is temporarily unavailable.") from exc

    return SalesContactResponse()
