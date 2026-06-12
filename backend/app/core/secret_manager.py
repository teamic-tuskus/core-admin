"""Secret Manager client with strict GCP-only secret access."""

from __future__ import annotations

from dataclasses import dataclass, field

from google.cloud import secretmanager


class SecretAccessError(RuntimeError):
    """Raised when a required secret cannot be accessed."""


@dataclass
class SecretManagerService:
    """Caches secrets fetched from GCP Secret Manager."""

    project_id: str
    default_version: str = "latest"
    _client: secretmanager.SecretManagerServiceClient = field(
        default_factory=secretmanager.SecretManagerServiceClient
    )
    _cache: dict[str, str] = field(default_factory=dict)

    def _secret_resource(self, secret_id: str, version: str | None = None) -> str:
        resolved_version = version or self.default_version
        return (
            f"projects/{self.project_id}/secrets/{secret_id}"
            f"/versions/{resolved_version}"
        )

    def get_secret(self, secret_id: str, version: str | None = None) -> str:
        """Fetch and cache a secret value from GCP Secret Manager."""
        cache_key = f"{secret_id}:{version or self.default_version}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        resource = self._secret_resource(secret_id=secret_id, version=version)
        try:
            response = self._client.access_secret_version(request={"name": resource})
        except Exception as exc:  # pragma: no cover - preserves provider exception context
            raise SecretAccessError(
                f"Unable to access secret '{secret_id}' from GCP Secret Manager"
            ) from exc

        value = response.payload.data.decode("utf-8")
        self._cache[cache_key] = value
        return value

    def warmup(self, secret_ids: tuple[str, ...]) -> None:
        """Preload required secrets and fail fast if any are unavailable."""
        for secret_id in secret_ids:
            self.get_secret(secret_id)


_secret_manager: SecretManagerService | None = None


def init_secret_manager(project_id: str, default_version: str = "latest") -> None:
    """Initialize singleton secret manager service."""
    global _secret_manager
    _secret_manager = SecretManagerService(
        project_id=project_id,
        default_version=default_version,
    )


def get_secret_manager() -> SecretManagerService:
    """Return initialized secret manager singleton."""
    if _secret_manager is None:
        raise RuntimeError("Secret manager has not been initialized")
    return _secret_manager


def get_secret(secret_id: str, version: str | None = None) -> str:
    """Convenience wrapper to fetch a secret from GCP Secret Manager only."""
    return get_secret_manager().get_secret(secret_id=secret_id, version=version)


def get_secret_uncached(secret_id: str, version: str | None = None) -> str:
    """Fetch a secret value directly from GCP Secret Manager, bypassing local cache."""
    manager = get_secret_manager()
    resource = manager._secret_resource(secret_id=secret_id, version=version)
    try:
        response = manager._client.access_secret_version(request={"name": resource})
    except Exception as exc:  # pragma: no cover - preserves provider exception context
        raise SecretAccessError(
            f"Unable to access secret '{secret_id}' from GCP Secret Manager"
        ) from exc
    return response.payload.data.decode("utf-8")
