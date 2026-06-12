"""Health endpoints for platform readiness checks."""

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="Liveness check")
async def health_check() -> dict[str, str]:
    """Simple liveness endpoint without exposing internal details."""
    return {"status": "ok"}
