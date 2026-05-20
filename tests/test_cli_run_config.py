from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from androidharness.cli import app
from androidharness.device import DeviceInfo
from androidharness.runner import RunOutcome

runner = CliRunner()


@pytest.fixture
def isolated_home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ANDROIDHARNESS_CONFIG", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-tests")
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
    assert stub_run["model"] == "gemini-2.5-pro"
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
    assert stub_run["model"] == "gemini-2.5-flash"
    assert stub_run["max_turns"] == 7


def test_run_with_no_config_file_uses_schema_defaults(isolated_home, stub_run):
    result = runner.invoke(app, ["run", "open settings"])
    assert result.exit_code == 0, result.stdout
    assert stub_run["model"] == "gemini-2.5-flash"
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
