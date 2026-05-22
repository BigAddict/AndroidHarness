from __future__ import annotations

from typer.testing import CliRunner

from androidharness.cli import app


def test_serve_help_works_without_invoking_uvicorn():
    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.stdout
    assert "--host" in result.stdout


def test_serve_emits_friendly_error_when_web_extra_missing(monkeypatch, capsys):
    """If fastapi isn't installed, the user must see a one-line install hint."""

    # Simulate the import failure by sabotaging the lazy import.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "androidharness.web" or name.startswith("androidharness.web."):
            raise ModuleNotFoundError("No module named 'fastapi'", name="fastapi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--port", "9999"])
    assert result.exit_code == 1
    # Typer's CliRunner captures stdout; friendly errors are written to stdout
    # (no err=True) so they remain visible regardless of shell redirection.
    assert "[web]" in result.output
    assert "pip install" in result.output or "uv add" in result.output


def test_serve_reraises_unrelated_import_errors(monkeypatch):
    """A genuine bug (e.g., syntax error in web/) must not be swallowed."""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "androidharness.web.app":
            raise ModuleNotFoundError("No module named 'totally_unrelated_thing'", name="totally_unrelated_thing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    runner = CliRunner()
    result = runner.invoke(app, ["serve"])
    # Either the CLI re-raises (exception in result.exception) or exits non-zero with the unrelated name.
    assert result.exit_code != 0
    output = (result.stdout or "") + (str(result.exception) if result.exception else "")
    assert "totally_unrelated_thing" in output
