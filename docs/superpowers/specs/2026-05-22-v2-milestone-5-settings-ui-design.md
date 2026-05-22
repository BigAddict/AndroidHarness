# v2 Milestone 5 — Settings UI design

**Status:** spec, ready to plan.
**Date:** 2026-05-22.
**Parent spec:** `docs/superpowers/specs/2026-05-20-v2-stack-and-scale-design.md` §9 (Web UI v2.0).

## Goal

Ship a browser-based editor for the shipped seam config (providers, logical models, throttler, policy, devices, logs, defaults) so the user can change every M1–M4 knob without hand-editing `~/.androidharness/config.yaml`. The CLI keeps working unchanged — both surfaces read/write the same Pydantic-validated YAML file.

This is the last item in the "v2 minimum" block of the roadmap.

## Non-goals (out of scope for M5)

- **Memory panel.** `MemoryConfig` exists but the vector store (M12) isn't built; editing it would change nothing.
- **Perception panel.** Only `viewport_filter` is live today; the other flags don't gate any code path yet. Defer the panel until perception steps 2–5 actually flip behavior.
- **Run launcher / live monitoring / replay / cost dashboard.** Those are v2.1–v2.4. M5 is the configuration surface only.
- **Auth.** The server binds to `127.0.0.1` only; no login.
- **Hot-reload for a running `serve` process.** Runs snapshot config at start, so config edits take effect on the next `run` invocation. No SIGHUP / inotify machinery.
- **Restart-required indicator.** Same reason — there is no in-process state to invalidate.
- **Browser-driven tests.** HTMX-rendered HTML is asserted via `TestClient`; Playwright/CDP smoke tests are a follow-up if warranted.

## Architecture

A new `androidharness/web/` subpackage. Lazy-imported from `cli.py` so the `[web]` extra is genuinely optional — invoking `androidharness serve` without `fastapi` installed prints a one-line install hint and exits cleanly.

```
androidharness/web/
├── __init__.py           # exports `create_app`
├── app.py                # `create_app(config_path) -> FastAPI` — wires deps, routes, templates
├── store.py              # `ConfigStore` — load + atomic write of config.yaml
├── routes.py             # one handler per panel (GET /panel/<name>, PATCH /config/<section>)
├── secrets.py            # pydantic-settings layer for env-var key resolution
├── devices.py            # thin wrapper over `androidharness.device.list_devices`
├── templates/
│   ├── base.html         # sidebar nav, panel slot, HTMX script tag
│   ├── index.html        # extends base, default panel = "providers"
│   └── _<panel>.html     # one per panel; rendered into the slot on swap
└── static/
    └── styles.css        # ~150 lines, hand-written, system font stack
```

**Dependency injection.** `create_app(config_path)` constructs a single `ConfigStore` and stashes it on `app.state`. Route handlers depend on it via FastAPI's `Depends(get_store)`. This keeps tests trivial — they instantiate `create_app(tmp_path / "config.yaml")` and use `TestClient`.

**Stack.** FastAPI, Jinja2, HTMX (CDN script tag, no build step), vanilla CSS, `python-multipart` for form bodies. No JavaScript file of our own.

## Panels

| Panel | Edits | Notes |
|---|---|---|
| Providers | `cfg.providers.entries` (`api_key_env`, `default_model`), `cfg.providers.default`, `cfg.providers.use_litellm` | Each entry shows a "✓ set" / "✗ missing" badge based on `os.environ[api_key_env]` resolved via the `secrets` module. Keys themselves are never read into Python from the form. |
| Models | `cfg.providers.logical_models` (a dict of `name -> [provider/model, ...]` fallback chains) | Free-form list editor; one row per logical name. |
| Throttler | `cfg.throttler` (enabled, cooldown_seconds, num_retries, buckets) | One bucket row per `provider/model`; `rpm` / `tpm` empty inputs mean "no limit" (`None`). |
| Policy | `cfg.policy` (default_mode, confirm_timeout_s, per_tool) | Per-tool dropdowns with the four `PolicyMode` choices. |
| Devices | live `adb devices` + `cfg.defaults.device_serial` | Read-only device list + a single select for the default. |
| Logging | `cfg.logging` (level, rotation_mb) | |
| General | `cfg.defaults` (model, max_turns, wall_clock_s, runs_dir, logs_dir) | Catch-all for the top-level defaults that don't merit their own panel. |

