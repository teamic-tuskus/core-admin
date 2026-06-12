"""Coupon management routes."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.core.auth import AuthenticatedPrincipal, require_coupons_access
from app.schemas.coupon import CouponCreateRequest, CouponDeleteResponse, CouponResponse
from app.services.catalog_service import CatalogService
from app.services.container import get_catalog_service

router = APIRouter(prefix="/coupons", tags=["coupons"])
COUPON_NOT_FOUND = "Coupon not found"
logger = logging.getLogger(__name__)


def _public_coupon_error(exc: ValueError, fallback: str) -> str:
    message = str(exc).strip()
    if not message:
        return fallback
    allowed_prefixes = (
        "Discount percent exceeds your limit",
        "Discount amount exceeds your limit",
    )
    allowed_exact = {
        "Coupon code already exists",
        "Coupon code is required",
        "Coupon product does not exist",
        "Coupon must define discount_percent and/or discount_amount_paise",
        COUPON_NOT_FOUND,
    }
    if message in allowed_exact:
        return message
    if any(message.startswith(prefix) for prefix in allowed_prefixes):
        return message
    return fallback


@router.post("", responses={400: {"description": "Invalid coupon payload"}, 403: {"description": "Forbidden"}})
async def create_coupon(
    payload: CouponCreateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_coupons_access)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> CouponResponse:
    """Create a coupon."""
    try:
        claims = getattr(principal, "claims", {}) if principal is not None else {}
        permissions_raw = claims.get("portal_permissions") if isinstance(claims, dict) else None
        permissions = {str(item).lower() for item in permissions_raw} if isinstance(permissions_raw, list) else set()

        is_advance_coupon = bool(
            payload.exclusive_for_tenant_id
            or payload.override_tenure_months is not None
            or payload.override_max_users is not None
            or payload.override_modules
        )
        if is_advance_coupon and "advance_coupons" not in permissions:
            raise HTTPException(status_code=403, detail="Advance coupon access required")

        max_percent_raw = claims.get("normal_coupon_max_discount_percent") if isinstance(claims, dict) else None
        max_amount_raw = claims.get("normal_coupon_max_discount_amount_paise") if isinstance(claims, dict) else None
        max_percent = int(max_percent_raw) if isinstance(max_percent_raw, int | float) else None
        max_amount = int(max_amount_raw) if isinstance(max_amount_raw, int | float) else None

        if payload.discount_percent is not None and max_percent is not None and payload.discount_percent > max_percent:
            raise ValueError(f"Discount percent exceeds your limit ({max_percent}%)")
        if payload.discount_amount_paise is not None and max_amount is not None and payload.discount_amount_paise > max_amount:
            raise ValueError(f"Discount amount exceeds your limit (INR {max_amount // 100})")

        item = catalog_service.create_coupon(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_coupon_error(exc, "Unable to create coupon.")) from exc
    return CouponResponse(**item)


@router.get("")
async def list_coupons(
    _: Annotated[AuthenticatedPrincipal, Depends(require_coupons_access)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> list[CouponResponse]:
    """List all coupons."""
    rows: list[CouponResponse] = []
    for item in catalog_service.list_coupons():
        try:
            rows.append(CouponResponse(**item))
        except ValidationError as exc:
            logger.warning(
                "Skipping malformed coupon row during list response",
                extra={"coupon_id": item.get("id")},
                exc_info=exc,
            )
            continue
    return rows


@router.post("/{coupon_id}/pause", responses={400: {"description": "Invalid coupon operation"}, 404: {"description": "Coupon not found"}})
async def pause_coupon(
    coupon_id: str,
    _: Annotated[AuthenticatedPrincipal, Depends(require_coupons_access)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> CouponResponse:
    """Pause coupon redemptions."""
    try:
        item = catalog_service.pause_coupon(coupon_id)
    except ValueError as exc:
        detail = _public_coupon_error(exc, "Unable to pause coupon.")
        status_code = 404 if detail == COUPON_NOT_FOUND else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return CouponResponse(**item)


@router.delete("/{coupon_id}", responses={400: {"description": "Invalid coupon operation"}, 404: {"description": "Coupon not found"}})
async def delete_coupon(
    coupon_id: str,
    _: Annotated[AuthenticatedPrincipal, Depends(require_coupons_access)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> CouponDeleteResponse:
    """Soft-delete a coupon."""
    try:
        deleted = catalog_service.delete_coupon(coupon_id)
    except ValueError as exc:
        detail = _public_coupon_error(exc, "Unable to delete coupon.")
        status_code = 404 if detail == COUPON_NOT_FOUND else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return CouponDeleteResponse(id=coupon_id, deleted=deleted)
