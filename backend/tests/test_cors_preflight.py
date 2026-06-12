"""CORS preflight tests for admin access invitation routes."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.api.v1.routes.admin import router as admin_router


ALLOWED_ORIGIN = "https://core.tuskus.com"


def _build_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ALLOWED_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(admin_router, prefix="/api/v1")
    return TestClient(app)


def test_preflight_allows_admin_access_invitation_endpoint() -> None:
    client = _build_client()

    response = client.options(
        "/api/v1/admin/access/invitations",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert "POST" in (response.headers.get("access-control-allow-methods") or "")


def test_preflight_rejects_unlisted_origin() -> None:
    client = _build_client()

    response = client.options(
        "/api/v1/admin/access/invitations",
        headers={
            "Origin": "https://unauthorized.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 400
    assert response.headers.get("access-control-allow-origin") is None
