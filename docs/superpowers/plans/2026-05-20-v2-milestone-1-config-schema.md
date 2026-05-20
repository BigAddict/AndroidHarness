# v2 Milestone 1 — Config Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a Pydantic-validated `AndroidHarnessConfig` persisted as YAML at `~/.androidharness/config.yaml`, plus an `androidharness config` subcommand group, plus wiring `run` to read defaults from the config (CLI flags still override).

**Architecture:** One new module `androidharness/config.py` holds the schema, default-path resolution, and load/save helpers. The CLI gains a `config` Typer sub-app with `init` / `show` / `path` / `validate`. `run` is changed in one place: at command entry, load the config, then treat existing Typer option defaults as overrides on top of the config. All v2 seams to come (provider, throttler, policy, memory, perception, logging) get *typed sub-models with safe defaults* now, even though their bodies are minimal — so milestones 2–5 plug in without churning the file format.

**Tech Stack:** Pydantic v2 (validation), PyYAML (round-trip serialization), Typer (CLI), pytest (tests). All already-pinned tools — only Pydantic + PyYAML are net-new deps.

**Spec:** `docs/superpowers/specs/2026-05-20-v2-stack-and-scale-design.md` (milestone #1 in §12).

---

## File Structure

| Path | Purpose |
|---|---|
| `pyproject.toml` | Modify — add `pydantic` + `pyyaml` runtime deps. |
| `androidharness/config.py` | **New.** `AndroidHarnessConfig` + sub-models, `default_config_path()`, `load_config()`, `save_config()`, `DEFAULT_CONFIG_YAML` template. |
| `androidharness/cli.py` | Modify — add `config` Typer sub-app (`init`/`show`/`path`/`validate`); change `run` to load config and use it as the default source under Typer's CLI overrides. |
| `tests/test_config.py` | **New.** Unit tests for schema defaults, sub-model nesting, `extra="forbid"`, load round-trip, save round-trip, malformed YAML errors, missing-file behavior. |
| `tests/test_cli_config.py` | **New.** CLI tests for `config init`/`show`/`path`/`validate` via `typer.testing.CliRunner`. |
| `tests/test_cli_run_config.py` | **New.** Integration test that `run` picks up `defaults.*` from a config file and that CLI flags still override. |

Existing `androidharness/runner.py`, `androidharness/agent.py`, `androidharness/device.py`, `androidharness/perception.py`, `androidharness/tools.py` are **untouched** by this milestone.

---

## Task 1: Add Pydantic + PyYAML dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the two deps**

Edit the `dependencies` list in `pyproject.toml` to insert `pydantic` and `pyyaml`. After the change, the list should read (preserving the surrounding `[project]` block):

```toml
dependencies = [
    "uiautomator2>=3.5.0",
    "uiautodev>=0.14.0",
    "google-genai>=0.3.0",
    "lxml>=5.0.0",
    "pillow>=10.0.0",
    "typer>=0.12.0",
    "adbutils[apk]>=2.12.0",
    "pydantic>=2.7.0",
    "pyyaml>=6.0.1",
]
```

- [ ] **Step 2: Sync the venv**

Run: `uv sync`
Expected: lockfile updates, both packages install, exit code 0.

- [ ] **Step 3: Sanity-check imports**

Run: `uv run python -c "import pydantic, yaml; print(pydantic.VERSION, yaml.__version__)"`
Expected: prints two version strings, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build(deps): add pydantic and pyyaml for v2 config schema"
```

---

## Task 2: Pydantic schema — `AndroidHarnessConfig` and sub-models

The schema is the foundation. Every sub-model (`ProvidersConfig`, `ThrottlerConfig`, `PolicyConfig`, `MemoryConfig`, `PerceptionConfig`, `LoggingConfig`) ships with safe defaults so milestone 1 produces a usable config even though milestones 2–6 will flesh the bodies out. `extra="forbid"` is on every model to catch typos.

**Files:**
- Create: `androidharness/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing schema tests**

Create `tests/test_config.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from androidharness.config import (
    AndroidHarnessConfig,
    DefaultsConfig,
    LoggingConfig,
    MemoryConfig,
    PerceptionConfig,
    PolicyConfig,
    ProvidersConfig,
    ThrottlerConfig,
)


def test_default_config_is_constructable_with_no_args():
    cfg = AndroidHarnessConfig()
    assert cfg.version == 1
    assert isinstance(cfg.defaults, DefaultsConfig)
    assert isinstance(cfg.providers, ProvidersConfig)
    assert isinstance(cfg.throttler, ThrottlerConfig)
    assert isinstance(cfg.policy, PolicyConfig)
    assert isinstance(cfg.memory, MemoryConfig)
    assert isinstance(cfg.perception, PerceptionConfig)
    assert isinstance(cfg.logging, LoggingConfig)


def test_defaults_section_field_values():
    d = DefaultsConfig()
    assert d.model == "gemini-2.5-flash"
    assert d.max_turns == 40
    assert d.wall_clock_s == 600.0
    assert d.runs_dir == "./runs"
    assert d.logs_dir == "./logs"
    assert d.device_serial is None


def test_policy_default_mode_and_per_tool_empty():
    p = PolicyConfig()
    assert p.default_mode == "auto"
    assert p.per_tool == {}


def test_throttler_disabled_by_default_with_empty_buckets():
    t = ThrottlerConfig()
    assert t.enabled is False
    assert t.buckets == {}


def test_memory_disabled_by_default_with_60_day_retention():
    m = MemoryConfig()
    assert m.enabled is False
    assert m.embedding_model == "gemini-text-embedding-004"
    assert m.retention_days == 60


def test_perception_all_compression_steps_off_by_default():
    pc = PerceptionConfig()
    assert pc.sibling_collapse is False
    assert pc.viewport_filter is False
    assert pc.resource_id_in_render is False


def test_logging_defaults():
    log = LoggingConfig()
    assert log.level == "INFO"
    assert log.rotation_mb == 10


def test_unknown_top_level_field_rejected():
    with pytest.raises(ValidationError) as exc:
        AndroidHarnessConfig(unknown_section={})
    assert "unknown_section" in str(exc.value)


def test_unknown_field_in_subsection_rejected():
    with pytest.raises(ValidationError) as exc:
        AndroidHarnessConfig(defaults={"typo_field": 1})
    assert "typo_field" in str(exc.value)


def test_invalid_log_level_rejected():
    with pytest.raises(ValidationError):
        AndroidHarnessConfig(logging={"level": "TOTALLY_INVALID"})


def test_invalid_policy_mode_rejected():
    with pytest.raises(ValidationError):
        AndroidHarnessConfig(policy={"default_mode": "explode"})


def test_max_turns_must_be_positive():
    with pytest.raises(ValidationError):
        AndroidHarnessConfig(defaults={"max_turns": 0})


def test_wall_clock_must_be_positive():
    with pytest.raises(ValidationError):
        AndroidHarnessConfig(defaults={"wall_clock_s": -1})


def test_version_must_be_one():
    with pytest.raises(ValidationError):
        AndroidHarnessConfig(version=2)
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: ImportError / collection error — `androidharness.config` doesn't exist yet.

- [ ] **Step 3: Create the schema module**

Create `androidharness/config.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid")

PolicyMode = Literal["auto", "confirm", "dry-run", "deny"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class DefaultsConfig(BaseModel):
    model_config = _STRICT

    model: str = "gemini-2.5-flash"
    max_turns: int = Field(default=40, gt=0)
    wall_clock_s: float = Field(default=600.0, gt=0)
    runs_dir: str = "./runs"
    logs_dir: str = "./logs"
    device_serial: str | None = None


class ProvidersConfig(BaseModel):
    """Placeholder — fleshed out in milestone 2 (LiteLLM provider seam)."""
    model_config = _STRICT


class ThrottlerConfig(BaseModel):
    """Placeholder — fleshed out in milestone 3 (token bucket + Router)."""
    model_config = _STRICT

    enabled: bool = False
    buckets: dict[str, dict] = Field(default_factory=dict)


class PolicyConfig(BaseModel):
    """Placeholder — fleshed out in milestone 4 (destructive-action gating)."""
    model_config = _STRICT

    default_mode: PolicyMode = "auto"
    per_tool: dict[str, PolicyMode] = Field(default_factory=dict)


class MemoryConfig(BaseModel):
    """Placeholder — fleshed out in milestone 12 (chromadb episodic memory)."""
    model_config = _STRICT

    enabled: bool = False
    embedding_model: str = "gemini-text-embedding-004"
    retention_days: int = Field(default=60, gt=0)


class PerceptionConfig(BaseModel):
    """Placeholder — toggles flip on as milestones 6, 11, 16 land."""
    model_config = _STRICT

    sibling_collapse: bool = False
    viewport_filter: bool = False
    resource_id_in_render: bool = False


class LoggingConfig(BaseModel):
    model_config = _STRICT

    level: LogLevel = "INFO"
    rotation_mb: int = Field(default=10, gt=0)


class AndroidHarnessConfig(BaseModel):
    model_config = _STRICT

    version: Literal[1] = 1
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    throttler: ThrottlerConfig = Field(default_factory=ThrottlerConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: all 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add androidharness/config.py tests/test_config.py
git commit -m "feat(config): add Pydantic schema for v2 AndroidHarnessConfig"
```

---

## Task 3: Path resolution + YAML load/save

`load_config()` returns a fully-defaulted `AndroidHarnessConfig` when the file doesn't exist (so first-time users on `androidharness run` get a working default without `config init`). When the file exists, it parses YAML, runs Pydantic validation, and raises a `ConfigError` with a readable message on validation failure. `save_config()` writes the model as YAML with a leading comment pointing to docs.

**Files:**
- Modify: `androidharness/config.py`
- Modify: `tests/test_config.py` (append load/save tests)

- [ ] **Step 1: Append load/save tests**

Append to `tests/test_config.py`:

```python
from pathlib import Path

import yaml

from androidharness.config import (
    CONFIG_HEADER,
    ConfigError,
    default_config_path,
    load_config,
    save_config,
)


def test_default_config_path_is_under_home_androidharness(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ANDROIDHARNESS_CONFIG", raising=False)
    assert default_config_path() == tmp_path / ".androidharness" / "config.yaml"


def test_default_config_path_respects_env_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom.yaml"
    monkeypatch.setenv("ANDROIDHARNESS_CONFIG", str(custom))
    assert default_config_path() == custom


def test_load_config_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "does_not_exist.yaml")
    assert cfg == AndroidHarnessConfig()


def test_load_config_empty_file_returns_defaults(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    cfg = load_config(p)
    assert cfg == AndroidHarnessConfig()


def test_load_config_partial_yaml_merges_with_defaults(tmp_path):
    p = tmp_path / "partial.yaml"
    p.write_text("defaults:\n  model: gemini-2.5-pro\n  max_turns: 80\n")
    cfg = load_config(p)
    assert cfg.defaults.model == "gemini-2.5-pro"
    assert cfg.defaults.max_turns == 80
    # Unspecified fields keep their defaults
    assert cfg.defaults.wall_clock_s == 600.0
    assert cfg.policy.default_mode == "auto"


def test_load_config_malformed_yaml_raises_config_error(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("defaults: : : oops\n")
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    assert str(p) in str(exc.value)


def test_load_config_validation_failure_raises_config_error(tmp_path):
    p = tmp_path / "bad_schema.yaml"
    p.write_text("defaults:\n  max_turns: -3\n")
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    assert "max_turns" in str(exc.value)


def test_save_then_load_round_trip(tmp_path):
    src = AndroidHarnessConfig(
        defaults={"model": "gemini-2.5-pro", "max_turns": 25},
        policy={"default_mode": "confirm"},
    )
    p = tmp_path / "config.yaml"
    save_config(src, p)
    loaded = load_config(p)
    assert loaded == src


def test_save_config_creates_parent_directories(tmp_path):
    p = tmp_path / "nested" / "subdir" / "config.yaml"
    save_config(AndroidHarnessConfig(), p)
    assert p.exists()


def test_save_config_writes_header_comment(tmp_path):
    p = tmp_path / "with_header.yaml"
    save_config(AndroidHarnessConfig(), p)
    text = p.read_text()
    assert text.startswith(CONFIG_HEADER)
    body = text[len(CONFIG_HEADER):]
    # Body must be valid YAML that round-trips through pydantic
    parsed = yaml.safe_load(body)
    assert parsed["version"] == 1
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: 10 new tests fail with ImportError for `load_config`, `save_config`, `ConfigError`, `default_config_path`, `CONFIG_HEADER`.

- [ ] **Step 3: Implement load/save/path in `androidharness/config.py`**

Append to `androidharness/config.py`:

```python
import os
from pathlib import Path

import yaml
from pydantic import ValidationError

CONFIG_HEADER = (
    "# AndroidHarness config — see docs/superpowers/specs/2026-05-20-v2-stack-and-scale-design.md\n"
    "# Generated by `androidharness config init`. Edit by hand or via the Settings UI (v2.0).\n"
    "---\n"
)


class ConfigError(RuntimeError):
    """Raised when a config file is malformed or fails schema validation."""


def default_config_path() -> Path:
    """Resolve the config path, honoring the `ANDROIDHARNESS_CONFIG` env var override."""
    override = os.environ.get("ANDROIDHARNESS_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("HOME", "~")).expanduser() / ".androidharness" / "config.yaml"


def load_config(path: Path | None = None) -> AndroidHarnessConfig:
    """Load config from disk. Missing file → defaults. Malformed → ConfigError."""
    p = Path(path) if path is not None else default_config_path()
    if not p.exists():
        return AndroidHarnessConfig()
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"failed to parse YAML in {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"config at {p} must be a YAML mapping at the top level")
    try:
        return AndroidHarnessConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"config at {p} failed validation:\n{e}") from e


def save_config(config: AndroidHarnessConfig, path: Path | None = None) -> Path:
    """Serialize config to YAML with a header comment. Creates parent dirs."""
    p = Path(path) if path is not None else default_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        config.model_dump(mode="json"),
        sort_keys=False,
        default_flow_style=False,
    )
    p.write_text(CONFIG_HEADER + body)
    return p
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: all tests (original 13 + new 10) pass.

- [ ] **Step 5: Commit**

```bash
git add androidharness/config.py tests/test_config.py
git commit -m "feat(config): add YAML load/save and ANDROIDHARNESS_CONFIG path resolution"
```

---

## Task 4: `androidharness config` subcommand group

A Typer sub-app with four commands:

- `init` — writes the default config to `default_config_path()` (or `--path`). Refuses to overwrite an existing file unless `--force`.
- `show` — prints the resolved, validated config as YAML to stdout. Reads from `default_config_path()` (or `--path`).
- `path` — prints the resolved config path. Useful for `$(androidharness config path)` in shell.
- `validate` — loads the config and prints `ok` (exit 0) or the validation error and exits with code 1.

**Files:**
- Modify: `androidharness/cli.py`
- Create: `tests/test_cli_config.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli_config.py`:

```python
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
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/test_cli_config.py -v`
Expected: collection succeeds (`app` is importable) but every test fails because the `config` subcommand isn't registered yet.

- [ ] **Step 3: Add the `config` sub-app to `androidharness/cli.py`**

At the top of `androidharness/cli.py`, add imports next to existing ones:

```python
from pathlib import Path

import typer
import yaml

from androidharness.config import (
    AndroidHarnessConfig,
    ConfigError,
    default_config_path,
    load_config,
    save_config,
)
```

(`Path`, `typer`, `yaml` may need de-duplicating with what's already there. `Path` is already imported via the existing `from pathlib import Path` — don't import twice.)

After the `app = typer.Typer(...)` line, add:

```python
config_app = typer.Typer(add_completion=False, help="Inspect or edit the AndroidHarness config file.")
app.add_typer(config_app, name="config")


def _resolve_config_path(path: Path | None) -> Path:
    return path if path is not None else default_config_path()


@config_app.command("path")
def config_path_cmd(
    path: Path | None = typer.Option(None, "--path", help="Override the config path."),
) -> None:
    """Print the resolved config file path."""
    typer.echo(str(_resolve_config_path(path)))


@config_app.command("init")
def config_init_cmd(
    path: Path | None = typer.Option(None, "--path", help="Override the config path."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config file."),
) -> None:
    """Write a default config file."""
    target = _resolve_config_path(path)
    if target.exists() and not force:
        typer.echo(f"error: config already exists at {target} (use --force to overwrite)", err=True)
        raise typer.Exit(code=1)
    written = save_config(AndroidHarnessConfig(), target)
    typer.echo(f"wrote default config to {written}")


@config_app.command("show")
def config_show_cmd(
    path: Path | None = typer.Option(None, "--path", help="Override the config path."),
) -> None:
    """Print the loaded config as YAML."""
    target = _resolve_config_path(path)
    try:
        cfg = load_config(target)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, default_flow_style=False), nl=False)


@config_app.command("validate")
def config_validate_cmd(
    path: Path | None = typer.Option(None, "--path", help="Override the config path."),
) -> None:
    """Validate the config file. Exits 0 on success, 1 on error."""
    target = _resolve_config_path(path)
    try:
        load_config(target)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"ok: {target}")
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `uv run pytest tests/test_cli_config.py -v`
Expected: all 9 tests pass.

- [ ] **Step 5: Smoke-test from the shell**

Run:
```bash
HOME=/tmp/ah-test-home uv run androidharness config path
HOME=/tmp/ah-test-home uv run androidharness config init
HOME=/tmp/ah-test-home uv run androidharness config show
HOME=/tmp/ah-test-home uv run androidharness config validate
```
Expected: prints a path, writes the file, shows YAML with `version: 1`, prints `ok: ...`. Then `rm -rf /tmp/ah-test-home`.

- [ ] **Step 6: Commit**

```bash
git add androidharness/cli.py tests/test_cli_config.py
git commit -m "feat(cli): add 'androidharness config' subcommand group (init/show/path/validate)"
```

---

## Task 5: Wire `run` to read defaults from config

When the user runs `androidharness run TASK`, default values for `--model`, `--max-turns`, `--wall-clock`, `--runs-dir`, `--logs-dir`, and (when neither `--serial` nor `--device-index` is given) `defaults.device_serial` come from the loaded config. **CLI flags still override the config** — that's the spec's parity contract.

The trick: Typer fills option defaults at parse time, so we can't tell "user passed `--model X`" from "user accepted the default". Solution: switch each option's default to a sentinel (`None`), and *after* parsing, fall back to the config value when the sentinel is still there.

**Files:**
- Modify: `androidharness/cli.py` (the `run_cmd` function only)
- Create: `tests/test_cli_run_config.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_cli_run_config.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/test_cli_run_config.py -v`
Expected: all 4 tests fail — current `run_cmd` ignores config.

- [ ] **Step 3: Update `run_cmd` in `androidharness/cli.py`**

Replace the existing `run_cmd` function with this version. Change the option defaults to `None`/sentinels so we can detect "not passed" and then resolve against the loaded config.

```python
@app.command("run")
def run_cmd(
    task: str = typer.Argument(..., help="Natural-language task to drive on the device."),
    serial: str | None = typer.Option(None, "--serial", "-s"),
    device_index: int | None = typer.Option(None, "--device-index", "-i"),
    model: str | None = typer.Option(None, "--model"),
    max_turns: int | None = typer.Option(None, "--max-turns"),
    wall_clock: float | None = typer.Option(None, "--wall-clock"),
    runs_dir: Path | None = typer.Option(None, "--run-dir"),
    logs_dir: Path | None = typer.Option(None, "--logs-dir"),
    config_path: Path | None = typer.Option(None, "--config", help="Override the config path."),
) -> None:
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e

    d = cfg.defaults
    model = model if model is not None else d.model
    max_turns = max_turns if max_turns is not None else d.max_turns
    wall_clock = wall_clock if wall_clock is not None else d.wall_clock_s
    runs_dir = runs_dir if runs_dir is not None else Path(d.runs_dir)
    logs_dir = logs_dir if logs_dir is not None else Path(d.logs_dir)

    log_path = setup_file_logging(logs_dir)
    typer.echo(f"logs: {log_path}", err=True)

    if serial and device_index is not None:
        typer.echo("error: --serial and --device-index are mutually exclusive", err=True)
        raise typer.Exit(code=2)

    infos = list_devices()
    if not infos:
        typer.echo("no devices connected (check 'adb devices')", err=True)
        raise typer.Exit(code=1)

    if serial:
        if serial not in {i.serial for i in infos}:
            typer.echo(f"serial {serial!r} not in connected devices", err=True)
            raise typer.Exit(code=1)
        chosen = serial
    elif device_index is not None:
        if not 0 <= device_index < len(infos):
            typer.echo(f"--device-index out of range: {device_index}", err=True)
            raise typer.Exit(code=1)
        chosen = infos[device_index].serial
    elif d.device_serial is not None:
        if d.device_serial not in {i.serial for i in infos}:
            typer.echo(
                f"config defaults.device_serial {d.device_serial!r} not in connected devices",
                err=True,
            )
            raise typer.Exit(code=1)
        chosen = d.device_serial
    else:
        if len(infos) == 1:
            chosen = infos[0].serial
        else:
            typer.echo("multiple devices — pass --serial or --device-index:", err=True)
            for i, info in enumerate(infos):
                typer.echo(f"  [{i}] {info.serial}  {info.model}", err=True)
            raise typer.Exit(code=1)

    if not os.environ.get("GOOGLE_API_KEY"):
        typer.echo("error: GOOGLE_API_KEY env var is not set", err=True)
        raise typer.Exit(code=1)

    device = UIAutomatorDevice.connect(chosen)
    client = GoogleGenaiClient()
    runs_dir.mkdir(parents=True, exist_ok=True)

    outcome = run_task(
        task=task,
        device=device,
        client=client,
        model=model,
        runs_root=runs_dir,
        max_turns=max_turns,
        wall_clock_s=wall_clock,
    )
    typer.echo(f"run dir: {outcome.run_dir}")
    typer.echo(f"status:  {outcome.status}")
    typer.echo(f"success: {outcome.success}")
    typer.echo(f"reason:  {outcome.reason}")
    typer.echo(f"turns:   {outcome.turns}")
    sys.exit(0 if outcome.success else 1)
```

- [ ] **Step 4: Run the new test file, confirm pass**

Run: `uv run pytest tests/test_cli_run_config.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Run the full suite to catch regressions**

Run: `uv run pytest -v`
Expected: every previously-passing test still passes; new tests pass; no regressions in `test_runner.py`, `test_agent.py`, `test_tools.py`, `test_perception.py`. (`test_device_integration.py` stays skipped without `ANDROIDHARNESS_DEVICE_SERIAL`.)

- [ ] **Step 6: Lint**

Run: `uv run ruff check androidharness tests`
Expected: no lint errors. Fix any imports flagged by I001 by re-ordering.

- [ ] **Step 7: Commit**

```bash
git add androidharness/cli.py tests/test_cli_run_config.py
git commit -m "feat(cli): wire 'androidharness run' defaults to AndroidHarnessConfig"
```

---

## Verification checklist (run before declaring milestone 1 done)

- [ ] `uv run pytest -v` — full suite green.
- [ ] `uv run ruff check androidharness tests` — clean.
- [ ] `HOME=/tmp/ah-smoke uv run androidharness config init && HOME=/tmp/ah-smoke uv run androidharness config show` — prints the file you just wrote.
- [ ] `HOME=/tmp/ah-smoke uv run androidharness config validate` — prints `ok: …`.
- [ ] `rm -rf /tmp/ah-smoke` afterwards.

---

## What this milestone deliberately does NOT do

These belong to later milestones and would expand the diff:

- **No LiteLLM client / no provider routing.** `ProvidersConfig` is an empty placeholder. Milestone 2 fills it.
- **No throttler logic.** `ThrottlerConfig.buckets` accepts `dict[str, dict]` but nothing reads it yet. Milestone 3 fills it.
- **No policy gate.** `PolicyConfig` is typed but not consulted by tools dispatch. Milestone 4 wires it.
- **No web UI.** Milestone 5.
- **No perception toggles wired into `perception.py`.** Flags exist; renderer ignores them. Milestone 6+ flip them on.
- **No migration tooling.** `version: Literal[1]` is the seed for future `v1 → v2` migration logic; no upgrade path exists yet because there's nothing to upgrade from.
