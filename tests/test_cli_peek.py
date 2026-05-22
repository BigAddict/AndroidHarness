"""Tests for the `androidharness peek` subcommand — the read-only window
into what the model would see on the connected device's current screen."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from androidharness.cli import app
from androidharness.device import DeviceInfo

runner = CliRunner()

_HIERARCHY = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[40,200][520,320]" class="android.widget.Button" text="Settings" clickable="true" resource-id="com.x:id/settings_row"/>
    <node bounds="[40,400][520,520]" class="android.widget.Button" text="Wi-Fi" clickable="true"/>
  </node>
</hierarchy>
"""


@pytest.fixture
def isolated_home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ANDROIDHARNESS_CONFIG", raising=False)
    return tmp_path


@pytest.fixture
def stub_peek(monkeypatch):
    """Replace device wiring with a fake that returns canned hierarchy XML.
    Does NOT stub run_task or any LLM client — peek must not touch either."""

    class FakeUIDevice:
        serial = "STUB"
        model = "StubPixel"

        @classmethod
        def connect(cls, serial: str):
            obj = cls()
            obj.serial = serial
            return obj

        def dump_hierarchy(self) -> str:
            return _HIERARCHY

    def fake_list_devices():
        return [DeviceInfo(serial="STUB", model="StubPixel")]

    monkeypatch.setattr("androidharness.cli.list_devices", fake_list_devices)
    monkeypatch.setattr("androidharness.cli.UIAutomatorDevice", FakeUIDevice)


def test_peek_prints_rendered_observation_for_current_screen(isolated_home, stub_peek):
    result = runner.invoke(app, ["peek"])
    assert result.exit_code == 0, result.stdout
    # Both buttons appear in the prose-rendered observation.
    assert '[1] Button "Settings" (clickable)' in result.stdout
    assert '[2] Button "Wi-Fi" (clickable)' in result.stdout
    # The header on stderr names the node count.
    combined = result.stdout + (result.stderr or "")
    assert "2 nodes" in combined


def test_peek_with_resource_ids_flag_overrides_config(isolated_home, stub_peek):
    """The default config has resource_id_in_render=False. --with-resource-ids
    must override per-invocation."""
    result = runner.invoke(app, ["peek", "--with-resource-ids"])
    assert result.exit_code == 0, result.stdout
    assert "#settings_row" in result.stdout
    # Wi-Fi node has no resource-id; it must NOT get a stray suffix.
    assert '[2] Button "Wi-Fi" (clickable)' in result.stdout


def test_peek_no_resource_ids_flag_overrides_config(isolated_home, stub_peek, tmp_path):
    """Inverse: config sets resource_id_in_render=true but --no-resource-ids
    suppresses for one peek."""
    cfg = isolated_home / ".androidharness" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("perception:\n  resource_id_in_render: true\n")
    result = runner.invoke(app, ["peek", "--no-resource-ids"])
    assert result.exit_code == 0, result.stdout
    assert "#settings_row" not in result.stdout


def test_peek_raw_xml_flag_dumps_the_uiautomator_xml(isolated_home, stub_peek):
    result = runner.invoke(app, ["peek", "--raw-xml"])
    assert result.exit_code == 0, result.stdout
    assert "<hierarchy" in result.stdout
    assert "android.widget.Button" in result.stdout
    # Raw mode skips parsing — no node-count header on stderr.
    assert "nodes" not in (result.stderr or "")


def test_peek_errors_when_no_device_connected(isolated_home, monkeypatch):
    monkeypatch.setattr("androidharness.cli.list_devices", lambda: [])
    result = runner.invoke(app, ["peek"])
    assert result.exit_code == 1
    combined = (result.stdout or "") + (result.stderr or "")
    assert "no devices" in combined.lower()


def test_peek_does_not_require_api_key(isolated_home, stub_peek, monkeypatch):
    """peek is read-only and must not touch the LLM. The provider env-var
    check (which `run` performs) must NOT fire here."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = runner.invoke(app, ["peek"])
    assert result.exit_code == 0, result.stdout


def test_peek_does_not_invoke_run_task_or_any_llm_client(isolated_home, stub_peek):
    """Belt-and-braces: peek must NOT call run_task or instantiate any LLM
    client. Patch them to MagicMock and assert zero calls."""
    with patch("androidharness.cli.run_task") as run_task, \
         patch("androidharness.cli.LiteLLMClient") as lite, \
         patch("androidharness.cli.LiteLLMRouterClient") as router, \
         patch("androidharness.cli.GoogleGenaiClient") as google:
        result = runner.invoke(app, ["peek"])
    assert result.exit_code == 0, result.stdout
    run_task.assert_not_called()
    lite.assert_not_called()
    router.assert_not_called()
    google.assert_not_called()
