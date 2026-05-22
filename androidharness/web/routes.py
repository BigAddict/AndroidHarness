"""Settings UI route handlers.

Each panel exposes:
  * GET  /panel/<name>          — render the panel partial
  * PATCH /config/<section>     — validate, atomic-write, re-render

`name` and `section` are validated against an allowlist; unknown values 404.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from androidharness.config import AndroidHarnessConfig
from androidharness.web.devices import list_adb_devices
from androidharness.web.forms import FormError, unflatten
from androidharness.web.secrets import ProviderSecrets

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
    extra: dict = {}
    if name == "devices":
        extra["devices"] = list_adb_devices()
    if name == "providers":
        extra["secrets_set"] = {
            entry_name: ProviderSecrets.is_set(entry.api_key_env)
            for entry_name, entry in cfg.providers.entries.items()
        }
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


def _validate_full(cfg_dump: dict) -> AndroidHarnessConfig:
    """Round-trip through AndroidHarnessConfig so cross-section invariants run."""
    return AndroidHarnessConfig.model_validate(cfg_dump)


def _pydantic_errors_to_dict(e: ValidationError) -> dict[str, str]:
    """Map each Pydantic error to a dotted-path key → human message."""
    out: dict[str, str] = {}
    for err in e.errors():
        path = ".".join(str(p) for p in err["loc"])
        out[path] = err["msg"]
    return out


def _strip_section_prefix(errors: dict[str, str], section_path: list[str]) -> dict[str, str]:
    """Remove the leading section prefix from error keys so templates use short names.

    Pydantic reports `defaults.max_turns` for a field inside `cfg.defaults`.
    The General panel template checks `errors.get('max_turns')`, not the full
    path. Stripping the prefix here keeps every panel template clean.
    """
    prefix = ".".join(section_path) + "."
    return {
        (key[len(prefix):] if key.startswith(prefix) else key): msg
        for key, msg in errors.items()
    }


def _apply_section_and_write(
    request: Request,
    name: str,
    section_path: list[str],
    submitted: dict,
):
    """Merge `submitted` into config at `section_path`, validate, and write on success.

    On ValidationError: renders the panel with errors (prefix-stripped to short
    field names) and the submitted values as overrides — no write occurs.
    On success: atomically writes the new config and renders with a success banner.
    """
    store = request.app.state.store
    cfg = store.load()
    cfg_dump = cfg.model_dump(mode="python")

    # Walk to the parent node and shallow-merge submitted into the target section.
    node = cfg_dump
    for part in section_path[:-1]:
        node = node.setdefault(part, {})
    last = section_path[-1] if section_path else None
    if last is None:
        cfg_dump.update(submitted)
    else:
        existing = node.get(last, {})
        merged = {**existing, **submitted} if isinstance(existing, dict) else submitted
        node[last] = merged

    try:
        new_cfg = _validate_full(cfg_dump)
    except ValidationError as e:
        raw_errors = _pydantic_errors_to_dict(e)
        errors = _strip_section_prefix(raw_errors, section_path)
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


def register_routes(app: FastAPI) -> None:
    templates = app.state.templates

    @app.get("/")
    def index(request: Request):
        store = request.app.state.store
        cfg = store.load()
        secrets_set = {
            entry_name: ProviderSecrets.is_set(entry.api_key_env)
            for entry_name, entry in cfg.providers.entries.items()
        }
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "cfg": cfg,
                "panels": list(PANELS.keys()),
                "active": "providers",
                "panel": "providers",
                "banner": None,
                "banner_kind": "ok",
                "errors": {},
                "overrides": {},
                "secrets_set": secrets_set,
            },
        )

    @app.get("/panel/{name}")
    def get_panel(name: str, request: Request):
        if name not in PANELS:
            raise HTTPException(status_code=404, detail=f"unknown panel: {name}")
        return _render_panel(request, name)

    @app.patch("/config/{section}")
    async def patch_config(section: str, request: Request):
        if section not in PANELS:
            raise HTTPException(status_code=404, detail=f"unknown section: {section}")
        form = await request.form()

        # Models is special-cased before unflatten: chain entries contain '/'
        # (e.g. 'gemini/gemini-2.5-flash') which unflatten would split as nested keys.
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
            return _apply_section_and_write(
                request, "models", ["providers"],
                {"logical_models": logical_models},
            )

        # Providers is special-cased before unflatten: entries.<name>.api_key_env
        # contains dots that unflatten would interpret as nested keys.
        if section == "providers":
            raw_form = {k: str(v) for k, v in form.items()}
            provider_keys = [k for k in raw_form.get("provider_keys", "").split(",") if k]
            entries: dict[str, dict] = {}
            for name in provider_keys:
                entries[name] = {
                    "api_key_env": raw_form.get(f"entries.{name}.api_key_env", ""),
                    "default_model": raw_form.get(f"entries.{name}.default_model", ""),
                }
            new_section: dict = {
                "default": raw_form.get("default", ""),
                "use_litellm": raw_form.get("use_litellm") == "true",
                "entries": entries,
            }
            return _apply_section_and_write(
                request, "providers", ["providers"], new_section,
            )

        # Throttler is special-cased before unflatten: bucket keys contain '/'
        # which dotted-path splitting would misinterpret as nested structure.
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
            new_section: dict = {
                "enabled": enabled,
                "cooldown_seconds": raw_form.get("cooldown_seconds"),
                "num_retries": raw_form.get("num_retries"),
                "buckets": buckets,
            }
            new_section = {k: v for k, v in new_section.items() if v is not None}
            return _apply_section_and_write(request, "throttler", ["throttler"], new_section)

        try:
            submitted = unflatten({k: str(v) for k, v in form.items()})
        except FormError as e:
            return _render_panel(
                request, section, banner=str(e), banner_kind="err",
                overrides={k: str(v) for k, v in form.items()},
            )

        if section == "general":
            # All fields land directly on cfg.defaults (device_serial is owned by Devices).
            return _apply_section_and_write(request, "general", ["defaults"], submitted)
        if section == "logging":
            return _apply_section_and_write(request, "logging", ["logging"], submitted)
        if section == "devices":
            return _apply_section_and_write(
                request, "devices", ["defaults"],
                {"device_serial": submitted.get("device_serial") or None},
            )
        if section == "policy":
            # per_tool: drop empty-string entries (they mean "use default").
            # Pass the whole new section so _apply_section_and_write replaces
            # per_tool wholesale rather than merging into the existing dict.
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

        raise HTTPException(status_code=405, detail=f"PATCH not yet wired for {section}")


__all__ = ["register_routes", "PANELS"]
