# v2 Milestone 5 — Settings UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a localhost FastAPI + HTMX Settings UI that edits the shipped seam config (providers, logical models, throttler, policy, devices, logging, defaults) so the user can change every M1–M4 knob without hand-editing `~/.androidharness/config.yaml`.

**Architecture:** A new `androidharness/web/` subpackage, lazy-imported from `cli.py serve` so the `[web]` extra is genuinely optional. `ConfigStore` owns atomic load/save of the YAML file. Routes follow `GET /panel/<name>` for partial render and `PATCH /config/<section>` for save-or-show-errors. HTMX swaps the panel container with the response. Validation runs the full Pydantic config end-to-end so cross-section invariants are caught. API keys are env-var references only — read via a `pydantic-settings` layer in `web/secrets.py`, never persisted to the YAML file.

**Tech Stack:** FastAPI, Jinja2, HTMX (CDN script tag — no build step), python-multipart, pydantic-settings, vanilla CSS, uvicorn, pytest with FastAPI's `TestClient`.

**Spec:** `docs/superpowers/specs/2026-05-22-v2-milestone-5-settings-ui-design.md`.

**Design decisions (user-confirmed at brainstorming time):**
1. Config-only, shipped-seams scope — defer Memory, Perception, Launcher panels.
2. Atomic file replace on save; no hot-reload (runs snapshot config at start).
3. Env-var references only for secrets, with a `pydantic-settings` layer added in M5.
4. Plain hand-written CSS, no design framework, no build step.
5. Inline field errors via HTMX-swapped form re-renders; no top-of-page error summary.

---

## File Structure

| Path | Status | Purpose |
|---|---|---|
| `pyproject.toml` | Modify | Add `[project.optional-dependencies] web = [...]`. |
| `androidharness/web/__init__.py` | New | Empty marker; re-exports `create_app` from `app.py`. |
| `androidharness/web/store.py` | New | `ConfigStore` — load + atomic-write of `~/.androidharness/config.yaml`. |
| `androidharness/web/secrets.py` | New | `ProviderSecrets` — pydantic-settings layer for env-var presence checks. |
| `androidharness/web/devices.py` | New | Wraps `androidharness.device.list_devices()` for the Devices panel. |
| `androidharness/web/forms.py` | New | `unflatten(flat: Mapping[str, str]) -> dict` helper for dotted form keys. |
| `androidharness/web/app.py` | New | `create_app(config_path) -> FastAPI` — DI, templates, static mount, route registration. |
| `androidharness/web/routes.py` | New | Route handlers, one per panel; the `render_panel` helper. |
| `androidharness/web/templates/base.html` | New | Sidebar nav + panel slot + HTMX `<script>` tag. |
| `androidharness/web/templates/index.html` | New | Extends `base`, pre-renders the Providers panel. |
| `androidharness/web/templates/_providers.html` | New | Providers panel (with `is_set` badges). |
| `androidharness/web/templates/_models.html` | New | Logical-models panel. |
| `androidharness/web/templates/_throttler.html` | New | Throttler panel. |
| `androidharness/web/templates/_policy.html` | New | Policy panel. |
| `androidharness/web/templates/_devices.html` | New | Devices panel (live `adb devices` + default-serial select). |
| `androidharness/web/templates/_logging.html` | New | Logging panel. |
| `androidharness/web/templates/_general.html` | New | General defaults panel. |
| `androidharness/web/static/styles.css` | New | Hand-written CSS, system font stack, ~150 lines. |
| `androidharness/cli.py` | Modify | Add `serve` command with lazy `web` import + missing-extra error path. |
| `tests/web/__init__.py` | New | Marker. |
| `tests/web/test_store.py` | New | Round-trip, atomic write, malformed YAML, missing-file → defaults. |
| `tests/web/test_secrets.py` | New | `ProviderSecrets.is_set/get` against monkeypatched `os.environ`. |
| `tests/web/test_devices.py` | New | `list_adb_devices` delegates to `device.list_devices`; failure → empty list. |
| `tests/web/test_forms.py` | New | `unflatten` happy path + nested dotted keys + collision rejection. |
| `tests/web/test_app.py` | New | `create_app` returns a FastAPI; GET `/` renders sidebar + default panel. |
| `tests/web/test_routes_general.py` | New | GET / valid PATCH / invalid PATCH for `general` panel. |
| `tests/web/test_routes_logging.py` | New | Same shape for `logging`. |
| `tests/web/test_routes_devices.py` | New | Same shape for `devices` (with monkeypatched `list_devices`). |
| `tests/web/test_routes_policy.py` | New | Same shape for `policy`. |
| `tests/web/test_routes_throttler.py` | New | Same shape for `throttler`. |
| `tests/web/test_routes_models.py` | New | Same shape for `models`. |
| `tests/web/test_routes_providers.py` | New | Same shape for `providers`, plus the secrets-badge rendering. |
| `tests/test_cli_serve.py` | New | `androidharness serve --help` works; missing-extra error path is friendly. |
| `docs/configuration.md` | Modify | Add "Settings UI" section pointing at `androidharness serve`. |
| `docs/architecture.md` | Modify | Add a Web UI module paragraph. |
| `docs/getting-started.md` | Modify | Mention `androidharness serve` as the alternative to hand-editing YAML. |
| `docs/roadmap.md` | Modify | Mark M5 Shipped with the commit range. |

Untouched: `agent.py`, `llm.py`, `policy.py`, `device.py`, `perception.py`, `render.py`, `tools.py`, `runner.py`, `imaging.py`, `logging_setup.py`, `config.py`.

---

## Task 1: Packaging — add `[web]` optional dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit `pyproject.toml`**

Add a new section after the `dependencies = [...]` block and before `[project.scripts]`:

```toml
[project.optional-dependencies]
web = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
    "jinja2>=3.1.0",
    "python-multipart>=0.0.9",
    "pydantic-settings>=2.5.0",
]
```

- [ ] **Step 2: Sync deps and confirm the extra installs**

Run: `uv sync --extra web`
Expected: `Resolved …` then `Installed …` listing `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `pydantic-settings`. No errors.

- [ ] **Step 3: Confirm base install still works without `[web]`**

Run: `uv run python -c "import androidharness; print('ok')"`
Expected: prints `ok`. (Base import must not touch the web subpackage.)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add [web] optional extra (fastapi, jinja2, htmx deps, pydantic-settings)"
```

---

## Task 2: `ConfigStore` — atomic load and write

**Files:**
- Create: `androidharness/web/__init__.py`
- Create: `androidharness/web/store.py`
- Test: `tests/web/__init__.py`
- Test: `tests/web/test_store.py`

- [ ] **Step 1: Create the package markers**

Create `androidharness/web/__init__.py`:

```python
"""Settings UI (v2 milestone 5). Lazy-imported from cli.py — requires the [web] extra."""

from androidharness.web.app import create_app

__all__ = ["create_app"]
```

Create `tests/web/__init__.py` empty (touch).

- [ ] **Step 2: Write failing tests**

Create `tests/web/test_store.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from androidharness.config import AndroidHarnessConfig, ConfigError
from androidharness.web.store import ConfigStore


def test_load_missing_file_returns_defaults(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.yaml")
    cfg = store.load()
    assert isinstance(cfg, AndroidHarnessConfig)
    assert cfg.version == 1
    assert cfg.providers.default == "gemini"


def test_round_trip_preserves_user_edits(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.yaml")
    cfg = store.load()
    cfg.policy.confirm_timeout_s = 7
    store.write(cfg)

    reloaded = ConfigStore(tmp_path / "config.yaml").load()
    assert reloaded.policy.confirm_timeout_s == 7


def test_write_is_atomic_no_tmp_file_left_behind(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.yaml")
    store.write(store.load())

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], f"atomic write leaked tmp files: {leftovers}"


def test_write_replaces_existing_file_atomically(tmp_path: Path, monkeypatch):
    """If os.replace is interrupted, the original file must still be intact."""
    config_path = tmp_path / "config.yaml"
    store = ConfigStore(config_path)

    original = store.load()
    original.policy.confirm_timeout_s = 5
    store.write(original)
    original_bytes = config_path.read_bytes()

    # Simulate a crash inside os.replace — the tmp must exist with new content
    # but the real file must keep its old content.
    def boom(src, dst):
        raise RuntimeError("simulated power loss")

    monkeypatch.setattr("os.replace", boom)

    updated = store.load()
    updated.policy.confirm_timeout_s = 99
    with pytest.raises(RuntimeError, match="simulated power loss"):
        store.write(updated)

    assert config_path.read_bytes() == original_bytes


def test_malformed_yaml_raises_config_error(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("policy: : :\n  not yaml\n")
    store = ConfigStore(path)
    with pytest.raises(ConfigError):
        store.load()


def test_unknown_top_level_key_raises_config_error(tmp_path: Path):
    """Pydantic extra='forbid' must catch typos so we don't silently drop them."""
    path = tmp_path / "config.yaml"
    path.write_text("version: 1\nbogus_key: 42\n")
    store = ConfigStore(path)
    with pytest.raises(ConfigError):
        store.load()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_store.py -v`