Seven panels total. Each lives behind `GET /panel/<name>` and `PATCH /config/<section>`. The `<section>` keys match the config field names so the route → model mapping is mechanical.

## Routes

```
GET   /                            → index.html (sidebar + first panel pre-rendered)
GET   /panel/{name}                → _<name>.html (HTMX swap target)
PATCH /config/{section}            → re-render _<panel>.html with success or field errors
GET   /devices                     → JSON of live adb devices (for the Devices panel)
GET   /static/*                    → mounted static files
```

`name` and `section` are validated against an allowlist — anything else returns 404. The allowlist also pins each section to the config path it writes:

| Section | Config path written |
|---|---|
| `providers` | `cfg.providers.entries`, `cfg.providers.default`, `cfg.providers.use_litellm` |
| `models` | `cfg.providers.logical_models` |
| `throttler` | `cfg.throttler` |
| `policy` | `cfg.policy` |
| `devices` | `cfg.defaults.device_serial` |
| `logging` | `cfg.logging` |
| `general` | `cfg.defaults` (excluding `device_serial`, which the Devices panel owns) |

## Write protocol (atomic)

`ConfigStore.write(cfg)`:

1. Serialize via `cfg.model_dump(mode="json")` → `yaml.safe_dump`.
2. Write to `<config_path>.tmp` in the same directory.
3. `os.replace(tmp, config_path)` — POSIX atomic on same filesystem.
4. Return `cfg`.

`ConfigStore.load()` re-reads from disk on every call. No caching; the file is small and read traffic is human-driven.

## Validation UX

1. Form submits via `hx-post="/config/<section>"` with `hx-target` set to the panel container.
2. Handler deserializes the form into the relevant Pydantic submodel.
3. The submodel is plugged into a full-config copy and re-validated end-to-end (catches cross-section invariants like `providers.default` not in `entries`).
4. On `ValidationError`: build `{field_path: message}` from `e.errors()`, re-render `_<panel>.html` with submitted values + per-field error spans. **Do not write.**
5. On success: write atomically, re-render `_<panel>.html` with a success banner.

Each error span sits adjacent to its input (`<span class="err" id="err-<field>">`). Top-of-form `<div class="banner banner-{ok|err}">` carries the overall outcome.

## Secrets handling

Per the brainstorm decision: env-var references only. The form takes the **env var name**, never the literal key.

The new `androidharness/web/secrets.py` module exposes:

```python
class ProviderSecrets(BaseSettings):
    """pydantic-settings reader. Resolves api_key_env names to env presence/value."""

    model_config = SettingsConfigDict(extra="allow")

    @classmethod
    def is_set(cls, env_var_name: str) -> bool: ...

    @classmethod
    def get(cls, env_var_name: str) -> str | None: ...
```

The Providers panel template calls `ProviderSecrets.is_set(entry.api_key_env)` to render the badge. Existing LLM client code that reads `os.environ[api_key_env]` directly is unchanged — pydantic-settings is additive here, not a refactor of the call sites.

`pydantic-settings` ships as a dep of the `[web]` extra (not the base install), because nothing in the base install needs the env layer.

## Packaging

`pyproject.toml` gains:

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

CLI:

```
androidharness serve [--port 8000] [--host 127.0.0.1] [--config <path>]
```

The `serve` command lazy-imports `androidharness.web` inside the handler. If `fastapi` is missing, catches `ModuleNotFoundError` and prints:

```
the `serve` command needs the optional [web] extra:
    uv add 'androidharness[web]'
    # or: pip install 'androidharness[web]'
```

…then exits with code 1.

## Testing strategy

