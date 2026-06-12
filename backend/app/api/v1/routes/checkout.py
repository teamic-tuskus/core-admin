"""Checkout and webhook routes."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.schemas.checkout import (
    CheckoutConfirmRequest,
    CheckoutIntentRequest,
    CheckoutIntentResponse,
    PostPaymentTaskRequest,
    SubscriptionResponse,
)
from app.core.secret_manager import get_secret
from app.core.settings import get_settings
from app.services.checkout_service import CheckoutService
from app.services.container import get_checkout_service

router = APIRouter(prefix="/checkout", tags=["checkout"])


def _public_checkout_error(exc: ValueError, fallback: str) -> str:
    message = str(exc).strip()
    if not message:
        return fallback
    allowed_exact = {
        "Product not found",
        "Requested tenure is not available for this product",
        "Final amount must be greater than zero",
        "Subscription not found",
        "Order ID mismatch",
        "Subscription ID mismatch",
        "Invalid Razorpay signature",
        "Coupon redemption limit reached",
        "Coupon is not active",
        "Unable to create recurring subscription",
    }
    if message in allowed_exact:
        return message
    return fallback


@router.post("/intent", responses={400: {"description": "Checkout intent failed"}})
async def create_checkout_intent(
    payload: CheckoutIntentRequest,
    checkout_service: Annotated[CheckoutService, Depends(get_checkout_service)],
) -> CheckoutIntentResponse:
    """Create idempotent checkout intent and Razorpay order."""
    try:
        item = checkout_service.create_checkout_intent(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_checkout_error(exc, "Unable to create checkout intent.")) from exc
    return CheckoutIntentResponse(**item)


@router.post("/confirm", responses={400: {"description": "Checkout confirmation failed"}})
async def confirm_checkout(
    payload: CheckoutConfirmRequest,
    checkout_service: Annotated[CheckoutService, Depends(get_checkout_service)],
) -> SubscriptionResponse:
    """Confirm Razorpay callback signature and activate subscription."""
    try:
        item = checkout_service.confirm_checkout(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_checkout_error(exc, "Unable to confirm checkout.")) from exc
    return SubscriptionResponse(**item)


@router.post("/webhook", responses={400: {"description": "Invalid webhook request"}})
async def razorpay_webhook(
    request: Request,
    checkout_service: Annotated[CheckoutService, Depends(get_checkout_service)],
    x_razorpay_signature: Annotated[str, Header(alias="X-Razorpay-Signature")] = "",
    x_razorpay_event_id: Annotated[str, Header(alias="X-Razorpay-Event-Id")] = "",
) -> dict[str, str]:
    """Validate and deduplicate Razorpay webhooks."""
    if not x_razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing webhook signature")
    if not x_razorpay_event_id:
        raise HTTPException(status_code=400, detail="Missing webhook event id")

    raw_body = await request.body()
    accepted = checkout_service.handle_webhook(
        event_id=x_razorpay_event_id,
        raw_body=raw_body,
        signature=x_razorpay_signature,
    )
    if not accepted:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    return {"status": "accepted"}


@router.post(
    "/internal/post-payment-process",
    include_in_schema=False,
    responses={401: {"description": "Unauthorized task request"}},
)
async def process_post_payment_task(
    payload: PostPaymentTaskRequest,
    checkout_service: Annotated[CheckoutService, Depends(get_checkout_service)],
    x_coreadmin_task_token: Annotated[str, Header(alias="X-CoreAdmin-Task-Token")] = "",
) -> dict[str, str]:
    """Internal endpoint used by Cloud Tasks for durable post-payment processing."""
    expected = get_secret(get_settings().post_payment_tasks_token_secret_id).strip()
    received = str(x_coreadmin_task_token or "").strip()
    if not expected or not received or not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=401, detail="Unauthorized task request")

    checkout_service.process_post_payment_tasks(subscription_id=payload.subscription_id)
    return {"status": "processed"}