Expected: all six tests fail with `ModuleNotFoundError: androidharness.web.store`.

- [ ] **Step 4: Implement `ConfigStore`**

Create `androidharness/web/store.py`:

```python
"""Atomic load + write for ~/.androidharness/config.yaml.

The Settings UI reads via load() on every request (the file is small) and
writes via write(cfg) which serializes to a sibling .tmp file then atomically
replaces the real file. On any failure the original file is left intact.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from androidharness.config import (
    CONFIG_HEADER,
    AndroidHarnessConfig,
    ConfigError,
    load_config,
)


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> AndroidHarnessConfig:
        return load_config(self.path)

    def write(self, cfg: AndroidHarnessConfig) -> AndroidHarnessConfig:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = yaml.safe_dump(
            cfg.model_dump(mode="json"),
            sort_keys=False,
            default_flow_style=False,
        )
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(CONFIG_HEADER + body)
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return cfg


__all__ = ["ConfigStore", "ConfigError"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_store.py -v`
Expected: all six tests pass.

- [ ] **Step 6: Commit**

```bash
git add androidharness/web/__init__.py androidharness/web/store.py tests/web/__init__.py tests/web/test_store.py
git commit -m "feat(web): ConfigStore — atomic load/write of config.yaml"
```

---

## Task 3: `ProviderSecrets` — pydantic-settings env layer

**Files:**
- Create: `androidharness/web/secrets.py`
- Test: `tests/web/test_secrets.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_secrets.py`:

```python
from __future__ import annotations

import pytest

from androidharness.web.secrets import ProviderSecrets


def test_is_set_true_when_env_var_present(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MY_FAKE_KEY", "x")
    assert ProviderSecrets.is_set("MY_FAKE_KEY") is True


def test_is_set_false_when_env_var_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MY_FAKE_KEY", raising=False)
    assert ProviderSecrets.is_set("MY_FAKE_KEY") is False


def test_is_set_false_when_env_var_empty(monkeypatch: pytest.MonkeyPatch):
    """Empty string is treated as unset — the agent won't be able to auth either way."""
    monkeypatch.setenv("MY_FAKE_KEY", "")
    assert ProviderSecrets.is_set("MY_FAKE_KEY") is False


def test_get_returns_value_when_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MY_FAKE_KEY", "sekret")
    assert ProviderSecrets.get("MY_FAKE_KEY") == "sekret"


def test_get_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MY_FAKE_KEY", raising=False)
    assert ProviderSecrets.get("MY_FAKE_KEY") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_secrets.py -v`
Expected: all five tests fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `ProviderSecrets`**

Create `androidharness/web/secrets.py`:

```python
"""Env-var lookups for provider API keys.

Keys are never persisted to config.yaml — only their env-var *names* are.
This module is the single place the UI checks whether a referenced key is
actually present in the running environment.

pydantic-settings is overkill for `os.environ.get` alone, but using it here
makes the env layer explicit and gives us a single hook to extend later
(secret managers, .env files, etc.).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSecrets(BaseSettings):
    """Reads from the process environment. Extends to .env/secret managers later."""

    model_config = SettingsConfigDict(extra="allow")

    @classmethod
    def is_set(cls, env_var_name: str) -> bool:
        value = cls.get(env_var_name)
        return bool(value)

    @classmethod
    def get(cls, env_var_name: str) -> str | None:
        # Construct fresh each call so we always reflect the current environment.
        instance = cls()
        return instance.model_dump().get(env_var_name) or None


__all__ = ["ProviderSecrets"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_secrets.py -v`
Expected: all five pass.

- [ ] **Step 5: Commit**

```bash
git add androidharness/web/secrets.py tests/web/test_secrets.py
git commit -m "feat(web): ProviderSecrets — pydantic-settings env layer for api_key_env names"
```

---

## Task 4: `list_adb_devices` wrapper

**Files:**
- Create: `androidharness/web/devices.py`
- Test: `tests/web/test_devices.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_devices.py`:

```python
from __future__ import annotations

import subprocess

import pytest

from androidharness.device import DeviceInfo
from androidharness.web.devices import list_adb_devices


def test_list_adb_devices_delegates_to_device_module(monkeypatch: pytest.MonkeyPatch):
    fake = [DeviceInfo(serial="ABC123", model="Pixel 9")]
    monkeypatch.setattr("androidharness.web.devices.list_devices", lambda: fake)
    assert list_adb_devices() == fake


def test_list_adb_devices_swallows_adb_failure_and_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
):
    """adb might not be installed on the box running the UI — UI must still load."""

    def boom():
        raise subprocess.CalledProcessError(1, ["adb"])

    monkeypatch.setattr("androidharness.web.devices.list_devices", boom)
    assert list_adb_devices() == []


def test_list_adb_devices_swallows_subprocess_error(monkeypatch: pytest.MonkeyPatch):
    def boom():
        raise FileNotFoundError("adb not found")

    monkeypatch.setattr("androidharness.web.devices.list_devices", boom)
    assert list_adb_devices() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_devices.py -v`
Expected: fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the wrapper**

Create `androidharness/web/devices.py`:

```python
"""Wrap androidharness.device.list_devices for the Settings UI.

Returns an empty list on any adb failure so the Devices panel still renders
when adb is missing or no devices are connected.
"""

from __future__ import annotations

import subprocess

from androidharness.device import DeviceInfo, list_devices


def list_adb_devices() -> list[DeviceInfo]:
    try:
        return list_devices()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []


__all__ = ["list_adb_devices"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_devices.py -v`
Expected: all three pass.

- [ ] **Step 5: Commit**

```bash
git add androidharness/web/devices.py tests/web/test_devices.py
git commit -m "feat(web): list_adb_devices wrapper that fails closed to []"
```

---

## Task 5: `unflatten` form helper

**Files:**
- Create: `androidharness/web/forms.py`
- Test: `tests/web/test_forms.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_forms.py`:

```python
from __future__ import annotations

import pytest

from androidharness.web.forms import FormError, unflatten


def test_unflatten_passes_through_simple_keys():
    assert unflatten({"a": "1", "b": "2"}) == {"a": "1", "b": "2"}


def test_unflatten_nests_dotted_keys():
    assert unflatten({"policy.default_mode": "confirm"}) == {
        "policy": {"default_mode": "confirm"}
    }


def test_unflatten_nests_two_deep():
    assert unflatten({"providers.entries.gemini.api_key_env": "GEMINI_API_KEY"}) == {
        "providers": {"entries": {"gemini": {"api_key_env": "GEMINI_API_KEY"}}}
    }


def test_unflatten_merges_sibling_paths():
    flat = {
        "policy.default_mode": "confirm",
        "policy.confirm_timeout_s": "30",
    }
    assert unflatten(flat) == {
        "policy": {"default_mode": "confirm", "confirm_timeout_s": "30"}
    }


def test_unflatten_rejects_value_then_dict_collision():
    """Cannot have both `a` and `a.b` in the same form."""
    with pytest.raises(FormError):
        unflatten({"a": "1", "a.b": "2"})


def test_unflatten_drops_empty_string_values():
    """Empty form fields collapse to absence so Pydantic defaults apply."""
    assert unflatten({"defaults.device_serial": ""}) == {"defaults": {}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_forms.py -v`
Expected: six failures, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `unflatten`**

Create `androidharness/web/forms.py`:

```python
"""Form helpers.

HTML forms can't natively post nested JSON. We use dotted keys
(`policy.default_mode`) and un-flatten them server-side before handing to
Pydantic for validation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FormError(ValueError):
    """Raised when a posted form is structurally inconsistent (e.g., key collision)."""


def unflatten(flat: Mapping[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in flat.items():
        if value == "":
            continue
        parts = key.split(".")
        node: dict[str, Any] = out
        for part in parts[:-1]:
            existing = node.get(part)
            if existing is None:
                existing = {}
                node[part] = existing
            elif not isinstance(existing, dict):
                raise FormError(
                    f"form key collision: {part!r} is both a leaf and a parent (key={key!r})"
                )
            node = existing
        leaf = parts[-1]
        if isinstance(node.get(leaf), dict):
            raise FormError(
                f"form key collision: {leaf!r} cannot be both a value and a parent"
            )
        node[leaf] = value
    return out


__all__ = ["FormError", "unflatten"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_forms.py -v`
Expected: all six pass.

