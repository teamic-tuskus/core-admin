"""Authentication policy tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.auth import get_current_principal


def _credentials(token: str):
    return SimpleNamespace(credentials=token)


def test_get_current_principal_accepts_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    decoded = {
        "uid": "user_001",
        "email": "admin@example.com",
        "firebase": {"sign_in_provider": "password"},
        "role": "admin",
    }

    class _FakeFirebaseAuth:
        @staticmethod
        def verify_id_token(token: str, check_revoked: bool = True):
            assert token == "token_google"
            assert check_revoked is True
            return decoded

    monkeypatch.setattr("app.core.auth.get_firebase_auth", lambda: _FakeFirebaseAuth())

    principal = get_current_principal(_credentials("token_google"))

    assert principal.uid == "user_001"
    assert principal.email == "admin@example.com"