| Test file | What it covers |
|---|---|
| `tests/web/test_store.py` | `ConfigStore.load()` defaults / round-trip / atomic write (tmp file gone after; partial-write crash leaves original intact). |
| `tests/web/test_secrets.py` | `ProviderSecrets.is_set` / `.get` reads from monkeypatched `os.environ`. |
| `tests/web/test_devices.py` | `list_adb_devices()` wraps `device.list_devices()` (monkeypatched). |
| `tests/web/test_routes_<panel>.py` | One file per panel — GET renders the panel, valid PATCH writes + re-renders success, invalid PATCH does NOT write + re-renders inline errors. Uses `TestClient(create_app(tmp_path / "config.yaml"))`. |
| `tests/web/test_app.py` | GET `/` returns the sidebar + the default panel; lazy-import error path on serve when fastapi is uninstalled (subprocess test). |
| `tests/test_cli_serve.py` | `androidharness serve --help` works without `[web]` extra (the import is lazy). |

No browser-driven tests. HTMX targets and `hx-post` attributes are asserted as text in the rendered HTML.

## Conventions

- Each `_<panel>.html` partial is self-contained — same template renders for GET and for PATCH responses (just with different banner/error state).
- Form field names match Pydantic field paths with `.` separators where needed (`per_tool.tap`, `entries.gemini.api_key_env`). The handler turns the flat form into nested dicts before validation.
- Static assets served by FastAPI's `StaticFiles` mount; no CDN besides the HTMX `<script>` (also vendorable as a static file later if offline is required).
- All HTML emitted is HTML5; no XHTML self-closing on void elements.
- The CSS file uses CSS custom properties for the (small) color palette — easy to dark-theme later without touching templates.

## Files touched

**New:**
- `androidharness/web/__init__.py`, `app.py`, `store.py`, `routes.py`, `secrets.py`, `devices.py`
- `androidharness/web/templates/base.html`, `index.html`, plus `_providers.html`, `_models.html`, `_throttler.html`, `_policy.html`, `_devices.html`, `_logging.html`, `_general.html`
- `androidharness/web/static/styles.css`
- `tests/web/__init__.py`, `tests/web/test_store.py`, `tests/web/test_secrets.py`, `tests/web/test_devices.py`, plus one `test_routes_<panel>.py` per panel, `tests/web/test_app.py`, `tests/test_cli_serve.py`

**Modified:**
- `pyproject.toml` — `[project.optional-dependencies] web = [...]`.
- `androidharness/cli.py` — add `serve` command with lazy import + missing-extra error path.
- `docs/configuration.md` — point at the Settings UI as the primary editor.
- `docs/architecture.md` — add a Web UI paragraph.
- `docs/getting-started.md` — mention `androidharness serve`.
- `docs/roadmap.md` — mark M5 Shipped (after merge).

**Untouched:**
- `agent.py`, `llm.py`, `policy.py`, `device.py`, `perception.py`, `render.py`, `tools.py`, `runner.py`, `imaging.py`, `logging_setup.py`, `config.py`. M5 reads `config.py`'s models but does not modify them.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| HTMX form serialization gets weird with nested fields (`entries.gemini.api_key_env`). | Handler explicitly un-flattens via a small helper; covered by `test_routes_providers.py`. |
| Lazy import of `web` from `cli.py` masks real import errors as "missing extra". | Catch `ModuleNotFoundError` and inspect `e.name` — only suppress when the missing module is a `[web]`-extra dep. Re-raise everything else. |
| Atomic write across filesystems (e.g., `/tmp` ≠ `$HOME`) breaks `os.replace`. | Write the tmp file alongside the real file (same parent dir). Test asserts this. |
| `adb devices` shells out and can hang. | Reuse `device.list_devices()`'s 5s subprocess timeout — already there. Devices panel surfaces failure as "adb not available" instead of crashing. |
| A future schema change quietly drops user data on round-trip. | `model_config = ConfigDict(extra="forbid")` is already on every model — unknown keys would raise. Round-trip test in `test_store.py` covers this. |

## Sequencing inside the milestone

Plan should order the implementation tasks roughly like:

1. Packaging + `serve` skeleton (lazy import + missing-extra error path).
2. `ConfigStore` (load + atomic write).
3. `ProviderSecrets` (pydantic-settings layer).
4. App skeleton + base template + static CSS + `GET /` + sidebar.
5. Panels in order of independence: General → Logging → Devices → Policy → Throttler → Models → Providers. (Providers last because it depends on `secrets.py` and has the most form fields.)
6. Docs + roadmap update.

Each task ends with passing tests and a commit.
