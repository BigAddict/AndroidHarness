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
