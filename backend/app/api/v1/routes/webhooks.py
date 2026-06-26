"""Stripe and Firebase webhook handlers."""

import hashlib
import hmac
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
import structlog

from app.core.secret_manager import get_secret, SecretAccessError
from app.core.settings import get_settings

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = structlog.get_logger(__name__)


@router.post("/stripe", responses={400: {"description": "Invalid Stripe webhook"}})
async def stripe_webhook(
    request: Request,
    stripe_signature: Annotated[str, Header(alias="Stripe-Signature")] = "",
) -> dict[str, str]:
    """
    Accept and verify Stripe webhook events.
    
    Stripe sends X-Stripe-Signature header with format:
    t=<timestamp>,v1=<signature>
    
    Signature is computed as HMAC-SHA256(concatenated_payload, webhook_secret)
    """
    if not stripe_signature:
        logger.warning("stripe_webhook_missing_signature")
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
    
    try:
        raw_body = await request.body()
        stripe_secret = get_secret("stripe-webhook-secret")
    except SecretAccessError as exc:
        logger.error("stripe_webhook_secret_access_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Webhook secret unavailable") from exc
    
    # Parse signature header: "t=<timestamp>,v1=<signature>,v0=..."
    signed_content = None
    signature = None
    
    for pair in stripe_signature.split(","):
        key, value = pair.split("=", 1)
        if key == "t":
            signed_content = value
        elif key == "v1":
            signature = value
    
    if not signed_content or not signature:
        logger.warning("stripe_webhook_invalid_signature_format", raw_signature=stripe_signature)
        raise HTTPException(status_code=400, detail="Invalid Stripe-Signature format")
    
    # Compute HMAC-SHA256(timestamp.payload, secret)
    expected_signature = hmac.new(
        stripe_secret.encode(),
        f"{signed_content}.{raw_body.decode()}".encode(),
        hashlib.sha256,
    ).hexdigest()
    
    # Constant-time comparison
    if not hmac.compare_digest(signature, expected_signature):
        logger.warning("stripe_webhook_invalid_signature", provided=signature[:8], expected=expected_signature[:8])
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")
    
    try:
        payload = json.loads(raw_body)
        event_type = payload.get("type", "unknown")
        event_id = payload.get("id", "unknown")
        logger.info("stripe_webhook_received", event_type=event_type, event_id=event_id)
        
        # TODO: Process Stripe webhook events (e.g., payment_intent.succeeded, customer.subscription.updated)
        # For now, just acknowledge receipt
        
    except json.JSONDecodeError as exc:
        logger.warning("stripe_webhook_invalid_json", error=str(exc))
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    
    return {"status": "received"}


@router.post("/firebase", responses={400: {"description": "Invalid Firebase webhook"}})
async def firebase_webhook(
    request: Request,
    authorization: Annotated[str, Header()] = "",
) -> dict[str, str]:
    """
    Accept and verify Firebase (Google Cloud) webhook events.
    
    Firebase webhooks use OAuth2 Bearer token verification.
    The Authorization header contains "Bearer <id_token>"
    Verify the token against Google's public keys.
    
    For now, we accept authenticated requests (token verification 
    should be done via middleware or external service).
    """
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("firebase_webhook_missing_auth")
        raise HTTPException(status_code=400, detail="Missing or invalid Authorization header")
    
    try:
        raw_body = await request.body()
        payload = json.loads(raw_body)
        event_type = payload.get("type", "unknown")
        event_id = payload.get("id", "unknown")
        logger.info("firebase_webhook_received", event_type=event_type, event_id=event_id)
        
        # TODO: Verify JWT token against Google's public keys
        # For now, just acknowledge receipt if Authorization header is present
        # In production, use google.auth.transport.requests and google.oauth2.id_token
        
        # TODO: Process Firebase webhook events (e.g., auth.user.created, auth.user.deleted)
        
    except json.JSONDecodeError as exc:
        logger.warning("firebase_webhook_invalid_json", error=str(exc))
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    
    return {"status": "received"}