- [ ] **Step 5: Commit**

```bash
git add androidharness/web/forms.py tests/web/test_forms.py
git commit -m "feat(web): unflatten helper for dotted-key HTML form bodies"
```

---

## Task 6: `create_app` skeleton + base template + sidebar + GET `/`

This task wires the FastAPI app, the Jinja templates, the static mount, and the GET `/` route. **No panel handlers yet** — those land in Tasks 7–13. The default panel ("providers") is pre-rendered with a "Coming soon" placeholder so the index page works end-to-end.

**Files:**
- Create: `androidharness/web/app.py`
- Create: `androidharness/web/routes.py`
- Create: `androidharness/web/templates/base.html`
- Create: `androidharness/web/templates/index.html`
- Create: `androidharness/web/templates/_providers.html` (placeholder body, fleshed out in Task 13)
- Create: `androidharness/web/static/styles.css`
- Test: `tests/web/test_app.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_app.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_app.py -v`
Expected: failures — `androidharness.web.app` doesn't exist yet.

- [ ] **Step 3: Implement `create_app` and the routes module**

Create `androidharness/web/app.py`:

```python
"""FastAPI app factory.

`create_app(config_path)` returns a fully wired app: templates, static mount,
ConfigStore on `app.state`, and all panel routes registered. Tests build a
fresh app per test with a tmp_path config file.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from androidharness.web.routes import register_routes
from androidharness.web.store import ConfigStore

_THIS_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_THIS_DIR / "templates"))


def create_app(config_path: Path) -> FastAPI:
    app = FastAPI(title="AndroidHarness — Settings UI")
    app.state.store = ConfigStore(Path(config_path))
    app.state.templates = _TEMPLATES
    app.mount("/static", StaticFiles(directory=str(_THIS_DIR / "static")), name="static")
    register_routes(app)
    return app


__all__ = ["create_app"]
```

Create `androidharness/web/routes.py`:

```python
"""Settings UI route handlers.

Each panel exposes:
  * GET  /panel/<name>          — render the panel partial
  * PATCH /config/<section>     — validate, atomic-write, re-render

`name` and `section` are validated against an allowlist; unknown values 404.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

# Allowlist of panel names. Each entry maps the URL name → template partial.
PANELS: dict[str, str] = {
    "providers": "_providers.html",
    "models": "_models.html",
    "throttler": "_throttler.html",
    "policy": "_policy.html",
    "devices": "_devices.html",
    "logging": "_logging.html",
    "general": "_general.html",
}


def _render_panel(
    request: Request,
    name: str,
    *,
    banner: str | None = None,
    banner_kind: str = "ok",
    errors: dict[str, str] | None = None,
    overrides: dict[str, str] | None = None,
):
    """Render the panel partial against the current config."""
    templates = request.app.state.templates
    store = request.app.state.store
    cfg = store.load()
    return templates.TemplateResponse(
        request,
        PANELS[name],
        {
            "cfg": cfg,
            "panel": name,
            "banner": banner,
            "banner_kind": banner_kind,
            "errors": errors or {},
            "overrides": overrides or {},
        },
    )


def register_routes(app: FastAPI) -> None:
    templates = app.state.templates

    @app.get("/")
    def index(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "cfg": request.app.state.store.load(),
                "panels": list(PANELS.keys()),
                "active": "providers",
            },
        )

    @app.get("/panel/{name}")
    def get_panel(name: str, request: Request):
        if name not in PANELS:
            raise HTTPException(status_code=404, detail=f"unknown panel: {name}")
        return _render_panel(request, name)

    @app.patch("/config/{section}")
    def patch_config(section: str, request: Request):
        if section not in PANELS:
            raise HTTPException(status_code=404, detail=f"unknown section: {section}")
        # Panel-specific handlers register themselves below this point;
        # 404 stays in effect until a handler claims the section.
        raise HTTPException(status_code=405, detail=f"PATCH not yet wired for {section}")


__all__ = ["register_routes", "PANELS"]
```

Create `androidharness/web/templates/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AndroidHarness — Settings</title>
<link rel="stylesheet" href="/static/styles.css">
<script src="https://unpkg.com/htmx.org@2.0.3" integrity="sha384-0895/pl2MU10Hqc6jd4RvrAumzVZCmcg6KQfbF3vBb5UfNQHZ7yyq8eD7m5rmwTl3" crossorigin="anonymous"></script>
</head>
<body>
<aside class="sidebar">
  <h1>AndroidHarness</h1>
  <nav>
    {% for p in panels %}
      <a href="/" hx-get="/panel/{{ p }}" hx-target="#panel" hx-swap="innerHTML"
         class="nav-link {% if p == active %}active{% endif %}">
        {{ p|capitalize }}
      </a>
    {% endfor %}
  </nav>
</aside>
<main id="panel">
  {% block panel %}{% endblock %}
</main>
</body>
</html>
```

Create `androidharness/web/templates/index.html`:

```html
{% extends "base.html" %}
{% block panel %}
  {% include "_" ~ active ~ ".html" %}
{% endblock %}
```

Create `androidharness/web/templates/_providers.html` (placeholder, Task 13 fleshes it out):

```html
<section class="panel">
  <h2>Providers</h2>
  {% if banner %}<div class="banner banner-{{ banner_kind }}">{{ banner }}</div>{% endif %}
  <p class="placeholder">Provider editing lands in the Providers panel task.</p>
</section>
```

Create `androidharness/web/static/styles.css`:

```css
:root {
  --bg: #fafafa;
  --fg: #1a1a1a;
  --muted: #666;
  --border: #ddd;
  --accent: #2563eb;
  --ok: #16a34a;
  --err: #dc2626;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--fg); }
body { display: grid; grid-template-columns: 220px 1fr; min-height: 100vh; }
.sidebar { background: #fff; border-right: 1px solid var(--border); padding: 16px; }
.sidebar h1 { font-size: 14px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin: 0 0 16px 0; }
.sidebar nav { display: flex; flex-direction: column; gap: 4px; }
.nav-link { display: block; padding: 8px 12px; border-radius: 6px; color: var(--fg); text-decoration: none; }
.nav-link:hover { background: #f0f0f0; }
.nav-link.active { background: var(--accent); color: white; }
main { padding: 24px 32px; }
.panel h2 { margin: 0 0 16px 0; }
.banner { padding: 10px 12px; border-radius: 6px; margin-bottom: 16px; }
.banner-ok { background: #ecfdf5; color: var(--ok); border: 1px solid var(--ok); }
.banner-err { background: #fef2f2; color: var(--err); border: 1px solid var(--err); }
form .field { margin-bottom: 14px; }
form label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 4px; }
form input, form select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 4px; min-width: 280px; font: inherit; }
form .err { display: block; color: var(--err); font-size: 12px; margin-top: 4px; }
form button { background: var(--accent); color: white; border: 0; padding: 8px 14px; border-radius: 6px; font: inherit; cursor: pointer; }
form button:hover { filter: brightness(1.08); }
.placeholder { color: var(--muted); font-style: italic; }
.badge { display: inline-block; padding: 2px 6px; border-radius: 999px; font-size: 11px; margin-left: 6px; }
.badge-set { background: #ecfdf5; color: var(--ok); }
.badge-missing { background: #fef2f2; color: var(--err); }
table { border-collapse: collapse; width: 100%; }
th, td { border-bottom: 1px solid var(--border); padding: 8px 6px; text-align: left; }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_app.py -v`
Expected: all six pass.

- [ ] **Step 5: Commit**

```bash
git add androidharness/web/app.py androidharness/web/routes.py \
        androidharness/web/templates/base.html \
        androidharness/web/templates/index.html \
        androidharness/web/templates/_providers.html \
        androidharness/web/static/styles.css \
        tests/web/test_app.py
git commit -m "feat(web): FastAPI app skeleton + base template + sidebar + GET /"
```

---

## Task 7: `serve` CLI command (lazy import + missing-extra error path)

**Files:**
- Modify: `androidharness/cli.py`
- Test: `tests/test_cli_serve.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cli_serve.py`:

```python
from __future__ import annotations

import subprocess
import sys
import textwrap

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
    assert "[web]" in result.stdout
    assert "pip install" in result.stdout or "uv add" in result.stdout


def test_serve_reraises_unrelated_import_errors(monkeypatch):
    """A genuine bug (e.g., syntax error in web/) must not be swallowed."""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "androidharness.web":
            raise ModuleNotFoundError("No module named 'totally_unrelated_thing'", name="totally_unrelated_thing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    runner = CliRunner()
    result = runner.invoke(app, ["serve"])
    # Either the CLI re-raises (exception in result.exception) or exits non-zero with the unrelated name.
    assert result.exit_code != 0
    output = (result.stdout or "") + (str(result.exception) if result.exception else "")
    assert "totally_unrelated_thing" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_serve.py -v`
