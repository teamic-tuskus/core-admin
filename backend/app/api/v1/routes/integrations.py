"""Integration callback routes for third-party OAuth providers."""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/zoho/callback")
async def zoho_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> dict[str, str | bool | None]:
    """Receive Zoho OAuth redirects for CoreAdmin-owned invoicing integrations."""
    if error:
        return {
            "ok": False,
            "provider": "zoho",
            "message": "Zoho authorization failed",
            "error": error,
            "code": None,
            "state": state,
        }

    if not code:
        return {
            "ok": False,
            "provider": "zoho",
            "message": "Missing authorization code",
            "error": None,
            "code": None,
            "state": state,
        }

    return {
        "ok": True,
        "provider": "zoho",
        "message": "Zoho authorization code received",
        "error": None,
        "code": code,
        "state": state,
    }
