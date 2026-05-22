from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_providers_renders_default_entries(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/panel/providers")
    assert resp.status_code == 200
    body = resp.text
    for provider in ("gemini", "anthropic", "openai"):
        assert provider in body


def test_get_panel_providers_shows_set_badge_when_env_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    client, _ = _client(tmp_path)
    resp = client.get("/panel/providers")
    assert "badge-set" in resp.text


def test_get_panel_providers_shows_missing_badge_when_env_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client, _ = _client(tmp_path)
    resp = client.get("/panel/providers")
    assert "badge-missing" in resp.text


def test_patch_config_providers_updates_default_and_api_key_env(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/providers",
        data={
            "default": "anthropic",
            "use_litellm": "true",
            "provider_keys": "gemini,anthropic,openai",
            "entries.gemini.api_key_env": "GEMINI_API_KEY",
            "entries.gemini.default_model": "gemini/gemini-2.5-flash",
            "entries.anthropic.api_key_env": "MY_ANTHROPIC_KEY",
            "entries.anthropic.default_model": "anthropic/claude-haiku-4-5",
            "entries.openai.api_key_env": "OPENAI_API_KEY",
            "entries.openai.default_model": "openai/gpt-4o-mini",
        },
    )
    assert resp.status_code == 200, resp.text
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.providers.default == "anthropic"
    assert reloaded.providers.entries["anthropic"].api_key_env == "MY_ANTHROPIC_KEY"


def test_patch_config_providers_rejects_default_not_in_entries(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/providers",
        data={
            "default": "doesnt_exist",
            "use_litellm": "true",
            "provider_keys": "gemini",
            "entries.gemini.api_key_env": "GEMINI_API_KEY",
            "entries.gemini.default_model": "gemini/gemini-2.5-flash",
        },
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
    if cfg_path.exists():
        reloaded = ConfigStore(cfg_path).load()
        assert reloaded.providers.default == "gemini"