Expected: three failures — no `serve` command exists.

- [ ] **Step 3: Add the `serve` command**

In `androidharness/cli.py`, add this command at the bottom of the file (before any `if __name__ == "__main__"`):

```python
# Set of pip-package names provided by the [web] optional extra.
# Used to tell "missing extra" apart from a real bug in androidharness/web/.
_WEB_EXTRA_PACKAGES = {
    "fastapi",
    "uvicorn",
    "jinja2",
    "multipart",  # python-multipart imports as `multipart`
    "pydantic_settings",
}


@app.command("serve")
def serve_cmd(
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind. Leave on 127.0.0.1 (no auth)."),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml. Defaults to $ANDROIDHARNESS_CONFIG or ~/.androidharness/config.yaml.",
    ),
) -> None:
    """Run the Settings UI (browser-based config editor)."""
    try:
        from androidharness.web import create_app  # lazy: requires [web] extra
    except ModuleNotFoundError as e:
        if e.name in _WEB_EXTRA_PACKAGES:
            typer.echo(
                "the `serve` command needs the optional [web] extra:\n"
                "    uv add 'androidharness[web]'\n"
                "    # or: pip install 'androidharness[web]'",
                err=True,
            )
            raise typer.Exit(code=1) from e
        raise

    try:
        import uvicorn
    except ModuleNotFoundError as e:
        typer.echo(
            "the `serve` command needs the optional [web] extra (uvicorn missing):\n"
            "    uv add 'androidharness[web]'",
            err=True,
        )
        raise typer.Exit(code=1) from e

    config_path = _resolve_config_path(config)
    app_obj = create_app(config_path)
    typer.echo(f"AndroidHarness Settings UI — editing {config_path}")
    typer.echo(f"open: http://{host}:{port}/")
    uvicorn.run(app_obj, host=host, port=port, log_level="info")
```

Add to the imports at the top of `cli.py` if not already present:

```python
from pathlib import Path  # likely already imported
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_serve.py -v`
Expected: all three pass. Note: the second test asserts the friendly error path is hit; the third test asserts unrelated import errors are NOT swallowed.

- [ ] **Step 5: Manually confirm `--help` shows the new command**

Run: `uv run androidharness --help`
Expected: output includes `serve` in the commands list.

Run: `uv run androidharness serve --help`
Expected: usage line with `--port`, `--host`, `--config` options.

- [ ] **Step 6: Commit**

```bash
git add androidharness/cli.py tests/test_cli_serve.py
git commit -m "feat(cli): androidharness serve — lazy import of [web] extra"
```

---

## Task 8: General panel (`cfg.defaults` minus `device_serial`)

The General panel edits `cfg.defaults`'s catch-all fields: `model`, `max_turns`, `wall_clock_s`, `runs_dir`, `logs_dir`. The `device_serial` field is owned by the Devices panel (Task 10).

**Files:**
- Modify: `androidharness/web/routes.py`
- Create: `androidharness/web/templates/_general.html`
- Test: `tests/web/test_routes_general.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_routes_general.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_general_renders_current_defaults(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/panel/general")
    assert resp.status_code == 200
    body = resp.text
    assert "max_turns" in body
    assert "40" in body  # the default
    assert "gemini-2.5-flash" in body


def test_patch_config_general_valid_writes_and_returns_success(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/general",
        data={
            "model": "gemini-2.5-pro",
            "max_turns": "20",
            "wall_clock_s": "300",
            "runs_dir": "./runs",
            "logs_dir": "./logs",
        },
    )
    assert resp.status_code == 200
    assert "saved" in resp.text.lower() or "banner-ok" in resp.text

    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.defaults.model == "gemini-2.5-pro"
    assert reloaded.defaults.max_turns == 20


def test_patch_config_general_invalid_does_not_write_and_shows_field_error(
    tmp_path: Path,
):
    client, cfg_path = _client(tmp_path)
    # max_turns must be > 0
    resp = client.patch(
        "/config/general",
        data={
            "model": "gemini-2.5-pro",
            "max_turns": "0",
            "wall_clock_s": "300",
            "runs_dir": "./runs",
            "logs_dir": "./logs",
        },
    )
    assert resp.status_code == 200  # 200 with error markup, not 4xx — HTMX swaps the body
    assert "banner-err" in resp.text
    assert "max_turns" in resp.text

    # File untouched (or never created)
    if cfg_path.exists():
        reloaded = ConfigStore(cfg_path).load()
        assert reloaded.defaults.max_turns == 40
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_routes_general.py -v`
Expected: failures — template doesn't exist and PATCH handler returns 405.

- [ ] **Step 3: Implement the panel template**

Create `androidharness/web/templates/_general.html`:

```html
<section class="panel">
  <h2>General defaults</h2>
  {% if banner %}<div class="banner banner-{{ banner_kind }}">{{ banner }}</div>{% endif %}
  <form hx-patch="/config/general" hx-target="#panel" hx-swap="innerHTML">
    <div class="field">
      <label for="model">Default model</label>
      <input id="model" name="model" value="{{ overrides.get('model', cfg.defaults.model) }}">
      {% if errors.get('model') %}<span class="err">{{ errors['model'] }}</span>{% endif %}
    </div>
    <div class="field">
      <label for="max_turns">Max turns per run</label>
      <input id="max_turns" name="max_turns" type="number" min="1"
             value="{{ overrides.get('max_turns', cfg.defaults.max_turns) }}">
      {% if errors.get('max_turns') %}<span class="err">{{ errors['max_turns'] }}</span>{% endif %}
    </div>
    <div class="field">
      <label for="wall_clock_s">Wall-clock cap (seconds)</label>
      <input id="wall_clock_s" name="wall_clock_s" type="number" step="any" min="0.001"
             value="{{ overrides.get('wall_clock_s', cfg.defaults.wall_clock_s) }}">
      {% if errors.get('wall_clock_s') %}<span class="err">{{ errors['wall_clock_s'] }}</span>{% endif %}
    </div>
    <div class="field">
      <label for="runs_dir">Runs directory</label>
      <input id="runs_dir" name="runs_dir" value="{{ overrides.get('runs_dir', cfg.defaults.runs_dir) }}">
      {% if errors.get('runs_dir') %}<span class="err">{{ errors['runs_dir'] }}</span>{% endif %}
    </div>
    <div class="field">
      <label for="logs_dir">Logs directory</label>
      <input id="logs_dir" name="logs_dir" value="{{ overrides.get('logs_dir', cfg.defaults.logs_dir) }}">
      {% if errors.get('logs_dir') %}<span class="err">{{ errors['logs_dir'] }}</span>{% endif %}
    </div>
    <button type="submit">Save</button>
  </form>
</section>
```

- [ ] **Step 4: Add the PATCH handler to `routes.py`**

Add this helper to `androidharness/web/routes.py` (between the imports and `PANELS`):

```python
from pydantic import ValidationError

from androidharness.config import AndroidHarnessConfig
from androidharness.web.forms import FormError, unflatten
```

Replace the `patch_config` handler in `register_routes` with the dispatching version below, and add the General-specific handler:

```python
def _validate_full(cfg_dump: dict) -> AndroidHarnessConfig:
    """Round-trip through AndroidHarnessConfig so cross-section invariants run."""
    return AndroidHarnessConfig.model_validate(cfg_dump)


def _pydantic_errors_to_dict(e: ValidationError) -> dict[str, str]:
    out: dict[str, str] = {}
    for err in e.errors():
        path = ".".join(str(p) for p in err["loc"])
        out[path] = err["msg"]
    return out


def _apply_section_and_write(
    request: Request,
    name: str,
    section_path: list[str],
    submitted: dict,
):
    """Merge `submitted` into the config at `section_path`, validate, write."""
    store = request.app.state.store
    cfg = store.load()
    cfg_dump = cfg.model_dump(mode="python")
    node = cfg_dump
    for part in section_path[:-1]:
        node = node.setdefault(part, {})
    last = section_path[-1] if section_path else None
    if last is None:
        # Section IS the whole config (not used today, but supported).
        cfg_dump.update(submitted)
    else:
        existing = node.get(last, {})
        if isinstance(existing, dict):
            merged = {**existing, **submitted}
        else:
            merged = submitted
        node[last] = merged
    try:
        new_cfg = _validate_full(cfg_dump)
    except ValidationError as e:
        errors = _pydantic_errors_to_dict(e)
        flat_overrides = {k: str(v) for k, v in submitted.items()}
        return _render_panel(
            request,
            name,
            banner="Could not save — see field errors below.",
            banner_kind="err",
            errors=errors,
            overrides=flat_overrides,
        )
    store.write(new_cfg)
    return _render_panel(request, name, banner="Saved.", banner_kind="ok")
```

