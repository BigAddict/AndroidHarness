from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from androidharness.cli import app
from androidharness.config import AndroidHarnessConfig
from androidharness.device import DeviceInfo
from androidharness.runner import RunOutcome

runner = CliRunner()


@pytest.fixture
def isolated_home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ANDROIDHARNESS_CONFIG", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    return tmp_path


def _ok_outcome() -> RunOutcome:
    return RunOutcome(run_dir="/tmp/fake", status="done", success=True, reason="ok", turns=1)


@pytest.fixture
def stub_run(monkeypatch):
    """Replace device/client wiring + run_task with stubs that capture invocation kwargs."""
    captured: dict = {}

    def fake_list_devices():
        return [DeviceInfo(serial="STUBSERIAL", model="StubPixel")]

    class FakeUIDevice:
        @classmethod
        def connect(cls, serial: str):
            captured["device_serial"] = serial
            obj = cls()
            obj.serial = serial
            obj.model = "StubPixel"
            return obj

    class FakeClient:
        pass

    def fake_run_task(**kwargs):
        captured.update(kwargs)
        return _ok_outcome()

    monkeypatch.setattr("androidharness.cli.list_devices", fake_list_devices)
    monkeypatch.setattr("androidharness.cli.UIAutomatorDevice", FakeUIDevice)
    monkeypatch.setattr("androidharness.cli.GoogleGenaiClient", FakeClient)
    monkeypatch.setattr("androidharness.cli.LiteLLMClient", FakeClient)
    monkeypatch.setattr("androidharness.cli.run_task", fake_run_task)
    return captured


def test_run_uses_config_defaults_when_flags_omitted(isolated_home, stub_run, tmp_path):
    cfg = isolated_home / ".androidharness" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "defaults:\n"
        "  model: gemini-2.5-pro\n"
        "  max_turns: 99\n"
        "  wall_clock_s: 42.0\n"
        f"  runs_dir: {tmp_path / 'cfgruns'}\n"
        f"  logs_dir: {tmp_path / 'cfglogs'}\n"
    )
    result = runner.invoke(app, ["run", "open settings"])
    assert result.exit_code == 0, result.stdout
    # use_litellm=True (default) slash-prefixes bare model names with the
    # selected provider, so `gemini-2.5-pro` reaches the agent as `gemini/gemini-2.5-pro`.
    assert stub_run["model"] == "gemini/gemini-2.5-pro"
    assert stub_run["max_turns"] == 99
    assert stub_run["wall_clock_s"] == 42.0
    assert str(stub_run["runs_root"]).endswith("cfgruns")


def test_cli_flags_override_config(isolated_home, stub_run, tmp_path):
    cfg = isolated_home / ".androidharness" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("defaults:\n  model: gemini-2.5-pro\n  max_turns: 99\n")
    result = runner.invoke(
        app,
        ["run", "open settings", "--model", "gemini-2.5-flash", "--max-turns", "7"],
    )
    assert result.exit_code == 0, result.stdout
    # CLI --model wins over the config, then gets slash-prefixed for LiteLLM.
    assert stub_run["model"] == "gemini/gemini-2.5-flash"
    assert stub_run["max_turns"] == 7


def test_run_with_no_config_file_uses_schema_defaults(isolated_home, stub_run):
    result = runner.invoke(app, ["run", "open settings"])
    assert result.exit_code == 0, result.stdout
    assert stub_run["model"] == "gemini/gemini-2.5-flash"
    assert stub_run["max_turns"] == 40
    assert stub_run["wall_clock_s"] == 600.0


def test_run_config_device_serial_picked_when_no_flag(isolated_home, stub_run, monkeypatch):
    from androidharness.device import DeviceInfo

    def two_devices():
        return [
            DeviceInfo(serial="STUBSERIAL", model="StubPixel"),
            DeviceInfo(serial="OTHER", model="Other"),
        ]

    monkeypatch.setattr("androidharness.cli.list_devices", two_devices)

    cfg = isolated_home / ".androidharness" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("defaults:\n  device_serial: OTHER\n")
    result = runner.invoke(app, ["run", "open settings"])
    assert result.exit_code == 0, result.stdout
    assert stub_run["device_serial"] == "OTHER"


# ---------------------------------------------------------------------------
# New tests — LiteLLM routing (Task 7)
# ---------------------------------------------------------------------------


