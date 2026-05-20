from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from androidharness.cli import app
from androidharness.config import CONFIG_HEADER, load_config

runner = CliRunner()


@pytest.fixture
def isolated_home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ANDROIDHARNESS_CONFIG", raising=False)
    return tmp_path


def test_config_path_prints_resolved_default(isolated_home):
    result = runner.invoke(app, ["config", "path"])
    assert result.exit_code == 0
    assert str(isolated_home / ".androidharness" / "config.yaml") in result.stdout


def test_config_path_honors_path_flag(tmp_path):
    custom = tmp_path / "elsewhere.yaml"
    result = runner.invoke(app, ["config", "path", "--path", str(custom)])
    assert result.exit_code == 0
    assert str(custom) in result.stdout


def test_config_init_writes_default_file(isolated_home):
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 0, result.stdout
    target = isolated_home / ".androidharness" / "config.yaml"
    assert target.exists()
    text = target.read_text()
    assert text.startswith(CONFIG_HEADER)
    # Round-trip: loadable + matches defaults
    loaded = load_config(target)
    assert loaded.defaults.model == "gemini-2.5-flash"


def test_config_init_refuses_to_overwrite_without_force(isolated_home):
    target = isolated_home / ".androidharness" / "config.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("# pretend existing\n")
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code != 0
    assert "exists" in result.stdout.lower() or "exists" in (result.stderr or "").lower()
    assert target.read_text() == "# pretend existing\n"


def test_config_init_overwrites_with_force(isolated_home):
    target = isolated_home / ".androidharness" / "config.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("# pretend existing\n")
    result = runner.invoke(app, ["config", "init", "--force"])
    assert result.exit_code == 0, result.stdout
    assert target.read_text().startswith(CONFIG_HEADER)


def test_config_show_prints_yaml_with_defaults(isolated_home):
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.stdout
    assert "version: 1" in result.stdout
    assert "gemini-2.5-flash" in result.stdout


def test_config_show_reads_existing_file(isolated_home):
    target = isolated_home / ".androidharness" / "config.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("defaults:\n  model: gemini-2.5-pro\n")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "gemini-2.5-pro" in result.stdout


def test_config_validate_ok_on_default(isolated_home):
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 0
    assert "ok" in result.stdout.lower()


def test_config_validate_fails_on_bad_file(isolated_home):
    target = isolated_home / ".androidharness" / "config.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("defaults:\n  max_turns: -5\n")
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code != 0
    combined = result.stdout + (result.stderr or "")
    assert "max_turns" in combined