Replace `patch_config` with:

```python
    @app.patch("/config/{section}")
    async def patch_config(section: str, request: Request):
        if section not in PANELS:
            raise HTTPException(status_code=404, detail=f"unknown section: {section}")
        form = await request.form()
        try:
            submitted = unflatten({k: str(v) for k, v in form.items()})
        except FormError as e:
            return _render_panel(
                request, section, banner=str(e), banner_kind="err",
                overrides={k: str(v) for k, v in form.items()},
            )

        if section == "general":
            # All fields land directly on cfg.defaults (device_serial is owned by Devices).
            return _apply_section_and_write(
                request, "general", ["defaults"], submitted,
            )
        raise HTTPException(status_code=405, detail=f"PATCH not yet wired for {section}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_routes_general.py -v`
Expected: all three pass.

Also re-run the app-level tests to confirm nothing regressed:

Run: `uv run pytest tests/web/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add androidharness/web/routes.py androidharness/web/templates/_general.html tests/web/test_routes_general.py
git commit -m "feat(web): General panel — edit cfg.defaults via /panel/general + PATCH /config/general"
```

---

## Task 9: Logging panel

**Files:**
- Modify: `androidharness/web/routes.py`
- Create: `androidharness/web/templates/_logging.html`
- Test: `tests/web/test_routes_logging.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_routes_logging.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_logging_renders_current_values(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/panel/logging")
    assert resp.status_code == 200
    body = resp.text
    assert "INFO" in body  # default level
    assert "10" in body    # default rotation_mb


def test_patch_config_logging_valid_writes(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/logging",
        data={"level": "DEBUG", "rotation_mb": "25"},
    )
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.logging.level == "DEBUG"
    assert reloaded.logging.rotation_mb == 25


def test_patch_config_logging_invalid_does_not_write(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/logging",
        data={"level": "DEBUG", "rotation_mb": "0"},  # must be > 0
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
    if cfg_path.exists():
        reloaded = ConfigStore(cfg_path).load()
        assert reloaded.logging.rotation_mb == 10


def test_patch_config_logging_rejects_unknown_level(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.patch(
        "/config/logging",
        data={"level": "TRACE", "rotation_mb": "10"},  # not in LogLevel literal
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
    assert "level" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_routes_logging.py -v`
Expected: four failures — template doesn't exist, handler is 405.

- [ ] **Step 3: Implement the panel template**

Create `androidharness/web/templates/_logging.html`:

```html
<section class="panel">
  <h2>Logging</h2>
  {% if banner %}<div class="banner banner-{{ banner_kind }}">{{ banner }}</div>{% endif %}
  <form hx-patch="/config/logging" hx-target="#panel" hx-swap="innerHTML">
    <div class="field">
      <label for="level">Log level</label>
      <select id="level" name="level">
        {% set current_level = overrides.get('level', cfg.logging.level) %}
        {% for lvl in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] %}
          <option value="{{ lvl }}" {% if lvl == current_level %}selected{% endif %}>{{ lvl }}</option>
        {% endfor %}
      </select>
      {% if errors.get('level') %}<span class="err">{{ errors['level'] }}</span>{% endif %}
    </div>
    <div class="field">
      <label for="rotation_mb">Rotation size (MB per file)</label>
      <input id="rotation_mb" name="rotation_mb" type="number" min="1"
             value="{{ overrides.get('rotation_mb', cfg.logging.rotation_mb) }}">
      {% if errors.get('rotation_mb') %}<span class="err">{{ errors['rotation_mb'] }}</span>{% endif %}
    </div>
    <button type="submit">Save</button>
  </form>
</section>
```

- [ ] **Step 4: Add the dispatch arm to `routes.py`**

In `register_routes`, extend the `patch_config` handler with a `logging` branch:

```python
        if section == "general":
            return _apply_section_and_write(request, "general", ["defaults"], submitted)
        if section == "logging":
            return _apply_section_and_write(request, "logging", ["logging"], submitted)
        raise HTTPException(status_code=405, detail=f"PATCH not yet wired for {section}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_routes_logging.py -v`
Expected: all four pass.

Run: `uv run pytest tests/web/ -v`
Expected: still all green.

- [ ] **Step 6: Commit**

```bash
git add androidharness/web/routes.py androidharness/web/templates/_logging.html tests/web/test_routes_logging.py
git commit -m "feat(web): Logging panel — edit cfg.logging via /panel/logging"
```

---

## Task 10: Devices panel

The Devices panel renders the live `adb devices` list plus a dropdown to pick the default. It edits `cfg.defaults.device_serial`.

**Files:**
- Modify: `androidharness/web/routes.py`
- Create: `androidharness/web/templates/_devices.html`
- Test: `tests/web/test_routes_devices.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_routes_devices.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from androidharness.device import DeviceInfo
from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_devices_lists_live_adb_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "androidharness.web.routes.list_adb_devices",
        lambda: [DeviceInfo(serial="ABC123", model="Pixel 9")],
    )
    client, _ = _client(tmp_path)
    resp = client.get("/panel/devices")
    assert resp.status_code == 200
    assert "ABC123" in resp.text
    assert "Pixel 9" in resp.text


def test_get_panel_devices_handles_no_devices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("androidharness.web.routes.list_adb_devices", lambda: [])
    client, _ = _client(tmp_path)
    resp = client.get("/panel/devices")
    assert resp.status_code == 200
    assert "no devices" in resp.text.lower()


def test_patch_config_devices_sets_default_serial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "androidharness.web.routes.list_adb_devices",
        lambda: [DeviceInfo(serial="ABC123", model="Pixel 9")],
    )
    client, cfg_path = _client(tmp_path)
    resp = client.patch("/config/devices", data={"device_serial": "ABC123"})
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.defaults.device_serial == "ABC123"


def test_patch_config_devices_empty_clears_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("androidharness.web.routes.list_adb_devices", lambda: [])
    client, cfg_path = _client(tmp_path)
    # Pre-seed a default
    pre = ConfigStore(cfg_path).load()
    pre.defaults.device_serial = "OLD"
    ConfigStore(cfg_path).write(pre)

    resp = client.patch("/config/devices", data={"device_serial": ""})
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.defaults.device_serial is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_routes_devices.py -v`
Expected: four failures.

- [ ] **Step 3: Implement the panel template**

Create `androidharness/web/templates/_devices.html`:

```html
<section class="panel">
  <h2>Devices</h2>
  {% if banner %}<div class="banner banner-{{ banner_kind }}">{{ banner }}</div>{% endif %}

  {% if devices %}
    <table>
      <thead><tr><th>Serial</th><th>Model</th></tr></thead>
      <tbody>
        {% for d in devices %}
          <tr><td>{{ d.serial }}</td><td>{{ d.model }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p class="placeholder">No devices found. Make sure adb is installed and a device is connected.</p>
  {% endif %}

  <form hx-patch="/config/devices" hx-target="#panel" hx-swap="innerHTML" style="margin-top: 16px;">
    <div class="field">
      <label for="device_serial">Default device</label>
      <select id="device_serial" name="device_serial">
        {% set current = overrides.get('device_serial', cfg.defaults.device_serial) %}
        <option value="" {% if not current %}selected{% endif %}>— none —</option>
        {% for d in devices %}
          <option value="{{ d.serial }}" {% if d.serial == current %}selected{% endif %}>
            {{ d.serial }} ({{ d.model }})
          </option>
        {% endfor %}
      </select>
      {% if errors.get('device_serial') %}<span class="err">{{ errors['device_serial'] }}</span>{% endif %}
    </div>
    <button type="submit">Save</button>
  </form>
</section>
```

- [ ] **Step 4: Update `_render_panel` to inject device list when needed**

In `androidharness/web/routes.py`, import the devices wrapper:

```python
from androidharness.web.devices import list_adb_devices
```

Extend `_render_panel` to inject `devices` into the template context when the panel is `"devices"`:

```python
def _render_panel(
    request: Request,
    name: str,
    *,
    banner: str | None = None,
    banner_kind: str = "ok",
    errors: dict[str, str] | None = None,
    overrides: dict[str, str] | None = None,
):
    templates = request.app.state.templates
    store = request.app.state.store
    cfg = store.load()
    extra: dict = {}
    if name == "devices":
        extra["devices"] = list_adb_devices()
    return templates.TemplateResponse(
        request,
        PANELS[name],
        {
            "cfg": cfg,
            "panel": name,
            "banner": banner,
            "banner_kind": banner_kind,
            "errors": errors or {},
            "overrides": overrides or {},
            **extra,
        },
    )
```

Add the `devices` arm to `patch_config`:

