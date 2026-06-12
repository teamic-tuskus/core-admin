"""API route tests for product CRUD endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes.products import router as products_router
from app.core.auth import require_products_access
from app.services.container import get_catalog_service


class _FakeCatalogService:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.items: dict[str, dict[str, object]] = {
            "prd_001": {
                "id": "prd_001",
                "code": "CORE-GROWTH",
                "name": "Core Growth",
                "description": "Growth plan",
                "modules": ["execution", "store"],
                "base_max_users": 25,
                "pricing": [{"tenure_months": 12, "amount_paise": 120000}],
                "created_at": now,
            }
        }

    def create_product(self, payload: dict) -> dict:
        if payload["code"].strip().upper() == "DUPLICATE":
            raise ValueError("Product code already exists")

        now = datetime.now(UTC)
        item = {
            "id": "prd_002",
            "code": payload["code"].strip().upper(),
            "name": payload["name"],
            "description": payload.get("description"),
            "modules": payload["modules"],
            "base_max_users": payload["base_max_users"],
            "pricing": payload["pricing"],
            "created_at": now,
        }
        self.items[item["id"]] = item
        return item

    def list_products(self) -> list[dict]:
        return list(self.items.values())

    def update_product(self, product_id: str, payload: dict) -> dict:
        current = self.items.get(product_id)
        if current is None:
            raise ValueError("Product not found")

        if payload.get("code", "").strip().upper() == "DUPLICATE":
            raise ValueError("Product code already exists")

        next_item = {
            **current,
            **payload,
        }
        if "code" in next_item:
            next_item["code"] = str(next_item["code"]).strip().upper()
        self.items[product_id] = next_item
        return next_item

    def delete_product(self, product_id: str) -> bool:
        if product_id not in self.items:
            raise ValueError("Product not found")
        self.items.pop(product_id)
        return True


def _build_client(service: _FakeCatalogService | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(products_router, prefix="/api/v1")

    fake_service = service or _FakeCatalogService()
    app.dependency_overrides[get_catalog_service] = lambda: fake_service
    app.dependency_overrides[require_products_access] = lambda: object()

    return TestClient(app)


def test_create_product_returns_product() -> None:
    client = _build_client()

    response = client.post(
        "/api/v1/products",
        json={
            "code": "core-scale",
            "name": "Core Scale",
            "description": "Scale plan",
            "modules": ["execution", "store", "accounts"],
            "base_max_users": 100,
            "pricing": [{"tenure_months": 12, "amount_paise": 240000}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "prd_002"
    assert payload["code"] == "CORE-SCALE"


def test_list_products_returns_rows() -> None:
    client = _build_client()

    response = client.get("/api/v1/products")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == "prd_001"


def test_update_product_returns_updated_product() -> None:
    client = _build_client()

    response = client.patch(
        "/api/v1/products/prd_001",
        json={
            "name": "Core Growth Plus",
            "base_max_users": 50,
            "modules": ["execution", "store", "survey"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Core Growth Plus"
    assert payload["base_max_users"] == 50


def test_update_product_rejects_empty_payload() -> None:
    client = _build_client()

    response = client.patch("/api/v1/products/prd_001", json={})

    assert response.status_code == 400
    assert response.json() == {"detail": "At least one field is required"}


def test_update_product_maps_not_found_to_404() -> None:
    client = _build_client()

    response = client.patch("/api/v1/products/prd_missing", json={"name": "Missing"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Product not found"}


def test_delete_product_returns_deleted_state() -> None:
    client = _build_client()

    response = client.delete("/api/v1/products/prd_001")

    assert response.status_code == 200
    assert response.json() == {"id": "prd_001", "deleted": True}


def test_delete_product_maps_not_found_to_404() -> None:
    client = _build_client()

    response = client.delete("/api/v1/products/prd_missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Product not found"}
