"""API route tests for coupon endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes.coupons import router as coupons_router
from app.core.auth import require_coupons_access
from app.services.container import get_catalog_service


class _FakeCatalogService:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.rows: list[dict[str, object]] = [
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
                "status": "active",
                "paused_at": None,
                "deleted_at": None,
                "created_at": now,
                "updated_at": now,
            }
        ]

    def create_coupon(self, payload: dict) -> dict:
        if str(payload.get("code") or "").upper() == "DUPLICATE":
            raise ValueError("Coupon code already exists")

        item = {
            "id": "cpn_002",
            "code": str(payload["code"]).upper(),
            "product_id": payload.get("product_id"),
            "discount_percent": payload.get("discount_percent"),
            "discount_amount_paise": payload.get("discount_amount_paise"),
            "override_tenure_months": payload.get("override_tenure_months"),
            "override_max_users": payload.get("override_max_users"),
            "override_modules": payload.get("override_modules"),
            "exclusive_for_tenant_id": payload.get("exclusive_for_tenant_id"),
            "valid_from": payload.get("valid_from"),
            "valid_until": payload.get("valid_until"),
            "max_redemptions": payload.get("max_redemptions"),
            "redemption_count": 0,
            "status": "active",
            "paused_at": None,
            "deleted_at": None,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        self.rows.append(item)
        return item

    def pause_coupon(self, coupon_id: str) -> dict:
        for item in self.rows:
            if item["id"] == coupon_id:
                item["status"] = "paused"
                item["paused_at"] = datetime.now(UTC)
                item["updated_at"] = datetime.now(UTC)
                return item
        raise ValueError("Coupon not found")

    def delete_coupon(self, coupon_id: str) -> bool:
        for item in self.rows:
            if item["id"] == coupon_id:
                item["status"] = "deleted"
                item["deleted_at"] = datetime.now(UTC)
                item["updated_at"] = datetime.now(UTC)
                return True
        raise ValueError("Coupon not found")

    def list_coupons(self) -> list[dict]:
        return self.rows


def _build_client(service: _FakeCatalogService | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(coupons_router, prefix="/api/v1")

    fake_service = service or _FakeCatalogService()
    app.dependency_overrides[get_catalog_service] = lambda: fake_service
    app.dependency_overrides[require_coupons_access] = lambda: type(
        "Principal",
        (),
        {"claims": {}, "uid": "uid_test", "email": "test@example.com"},
    )()

    return TestClient(app)


def _build_client_with_permissions(permissions: list[str]) -> TestClient:
    app = FastAPI()
    app.include_router(coupons_router, prefix="/api/v1")

    app.dependency_overrides[get_catalog_service] = lambda: _FakeCatalogService()
    app.dependency_overrides[require_coupons_access] = lambda: type(
        "Principal",
        (),
        {
            "claims": {"portal_permissions": permissions},
            "uid": "uid_test",
            "email": "test@example.com",
        },
    )()
    return TestClient(app)


def test_create_coupon_returns_coupon() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/coupons",
        json={
            "code": "newyear50",
            "product_id": None,
            "discount_percent": 50,
            "max_redemptions": 500,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "cpn_002"
    assert payload["code"] == "NEWYEAR50"
    assert payload["discount_percent"] == 50


def test_create_coupon_maps_service_error_to_400() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/coupons",
        json={
            "code": "duplicate",
            "discount_percent": 10,
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Coupon code already exists"}


def test_list_coupons_returns_rows() -> None:
    client = _build_client()

    response = client.get("/api/v1/coupons")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == "cpn_001"


def test_list_coupons_skips_malformed_rows() -> None:
    service = _FakeCatalogService()
    service.rows.append(
        {
            "id": "cpn_bad",
            "code": "BROKEN",
            "product_id": None,
            "discount_percent": 5,
            "discount_amount_paise": None,
            "override_tenure_months": None,
            "override_max_users": None,
            "override_modules": None,
            "exclusive_for_tenant_id": None,
            "valid_from": None,
            "valid_until": None,
            "max_redemptions": 10,
            "redemption_count": 0,
            "status": "active",
            "paused_at": None,
            "deleted_at": None,
            "created_at": "not-a-datetime",
            "updated_at": None,
        }
    )
    client = _build_client(service)

    response = client.get("/api/v1/coupons")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == "cpn_001"


def test_create_advance_coupon_requires_advance_permission() -> None:
    client = _build_client_with_permissions(["coupons"])

    response = client.post(
        "/api/v1/coupons",
        json={
            "code": "ADV-LOCKED",
            "exclusive_for_tenant_id": "ten_123",
            "override_tenure_months": 1,
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Advance coupon access required"}


def test_pause_coupon_returns_updated_row() -> None:
    client = _build_client()

    response = client.post("/api/v1/coupons/cpn_001/pause")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "cpn_001"
    assert payload["status"] == "paused"


def test_delete_coupon_returns_deleted_true() -> None:
    client = _build_client()

    response = client.delete("/api/v1/coupons/cpn_001")

    assert response.status_code == 200
    assert response.json() == {"id": "cpn_001", "deleted": True}