```python
        if section == "devices":
            return _apply_section_and_write(
                request, "devices", ["defaults"],
                {"device_serial": submitted.get("device_serial") or None},
            )
```

(The `or None` collapses empty string → `None` so the Pydantic field can be cleared.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_routes_devices.py -v`
Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add androidharness/web/routes.py androidharness/web/templates/_devices.html tests/web/test_routes_devices.py
git commit -m "feat(web): Devices panel — live adb list + edit cfg.defaults.device_serial"
```

---

## Task 11: Policy panel

**Files:**
- Modify: `androidharness/web/routes.py`
- Create: `androidharness/web/templates/_policy.html`
- Test: `tests/web/test_routes_policy.py`

The Policy panel has three pieces: `default_mode` (one of four modes), `confirm_timeout_s`, and a per-tool override grid keyed by tool name. We fix the per-tool tool list to the tools that exist today (`tap`, `long_press`, `type`, `swipe`, `scroll`, `press_key`, `wait`, `show_screen`, `open_notifications`, `close_notifications`, `done`).

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_routes_policy.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_policy_renders_default_mode_and_timeout(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/panel/policy")
    assert resp.status_code == 200
    body = resp.text
    assert "default_mode" in body
    assert "confirm_timeout_s" in body
    # The spec-mandated confirm defaults must show up.
    assert "per_tool.type" in body
    assert "per_tool.long_press" in body


def test_patch_config_policy_valid_writes(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/policy",
        data={
            "default_mode": "confirm",
            "confirm_timeout_s": "15",
            "per_tool.tap": "auto",
            "per_tool.type": "deny",
            "per_tool.long_press": "confirm",
        },
    )
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.policy.default_mode == "confirm"
    assert reloaded.policy.confirm_timeout_s == 15
    assert reloaded.policy.per_tool["type"] == "deny"


def test_patch_config_policy_invalid_timeout_does_not_write(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/policy",
        data={
            "default_mode": "auto",
            "confirm_timeout_s": "0",  # must be > 0
            "per_tool.type": "confirm",
        },
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
    if cfg_path.exists():
        reloaded = ConfigStore(cfg_path).load()
        assert reloaded.policy.confirm_timeout_s == 30


def test_patch_config_policy_invalid_mode_does_not_write(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.patch(
        "/config/policy",
        data={
            "default_mode": "bogus",
            "confirm_timeout_s": "30",
            "per_tool.type": "confirm",
        },
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_routes_policy.py -v`
Expected: four failures.

- [ ] **Step 3: Implement the panel template**

Create `androidharness/web/templates/_policy.html`:

```html
<section class="panel">
  <h2>Policy</h2>
  {% if banner %}<div class="banner banner-{{ banner_kind }}">{{ banner }}</div>{% endif %}

  {% set modes = ['auto', 'confirm', 'dry-run', 'deny'] %}
  {% set tools = [
    'tap', 'long_press', 'type', 'swipe', 'scroll',
    'press_key', 'wait', 'show_screen',
    'open_notifications', 'close_notifications', 'done',
  ] %}

  <form hx-patch="/config/policy" hx-target="#panel" hx-swap="innerHTML">
    <div class="field">
      <label for="default_mode">Default mode (applies to any tool not listed below)</label>
      <select id="default_mode" name="default_mode">
        {% set current = overrides.get('default_mode', cfg.policy.default_mode) %}
        {% for m in modes %}
          <option value="{{ m }}" {% if m == current %}selected{% endif %}>{{ m }}</option>
        {% endfor %}
      </select>
      {% if errors.get('default_mode') %}<span class="err">{{ errors['default_mode'] }}</span>{% endif %}
    </div>

    <div class="field">
      <label for="confirm_timeout_s">Confirm timeout (seconds — auto-rejects on expiry)</label>
      <input id="confirm_timeout_s" name="confirm_timeout_s" type="number" min="1"
             value="{{ overrides.get('confirm_timeout_s', cfg.policy.confirm_timeout_s) }}">
      {% if errors.get('confirm_timeout_s') %}<span class="err">{{ errors['confirm_timeout_s'] }}</span>{% endif %}
    </div>

    <h3 style="margin-top: 24px;">Per-tool override</h3>
    <table>
      <thead><tr><th>Tool</th><th>Mode</th></tr></thead>
      <tbody>
        {% for t in tools %}
          {% set tool_key = 'per_tool.' ~ t %}
          {% set current = overrides.get(tool_key, cfg.policy.per_tool.get(t, '')) %}
          <tr>
            <td><code>{{ t }}</code></td>
            <td>
              <select name="{{ tool_key }}">
                <option value="" {% if not current %}selected{% endif %}>— use default —</option>
                {% for m in modes %}
                  <option value="{{ m }}" {% if m == current %}selected{% endif %}>{{ m }}</option>
                {% endfor %}
              </select>
              {% if errors.get(tool_key) %}<span class="err">{{ errors[tool_key] }}</span>{% endif %}
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>

    <button type="submit" style="margin-top: 16px;">Save</button>
  </form>
</section>
```

- [ ] **Step 4: Add the dispatch arm to `routes.py`**

The Policy section has nested `per_tool.*` keys. After `unflatten`, the submitted dict already has the right shape (`{"default_mode": ..., "confirm_timeout_s": ..., "per_tool": {...}}`). We then have to **replace** `per_tool` (not merge) so that omitted/`— use default —` entries actually disappear.

Add to `patch_config`:

```python
        if section == "policy":
            # per_tool: drop empty-string entries (they mean "use default")
            cleaned_per_tool = {
                t: m for t, m in submitted.get("per_tool", {}).items() if m
            }
            new_section = {
                "default_mode": submitted.get("default_mode"),
                "confirm_timeout_s": submitted.get("confirm_timeout_s"),
                "per_tool": cleaned_per_tool,
            }
            # Drop None entries so Pydantic defaults apply where the form left fields blank.
            new_section = {k: v for k, v in new_section.items() if v is not None}
            return _apply_section_and_write(
                request, "policy", ["policy"], new_section,
            )
```

Note: `_apply_section_and_write` does a shallow merge of the submitted dict into the existing section. We pass the **whole** new section, so `per_tool` gets replaced wholesale (which is what we want).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_routes_policy.py -v`
Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add androidharness/web/routes.py androidharness/web/templates/_policy.html tests/web/test_routes_policy.py
git commit -m "feat(web): Policy panel — edit cfg.policy via /panel/policy"
```

---

## Task 12: Throttler panel

**Files:**
- Modify: `androidharness/web/routes.py`
- Create: `androidharness/web/templates/_throttler.html`
- Test: `tests/web/test_routes_throttler.py`

The Throttler panel edits `enabled`, `cooldown_seconds`, `num_retries`, and the `buckets` dict. Each bucket is keyed by a `provider/model` string with `rpm` / `tpm` ints (empty = "no limit"). Adding new bucket rows is via a free-form "add row" pattern — the template renders existing rows plus one blank row; on save, blank rows with no key are dropped.

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_routes_throttler.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from androidharness.web.app import create_app
from androidharness.web.store import ConfigStore


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "config.yaml"
    return TestClient(create_app(cfg_path)), cfg_path


def test_get_panel_throttler_renders_current_values(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/panel/throttler")
    assert resp.status_code == 200
    assert "enabled" in resp.text
    assert "cooldown_seconds" in resp.text


def test_patch_config_throttler_enables_with_one_bucket(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/throttler",
        data={
            "enabled": "true",
            "cooldown_seconds": "30",
            "num_retries": "3",
            "bucket_keys": "gemini/gemini-2.5-flash",
            "bucket.gemini/gemini-2.5-flash.rpm": "60",
            "bucket.gemini/gemini-2.5-flash.tpm": "100000",
        },
    )
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.throttler.enabled is True
    assert reloaded.throttler.cooldown_seconds == 30
    assert reloaded.throttler.buckets["gemini/gemini-2.5-flash"].rpm == 60
    assert reloaded.throttler.buckets["gemini/gemini-2.5-flash"].tpm == 100000


def test_patch_config_throttler_empty_caps_become_none(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/throttler",
        data={
            "enabled": "false",
            "cooldown_seconds": "60",
            "num_retries": "2",
            "bucket_keys": "openai/gpt-4o-mini",
            "bucket.openai/gpt-4o-mini.rpm": "",
            "bucket.openai/gpt-4o-mini.tpm": "",
        },
    )
    assert resp.status_code == 200
    assert "banner-ok" in resp.text
    reloaded = ConfigStore(cfg_path).load()
    assert reloaded.throttler.buckets["openai/gpt-4o-mini"].rpm is None
    assert reloaded.throttler.buckets["openai/gpt-4o-mini"].tpm is None


def test_patch_config_throttler_invalid_cooldown_does_not_write(tmp_path: Path):
    client, cfg_path = _client(tmp_path)
    resp = client.patch(
        "/config/throttler",
        data={"enabled": "true", "cooldown_seconds": "0", "num_retries": "2"},
    )
    assert resp.status_code == 200
    assert "banner-err" in resp.text
    if cfg_path.exists():
        reloaded = ConfigStore(cfg_path).load()
        assert reloaded.throttler.cooldown_seconds == 60  # default
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_routes_throttler.py -v`
Expected: four failures.

- [ ] **Step 3: Implement the panel template**

Create `androidharness/web/templates/_throttler.html`:

```html
<section class="panel">
  <h2>Throttler</h2>
  {% if banner %}<div class="banner banner-{{ banner_kind }}">{{ banner }}</div>{% endif %}

  <form hx-patch="/config/throttler" hx-target="#panel" hx-swap="innerHTML">
    <div class="field">
      <label>
        <input type="checkbox" name="enabled" value="true"
               {% if (overrides.get('enabled') or cfg.throttler.enabled) %}checked{% endif %}>
        Enabled (routes calls through litellm.Router for rate limiting + fallback)
      </label>
    </div>

    <div class="field">
      <label for="cooldown_seconds">Cooldown after a rate-limit (seconds)</label>
      <input id="cooldown_seconds" name="cooldown_seconds" type="number" min="1"
             value="{{ overrides.get('cooldown_seconds', cfg.throttler.cooldown_seconds) }}">
      {% if errors.get('cooldown_seconds') %}<span class="err">{{ errors['cooldown_seconds'] }}</span>{% endif %}
    </div>

    <div class="field">
      <label for="num_retries">Retries before giving up</label>
      <input id="num_retries" name="num_retries" type="number" min="0"
             value="{{ overrides.get('num_retries', cfg.throttler.num_retries) }}">
      {% if errors.get('num_retries') %}<span class="err">{{ errors['num_retries'] }}</span>{% endif %}
    </div>

    <h3 style="margin-top: 24px;">Buckets</h3>
    <table>
      <thead><tr><th>provider/model</th><th>RPM</th><th>TPM</th></tr></thead>
      <tbody>
        {% set keys = cfg.throttler.buckets.keys() | list %}
        <input type="hidden" name="bucket_keys" value="{{ keys|join(',') }}">
        {% for key in keys %}
          {% set b = cfg.throttler.buckets[key] %}
          <tr>
            <td><code>{{ key }}</code></td>
            <td><input name="bucket.{{ key }}.rpm" type="number" min="1" value="{{ b.rpm or '' }}"></td>
            <td><input name="bucket.{{ key }}.tpm" type="number" min="1" value="{{ b.tpm or '' }}"></td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
    <p class="placeholder">Add new buckets by editing config.yaml directly for now; this panel edits existing entries.</p>

    <button type="submit" style="margin-top: 16px;">Save</button>
  </form>
</section>
```

(Adding new buckets via the UI is a follow-up; the empty-row pattern is more form-handling code than the rest of M5. Existing buckets are fully editable.)

- [ ] **Step 4: Add the dispatch arm to `routes.py`**

The throttler form posts:
- `enabled` (checkbox — present iff checked)
- `cooldown_seconds`, `num_retries`
- `bucket_keys` (comma-separated list of bucket keys present in the form)
- `bucket.<key>.rpm`, `bucket.<key>.tpm` per bucket

The handler needs to:
- Coerce the checkbox absence to `False`
- Build `buckets` dict from `bucket_keys` (NOT from the unflattened dict, because the dotted keys contain `/` which can interact poorly with naive splitting)

To avoid the `/` ambiguity, the throttler arm consumes the raw form directly instead of using `unflatten`:

```python
        if section == "throttler":
            raw_form = {k: str(v) for k, v in form.items()}
            enabled = raw_form.get("enabled") == "true"
            bucket_keys = [k for k in raw_form.get("bucket_keys", "").split(",") if k]
            buckets: dict[str, dict] = {}
            for key in bucket_keys:
                rpm_raw = raw_form.get(f"bucket.{key}.rpm", "")
                tpm_raw = raw_form.get(f"bucket.{key}.tpm", "")
                bucket: dict = {}
                if rpm_raw:
                    bucket["rpm"] = rpm_raw
                if tpm_raw:
                    bucket["tpm"] = tpm_raw
                buckets[key] = bucket
            new_section = {
                "enabled": enabled,
                "cooldown_seconds": raw_form.get("cooldown_seconds"),
                "num_retries": raw_form.get("num_retries"),
                "buckets": buckets,
            }
            new_section = {k: v for k, v in new_section.items() if v is not None}
            return _apply_section_and_write(
                request, "throttler", ["throttler"], new_section,
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_routes_throttler.py -v`
Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add androidharness/web/routes.py androidharness/web/templates/_throttler.html tests/web/test_routes_throttler.py
git commit -m "feat(web): Throttler panel — edit cfg.throttler via /panel/throttler"
```

---

## Task 13: Models panel (logical models)

The Models panel edits `cfg.providers.logical_models` — a dict of logical name → ordered list of `provider/model` fallback chain entries.

**Files:**
- Modify: `androidharness/web/routes.py`
- Create: `androidharness/web/templates/_models.html`
- Test: `tests/web/test_routes_models.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_routes_models.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_routes_models.py -v`
Expected: four failures.

- [ ] **Step 3: Implement the panel template**

Create `androidharness/web/templates/_models.html`:

```html
<section class="panel">
  <h2>Logical models</h2>
  {% if banner %}<div class="banner banner-{{ banner_kind }}">{{ banner }}</div>{% endif %}
  <p class="placeholder">
    Logical names (e.g. <code>fast</code>, <code>smart</code>, <code>cheap</code>) map to ordered
    fallback chains of <code>provider/model</code> entries. The throttler tries each entry in order
    on rate-limit errors.
  </p>

  <form hx-patch="/config/models" hx-target="#panel" hx-swap="innerHTML">
    {% set names = cfg.providers.logical_models.keys() | list %}
    <input type="hidden" name="logical_names" value="{{ names|join(',') }}">

    <table>
      <thead><tr><th>Name</th><th>Fallback chain (comma-separated)</th></tr></thead>
      <tbody>
        {% for name in names %}
          {% set chain_key = 'chain.' ~ name %}
          {% set current_chain = overrides.get(chain_key, cfg.providers.logical_models[name]|join(', ')) %}
          <tr>
            <td><code>{{ name }}</code></td>
            <td>
              <input name="{{ chain_key }}" value="{{ current_chain }}" style="min-width: 420px;">
              {% if errors.get(chain_key) or errors.get('providers.logical_models.' ~ name) %}
                <span class="err">{{ errors.get(chain_key) or errors.get('providers.logical_models.' ~ name) }}</span>
              {% endif %}
            </td>
          </tr>
        {% endfor %}
        {# One blank row to add a new logical model #}
        <tr>
          <td><input name="new_logical_name" placeholder="name (e.g. smart)"></td>
          <td><input name="new_chain" placeholder="anthropic/claude-haiku-4-5, openai/gpt-4o-mini" style="min-width: 420px;"></td>
        </tr>
      </tbody>
    </table>

    <button type="submit" style="margin-top: 16px;">Save</button>
  </form>
</section>
```

- [ ] **Step 4: Add the dispatch arm to `routes.py`**

Add to `patch_config`:

```python
        if section == "models":
            raw_form = {k: str(v) for k, v in form.items()}
            names = [n for n in raw_form.get("logical_names", "").split(",") if n]
            logical_models: dict[str, list[str]] = {}
            for name in names:
                raw_chain = raw_form.get(f"chain.{name}", "")
                chain = [e.strip() for e in raw_chain.split(",") if e.strip()]
                logical_models[name] = chain
            new_name = raw_form.get("new_logical_name", "").strip()
            new_chain_raw = raw_form.get("new_chain", "").strip()
            if new_name and new_chain_raw:
                logical_models[new_name] = [
                    e.strip() for e in new_chain_raw.split(",") if e.strip()
                ]
            # We replace `providers.logical_models` wholesale.
            return _apply_section_and_write(
                request, "models", ["providers"],
                {"logical_models": logical_models},
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_routes_models.py -v`
Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add androidharness/web/routes.py androidharness/web/templates/_models.html tests/web/test_routes_models.py
git commit -m "feat(web): Models panel — edit cfg.providers.logical_models via /panel/models"
```

---

## Task 14: Providers panel (with secrets badges)

This is the most involved panel — it lists each provider entry with editable `api_key_env` and `default_model`, plus the top-level `default` and `use_litellm` toggles. Each entry shows a `✓ set` / `✗ missing` badge based on `ProviderSecrets.is_set`.

**Files:**
- Modify: `androidharness/web/routes.py`
- Modify: `androidharness/web/templates/_providers.html` (replacing the Task 6 placeholder)
- Test: `tests/web/test_routes_providers.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_routes_providers.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_routes_providers.py -v`
Expected: five failures.

- [ ] **Step 3: Replace the placeholder `_providers.html`**

Overwrite `androidharness/web/templates/_providers.html`:

```html
<section class="panel">
  <h2>Providers</h2>
  {% if banner %}<div class="banner banner-{{ banner_kind }}">{{ banner }}</div>{% endif %}

  <form hx-patch="/config/providers" hx-target="#panel" hx-swap="innerHTML">
    <div class="field">
      <label for="default">Default provider</label>
      <select id="default" name="default">
        {% set current_default = overrides.get('default', cfg.providers.default) %}
        {% for name in cfg.providers.entries.keys() %}
          <option value="{{ name }}" {% if name == current_default %}selected{% endif %}>{{ name }}</option>
        {% endfor %}
      </select>
      {% if errors.get('providers.default') %}<span class="err">{{ errors['providers.default'] }}</span>{% endif %}
    </div>

    <div class="field">
      <label>
        <input type="checkbox" name="use_litellm" value="true"
               {% if overrides.get('use_litellm') == 'true' or (overrides.get('use_litellm') is none and cfg.providers.use_litellm) %}checked{% endif %}>
        Use LiteLLM (uncheck to fall back to v1 GoogleGenaiClient)
      </label>
    </div>

    <h3 style="margin-top: 24px;">Entries</h3>
    <input type="hidden" name="provider_keys" value="{{ cfg.providers.entries.keys()|join(',') }}">
    <table>
      <thead>
        <tr><th>Name</th><th>api_key_env</th><th>default_model</th><th>Status</th></tr>
      </thead>
      <tbody>
        {% for name, entry in cfg.providers.entries.items() %}
          <tr>
            <td><code>{{ name }}</code></td>
            <td>
              <input name="entries.{{ name }}.api_key_env"
                     value="{{ overrides.get('entries.' ~ name ~ '.api_key_env', entry.api_key_env) }}">
              {% if errors.get('providers.entries.' ~ name ~ '.api_key_env') %}
                <span class="err">{{ errors['providers.entries.' ~ name ~ '.api_key_env'] }}</span>
              {% endif %}
            </td>
            <td>
              <input name="entries.{{ name }}.default_model"
                     value="{{ overrides.get('entries.' ~ name ~ '.default_model', entry.default_model) }}">
              {% if errors.get('providers.entries.' ~ name ~ '.default_model') %}
                <span class="err">{{ errors['providers.entries.' ~ name ~ '.default_model'] }}</span>
              {% endif %}
            </td>
            <td>
              {% if secrets_set.get(name) %}
                <span class="badge badge-set">✓ set</span>
              {% else %}
                <span class="badge badge-missing">✗ missing</span>
              {% endif %}
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>

    <button type="submit" style="margin-top: 16px;">Save</button>
  </form>
</section>
```

- [ ] **Step 4: Update `_render_panel` to inject the secrets-set map**

In `androidharness/web/routes.py`, import the secrets module:

```python
from androidharness.web.secrets import ProviderSecrets
```

Extend `_render_panel`'s `extra` block:

```python
    if name == "devices":
        extra["devices"] = list_adb_devices()
    if name == "providers":
        extra["secrets_set"] = {
            entry_name: ProviderSecrets.is_set(entry.api_key_env)
            for entry_name, entry in cfg.providers.entries.items()
        }
```

- [ ] **Step 5: Add the dispatch arm to `routes.py`**

Add to `patch_config`:

```python
        if section == "providers":
            raw_form = {k: str(v) for k, v in form.items()}
            provider_keys = [k for k in raw_form.get("provider_keys", "").split(",") if k]
            entries: dict[str, dict] = {}
            for name in provider_keys:
                entries[name] = {
                    "api_key_env": raw_form.get(f"entries.{name}.api_key_env", ""),
                    "default_model": raw_form.get(f"entries.{name}.default_model", ""),
                }
            new_section = {
                "default": raw_form.get("default", ""),
                "use_litellm": raw_form.get("use_litellm") == "true",
                "entries": entries,
            }
            # We let Pydantic validate string-emptiness — leave fields in so the user sees the error.
            return _apply_section_and_write(
                request, "providers", ["providers"], new_section,
            )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/web/test_routes_providers.py -v`
Expected: all five pass.

Run: `uv run pytest tests/web/ -v`
Expected: full suite green.

- [ ] **Step 7: Commit**

```bash
git add androidharness/web/routes.py androidharness/web/templates/_providers.html tests/web/test_routes_providers.py
git commit -m "feat(web): Providers panel — edit cfg.providers via /panel/providers, env-presence badges"
```

---

## Task 15: Full suite + ruff + manual smoke

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass — no failures introduced in pre-existing tests.

- [ ] **Step 2: Run ruff**

Run: `uv run ruff check androidharness/ tests/`
Expected: no issues. If `B008` flags Typer `Option()` defaults in the new `serve` command in `cli.py`, those are already covered by the per-file ignore in `pyproject.toml`.

- [ ] **Step 3: Manually smoke the UI**

Run: `uv run androidharness serve --config /tmp/m5-smoke.yaml`
Expected: stderr shows `open: http://127.0.0.1:8000/`. Open the URL in a browser, click every sidebar entry, save a value on at least the General and Policy panels, confirm the success banner, then `cat /tmp/m5-smoke.yaml` to confirm the change landed.

If any panel renders broken, fix and re-test before committing.

(No commit at this step unless fixes are made — this is a verification gate.)

---

## Task 16: Documentation updates

**Files:**
- Modify: `docs/configuration.md`
- Modify: `docs/architecture.md`
- Modify: `docs/getting-started.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: `docs/configuration.md`**

Add a new section near the top, before the per-section reference:

```markdown
## Editing the config

Two ways:

* **Settings UI:** `uv run androidharness serve` (requires the `[web]` extra), then open <http://127.0.0.1:8000>. Inline validation, atomic writes, no restart of the server needed when you re-save.
* **Direct YAML:** edit `~/.androidharness/config.yaml` (or `$ANDROIDHARNESS_CONFIG`). Runs read config at start, so re-run after editing.

The Settings UI and the CLI both write the same file. API keys are referenced by env-var name only — the UI never reads or stores the key itself.
```

- [ ] **Step 2: `docs/architecture.md`**

Add a paragraph in the module reference, after the existing entries:

```markdown
* **`androidharness/web/`** — Settings UI subpackage (v2 milestone 5). FastAPI app behind a lazy import from `cli.py serve`, so the `[web]` extra (`fastapi`, `jinja2`, `uvicorn`, `python-multipart`, `pydantic-settings`) stays optional. `web/store.py` does atomic load/write; `web/routes.py` registers one `GET /panel/<name>` + `PATCH /config/<section>` per panel; `web/secrets.py` resolves `api_key_env` references against `os.environ`. Validation runs the full `AndroidHarnessConfig` end-to-end so cross-section invariants are caught before writing.
```

- [ ] **Step 3: `docs/getting-started.md`**

Add a short paragraph in the "Configuring" / setup section:

```markdown
### Settings UI (optional)

Install the web extra and run the editor:

    uv add 'androidharness[web]'
    uv run androidharness serve

…then open <http://127.0.0.1:8000>. The UI binds to localhost only — no auth, no network exposure. Runs that started before you saved still use the config they snapshotted at start; new runs pick up the change.
```

- [ ] **Step 4: `docs/roadmap.md`**

Update the M5 row:

```markdown
| 5 | **Web UI v2.0 — Settings UI** — FastAPI + HTMX editor for providers, models, throttler, policy, devices, logging, defaults | **Shipped** | <SHA-RANGE> |
```

(Replace `<SHA-RANGE>` with the actual first…last commit SHAs of this plan's implementation after Task 16 commits.)

Update the "Current focus" section accordingly:

```markdown
## Current focus

Milestones 1–5 are complete. The "v2 minimum" block is shipped. Milestone 6 (perception compression step 1 — sibling collapse) is the next planned item.
```

- [ ] **Step 5: Commit**

```bash
git add docs/configuration.md docs/architecture.md docs/getting-started.md docs/roadmap.md
git commit -m "docs: Settings UI in configuration / architecture / getting-started; M5 shipped"
```

---

## Done

Final verification:

```bash
uv run pytest -q
uv run ruff check androidharness/ tests/
uv run androidharness serve --config /tmp/m5-final-smoke.yaml  # then click around
```

If all three pass cleanly, M5 is ready to merge. Use `superpowers:finishing-a-development-branch` to decide on the integration approach (push the branch, open a PR, etc.).
