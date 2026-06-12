"""Permission contract tests for scoped portal access."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes.coupons import router as coupons_router
from app.api.v1.routes.products import router as products_router
from app.core.auth import AuthenticatedPrincipal, get_current_principal
from app.services.container import get_catalog_service


class _FakeCatalogService:
    def list_products(self) -> list[dict]:
        return [
            {
                "id": "prd_001",
                "code": "CORE-GROWTH",
                "name": "Core Growth",
                "description": "Growth plan",
                "modules": ["execution", "store"],
                "base_max_users": 25,
                "pricing": [{"tenure_months": 12, "amount_paise": 120000}],
                "created_at": datetime.now(UTC),
            }
        ]

    def list_coupons(self) -> list[dict]:
        return [
            {
                "id": "cpn_001",
                "code": "WELCOME10",
                "product_id": None,
                "discount_percent": 10,
                "discount_amount_paise": None,
                "override_tenure_months": None,
                "override_max_users": None,
                "override_modules": None,
                "exclusive_for_tenant_id": None,
                "valid_from": None,
                "valid_until": None,
                "max_redemptions": 100,
                "redemption_count": 0,
                "created_at": datetime.now(UTC),
            }
        ]


def _build_client(principal: AuthenticatedPrincipal) -> TestClient:
    app = FastAPI()
    app.include_router(products_router, prefix="/api/v1")
    app.include_router(coupons_router, prefix="/api/v1")

    app.dependency_overrides[get_catalog_service] = lambda: _FakeCatalogService()
    app.dependency_overrides[get_current_principal] = lambda: principal

    return TestClient(app)


def test_admin_coupon_only_scope_blocks_products_and_allows_coupons() -> None:
    client = _build_client(
        AuthenticatedPrincipal(
            uid="uid_admin",
            email="admin@example.com",
            claims={
                "uid": "uid_admin",
                "role": "admin",
                "roles": ["admin"],
                "portal_permissions": ["coupons", "users"],
            },
        )
    )

    products_response = client.get("/api/v1/products")
    assert products_response.status_code == 403
    assert products_response.json() == {"detail": "Insufficient permissions"}

    coupons_response = client.get("/api/v1/coupons")
    assert coupons_response.status_code == 200
    assert len(coupons_response.json()) == 1


def test_manager_product_only_scope_allows_products_and_blocks_coupons() -> None:
    client = _build_client(
        AuthenticatedPrincipal(
            uid="uid_manager",
            email="manager@example.com",
            claims={
                "uid": "uid_manager",
                "role": "manager",
                "roles": ["manager"],
                "portal_permissions": ["products"],
            },
        )
    )

    products_response = client.get("/api/v1/products")
    assert products_response.status_code == 200
    assert len(products_response.json()) == 1

    coupons_response = client.get("/api/v1/coupons")
    assert coupons_response.status_code == 403
    assert coupons_response.json() == {"detail": "Insufficient permissions"}