def _write_cfg(tmp_path, cfg_dict):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(cfg_dict, sort_keys=False))
    return p


def test_cli_run_uses_litellm_client_by_default(tmp_path, monkeypatch):
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")

    with patch("androidharness.cli.LiteLLMClient") as lite, \
         patch("androidharness.cli.GoogleGenaiClient") as google, \
         patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]), \
         patch("androidharness.cli.run_task") as run_task:
        run_task.return_value = type("O", (), {
            "run_dir": "/tmp/x", "status": "done", "success": True,
            "reason": "ok", "turns": 1,
        })()
        result = runner.invoke(app, ["run", "open settings", "--config", str(cfg_path)])

    assert result.exit_code == 0, result.stdout
    lite.assert_called_once()
    google.assert_not_called()


def test_cli_run_falls_back_to_google_when_use_litellm_false(tmp_path, monkeypatch):
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg["providers"]["use_litellm"] = False
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")

    with patch("androidharness.cli.LiteLLMClient") as lite, \
         patch("androidharness.cli.GoogleGenaiClient") as google, \
         patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]), \
         patch("androidharness.cli.run_task") as run_task:
        run_task.return_value = type("O", (), {
            "run_dir": "/tmp/x", "status": "done", "success": True,
            "reason": "ok", "turns": 1,
        })()
        result = runner.invoke(app, ["run", "open settings", "--config", str(cfg_path)])

    assert result.exit_code == 0, result.stdout
    google.assert_called_once()
    lite.assert_not_called()


def test_cli_run_errors_when_selected_provider_api_key_env_var_missing(tmp_path, monkeypatch):
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]):
        result = runner.invoke(app, ["run", "x", "--config", str(cfg_path)])

    assert result.exit_code == 1
    # Typer/Click route stderr separately; the message ends up in result.output via the runner's
    # default mix_stderr behavior. Search both for resilience across Click versions.
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "GEMINI_API_KEY" in combined


def test_cli_run_uses_router_client_when_throttler_enabled(tmp_path, monkeypatch):
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg["throttler"]["enabled"] = True
    cfg["providers"]["logical_models"] = {"fast": ["gemini/gemini-2.5-flash"]}
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")

    with patch("androidharness.cli.LiteLLMRouterClient") as router, \
         patch("androidharness.cli.LiteLLMClient") as lite, \
         patch("androidharness.cli.GoogleGenaiClient") as google, \
         patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]), \
         patch("androidharness.cli.run_task") as run_task:
        run_task.return_value = type("O", (), {
            "run_dir": "/tmp/x", "status": "done", "success": True,
            "reason": "ok", "turns": 1,
        })()
        result = runner.invoke(app, ["run", "open settings", "--config", str(cfg_path)])

    assert result.exit_code == 0, result.stdout
    router.assert_called_once()
    lite.assert_not_called()
    google.assert_not_called()


def test_cli_run_keeps_litellm_client_when_throttler_disabled(tmp_path, monkeypatch):
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg["throttler"]["enabled"] = False
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")

    with patch("androidharness.cli.LiteLLMRouterClient") as router, \
         patch("androidharness.cli.LiteLLMClient") as lite, \
         patch("androidharness.cli.GoogleGenaiClient") as google, \
         patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]), \
         patch("androidharness.cli.run_task") as run_task:
        run_task.return_value = type("O", (), {
            "run_dir": "/tmp/x", "status": "done", "success": True,
            "reason": "ok", "turns": 1,
        })()
        result = runner.invoke(app, ["run", "open settings", "--config", str(cfg_path)])

    assert result.exit_code == 0, result.stdout
    lite.assert_called_once()
    router.assert_not_called()
    google.assert_not_called()


def test_cli_run_with_throttler_requires_keys_for_every_fallback_provider(tmp_path, monkeypatch):
    """With throttler enabled and a chain that includes anthropic, the CLI
    must require ANTHROPIC_API_KEY too — not just the default provider's key."""
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg["throttler"]["enabled"] = True
    cfg["providers"]["logical_models"] = {"fast": [
        "gemini/gemini-2.5-flash",
        "anthropic/claude-haiku-4-5",
    ]}
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]):
        result = runner.invoke(app, ["run", "open settings", "--config", str(cfg_path)])

    assert result.exit_code == 1
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "ANTHROPIC_API_KEY" in combined
