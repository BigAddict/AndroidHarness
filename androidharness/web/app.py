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
