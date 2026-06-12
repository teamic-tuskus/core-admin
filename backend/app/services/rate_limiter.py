"""Backend-owned rate limiting service for public-facing routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256


@dataclass
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class RateLimiterService:
    """Checks and records route-level request usage windows."""

    def __init__(self, *, repo) -> None:
        self.repo = repo

    @staticmethod
    def _now() -> datetime:
        return datetime.now(tz=timezone.utc)

    @staticmethod
    def _hash_subject(subject: str) -> str:
        normalized = subject.strip().lower()
        return sha256(normalized.encode("utf-8")).hexdigest()

    def check(self, *, route_key: str, subject: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = self._now()
        usage_key = f"{route_key}:{self._hash_subject(subject)}"
        allowed, retry_after = self.repo.consume(
            key=usage_key,
            limit=limit,
            window_seconds=window_seconds,
            now=now,
        )
        return RateLimitDecision(allowed=allowed, retry_after_seconds=retry_after)
