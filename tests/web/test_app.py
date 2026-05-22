from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from androidharness.web.app import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "config.yaml"))


def test_create_app_returns_a_fastapi_app(tmp_path: Path):
    app = create_app(tmp_path / "config.yaml")
    assert app.title.startswith("AndroidHarness")


def test_index_renders_sidebar_with_all_panel_links(tmp_path: Path):
    resp = _client(tmp_path).get("/")
    assert resp.status_code == 200
    body = resp.text
    for panel in (
        "Providers",
        "Models",
        "Throttler",
        "Policy",
        "Devices",
        "Logging",
        "General",
    ):
        assert panel in body, f"sidebar missing link for {panel!r}"


def test_index_includes_htmx_script(tmp_path: Path):
    resp = _client(tmp_path).get("/")
    assert "htmx" in resp.text.lower()


def test_static_styles_css_is_served(tmp_path: Path):
    resp = _client(tmp_path).get("/static/styles.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_get_panel_unknown_name_returns_404(tmp_path: Path):
    resp = _client(tmp_path).get("/panel/bogus")
    assert resp.status_code == 404


def test_patch_config_unknown_section_returns_404(tmp_path: Path):
    resp = _client(tmp_path).patch("/config/bogus", data={"x": "y"})
    assert resp.status_code == 404
