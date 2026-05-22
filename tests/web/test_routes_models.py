from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_models_renders_existing_logical_models(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    store = ConfigStore(cfg_path)
    cfg = store.load()
    cfg.providers.logical_models = {"fast": ["gemini/gemini-2.5-flash"]}
    store.write(cfg)

    client = TestClient(create_app(cfg_path))
    resp = client.get("/panel/models")
    assert resp.status_code == 200
    assert "fast" in resp.text
    assert "gemini/gemini-2.5-flash" in resp.text


def test_patch_config_models_sets_logical_models(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    # One logical model with two entries (comma-separated in the form)
    resp = client.patch(
        "/config/models",
        data={
            "logical_names": "smart",
            "chain.smart": "anthropic/claude-haiku-4-5, openai/gpt-4o-mini",
        },
    )
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.providers.logical_models == {
        "smart": ["anthropic/claude-haiku-4-5", "openai/gpt-4o-mini"],
    }


def test_patch_config_models_rejects_non_provider_slash_model_entry(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/models",
        data={
            "logical_names": "smart",
            "chain.smart": "bare-model-id-without-provider",  # missing the `/`
        },
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
    if cfg_path.exists():
        reloaded = ConfigStore(cfg_path).load()
        assert reloaded.providers.logical_models == {}  # default


def test_patch_config_models_empty_chain_rejected(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.patch(
        "/config/models",
        data={
            "logical_names": "smart",
            "chain.smart": "",  # empty chain
        },
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
