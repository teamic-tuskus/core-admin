"""Tests for backend settings behavior."""

from app.core.settings import Settings


def test_secret_ids_parse_from_csv() -> None:
    parsed = Settings.parse_secret_ids("one,two, three")
    assert parsed == ("one", "two", "three")


def test_secret_ids_parse_from_sequence() -> None:
    parsed = Settings.parse_secret_ids(["alpha", "beta", ""])
    assert parsed == ("alpha", "beta")


def test_settings_require_project_id() -> None:
    settings = Settings(gcp_project_id="demo-project")
    assert settings.gcp_project_id == "demo-project"
