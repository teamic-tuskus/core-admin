"""Product management routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthenticatedPrincipal, require_products_access
from app.schemas.product import (
    ProductCreateRequest,
    ProductDeleteResponse,
    ProductResponse,
    ProductUpdateRequest,
)
from app.services.catalog_service import CatalogService
from app.services.container import get_catalog_service

router = APIRouter(prefix="/products", tags=["products"])
PRODUCT_NOT_FOUND = "Product not found"


def _public_product_error(exc: ValueError, fallback: str) -> str:
    message = str(exc).strip()
    if not message:
        return fallback
    allowed_exact = {
        PRODUCT_NOT_FOUND,
        "Product code already exists",
        "At least one pricing tier is required",
        "Pricing tier amount must be a positive integer",
        "Pricing tiers must have unique tenure_months",
        "Pricing tiers must be sorted by tenure_months",
    }
    if message in allowed_exact:
        return message
    return fallback


@router.post("", responses={400: {"description": "Invalid product payload"}})
async def create_product(
    payload: ProductCreateRequest,
    _: Annotated[AuthenticatedPrincipal, Depends(require_products_access)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ProductResponse:
    """Create a product definition."""
    try:
        item = catalog_service.create_product(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_public_product_error(exc, "Unable to create product.")) from exc
    return ProductResponse(**item)


@router.get("")
async def list_products(
    _: Annotated[AuthenticatedPrincipal, Depends(require_products_access)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> list[ProductResponse]:
    """List all products."""
    return [ProductResponse(**item) for item in catalog_service.list_products()]


@router.patch(
    "/{product_id}",
    responses={
        400: {"description": "Invalid product update payload"},
        404: {"description": "Product not found"},
    },
)
async def update_product(
    product_id: str,
    payload: ProductUpdateRequest,
    _: Annotated[AuthenticatedPrincipal, Depends(require_products_access)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ProductResponse:
    """Update product definition."""
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="At least one field is required")

    try:
        item = catalog_service.update_product(product_id, data)
    except ValueError as exc:
        detail = _public_product_error(exc, "Unable to update product.")
        status_code = 404 if detail == PRODUCT_NOT_FOUND else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return ProductResponse(**item)


@router.delete("/{product_id}", responses={404: {"description": "Product not found"}})
async def delete_product(
    product_id: str,
    _: Annotated[AuthenticatedPrincipal, Depends(require_products_access)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ProductDeleteResponse:
    """Delete product definition."""
    try:
        deleted = catalog_service.delete_product(product_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=_public_product_error(exc, PRODUCT_NOT_FOUND)) from exc
    return ProductDeleteResponse(id=product_id, deleted=deleted)
