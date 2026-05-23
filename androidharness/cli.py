from __future__ import annotations

import os
import sys
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
from androidharness.device import UIAutomatorDevice, list_devices
from androidharness.llm import GoogleGenaiClient, LiteLLMClient, LiteLLMRouterClient
from androidharness.logging_setup import setup_logging
from androidharness.perception import parse_hierarchy
from androidharness.render import DEFAULT_RENDERER
from androidharness.runner import run_task

app = typer.Typer(add_completion=False, help="AI harness for Android devices.")

config_app = typer.Typer(
    add_completion=False,
    help="Inspect or edit the AndroidHarness config file.",
)
app.add_typer(config_app, name="config")


def _resolve_config_path(path: Path | None) -> Path:
    return path if path is not None else default_config_path()


_VALID_POLICY_MODES = {"auto", "confirm", "dry-run", "deny"}


def _parse_policy_overrides(raw: str | None) -> dict[str, str]:
    """Parse a `--policy tap=confirm,type=deny` string into a per_tool dict.
    Returns {} when `raw` is None or empty. Raises typer.BadParameter on
    malformed input."""
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" not in pair:
            raise typer.BadParameter(
                f"--policy entry {pair!r} is not in `tool=mode` form"
            )
        tool, mode = (p.strip() for p in pair.split("=", 1))
        if mode not in _VALID_POLICY_MODES:
            raise typer.BadParameter(
                f"--policy mode {mode!r} for tool {tool!r} must be one of "
                f"{sorted(_VALID_POLICY_MODES)}"
            )
        out[tool] = mode
    return out


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
    dumped = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, default_flow_style=False)
    typer.echo(dumped, nl=False)


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


@app.command("devices")
def devices_cmd() -> None:
    """List ADB-connected devices."""
    infos = list_devices()
    if not infos:
        typer.echo("no devices connected (check 'adb devices')")
        raise typer.Exit(code=1)
    for i, info in enumerate(infos):
        typer.echo(f"[{i}] {info.serial}  {info.model}")


def _select_device_serial(serial, device_index, cfg, infos) -> str:
    """Resolve which device serial to use, matching `run`'s precedence:
    explicit --serial > --device-index > cfg.defaults.device_serial > sole
    connected device > error. Aborts the CLI on any ambiguity."""
    if serial and device_index is not None:
        typer.echo("error: --serial and --device-index are mutually exclusive", err=True)
        raise typer.Exit(code=2)
    if serial:
        if serial not in {i.serial for i in infos}:
            typer.echo(f"serial {serial!r} not in connected devices", err=True)
            raise typer.Exit(code=1)
        return serial
    if device_index is not None:
        if not 0 <= device_index < len(infos):
            typer.echo(f"--device-index out of range: {device_index}", err=True)
            raise typer.Exit(code=1)
        return infos[device_index].serial
    if cfg.defaults.device_serial is not None:
        if cfg.defaults.device_serial in {i.serial for i in infos}:
            return cfg.defaults.device_serial
    if len(infos) == 1:
        return infos[0].serial
    typer.echo("multiple devices — pass --serial or --device-index:", err=True)
    for i, info in enumerate(infos):
        typer.echo(f"  [{i}] {info.serial}  {info.model}", err=True)
    raise typer.Exit(code=1)


@app.command("peek")
def peek_cmd(
    serial: str | None = typer.Option(None, "--serial", "-s"),
    device_index: int | None = typer.Option(None, "--device-index", "-i"),
    viewport_filter: bool | None = typer.Option(
        None,
        "--viewport-filter/--no-viewport-filter",
        help="Drop off-screen / visibility=gone nodes. Default: cfg.perception.viewport_filter.",
    ),
    with_resource_ids: bool | None = typer.Option(
        None,
        "--with-resource-ids/--no-resource-ids",
        help="Append the resource-id to each node. Default: cfg.perception.resource_id_in_render.",
    ),
    sibling_collapse: bool | None = typer.Option(
        None,
        "--sibling-collapse/--no-sibling-collapse",
        help="Collapse runs of N≥3 identical sibling nodes. Default: cfg.perception.sibling_collapse.",  # noqa: E501
    ),
    raw_xml: bool = typer.Option(
        False,
        "--raw-xml",
        help="Print the raw uiautomator2 XML instead of the rendered Observation.",
    ),
    config_path: Path | None = typer.Option(None, "--config", help="Override the config path."),
) -> None:
    """Dump what the model would see on the connected device right now.

    Read-only: connects, dumps_hierarchy, parses, renders, prints. No LLM is
    called, no tool fires, the device state is not changed. Useful for
    debugging perception filters and previewing screens before pointing the
    agent at them.
    """
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e

    vf = viewport_filter if viewport_filter is not None else cfg.perception.viewport_filter
    rids = (
        with_resource_ids
        if with_resource_ids is not None
        else cfg.perception.resource_id_in_render
    )
    sc = (
        sibling_collapse
        if sibling_collapse is not None
        else cfg.perception.sibling_collapse
    )

    infos = list_devices()
    if not infos:
        typer.echo("no devices connected (check 'adb devices')", err=True)
        raise typer.Exit(code=1)
    chosen = _select_device_serial(serial, device_index, cfg, infos)

    device = UIAutomatorDevice.connect(chosen)
    xml = device.dump_hierarchy()
    if raw_xml:
        typer.echo(xml, nl=False)
        return

    obs = parse_hierarchy(xml, viewport_filter=vf)
    rendered = DEFAULT_RENDERER.observation(obs, with_resource_id=rids, sibling_collapse=sc)
    # Header goes to stderr so the rendered body on stdout stays pipeable.
    typer.echo(
        f"# {len(obs.nodes)} nodes (viewport_filter={vf}, resource_ids={rids}, "
        f"sibling_collapse={sc}, ~{len(rendered)} chars)",
        err=True,
    )
    typer.echo(rendered)


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
    policy_override: str | None = typer.Option(
        None, "--policy",
        help="Per-tool policy override, e.g. `tap=confirm,type=deny`.",
    ),
) -> None:
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e

    # Build the per-run Policy from config + CLI override.
    from androidharness.policy import CliConfirmer, Policy
    overrides = _parse_policy_overrides(policy_override)
    merged_per_tool = {**cfg.policy.per_tool, **overrides}
    policy = Policy.from_config(
        cfg.policy.model_copy(update={"per_tool": merged_per_tool})
    )
    confirmer = CliConfirmer(timeout_s=cfg.policy.confirm_timeout_s)

    d = cfg.defaults
    model = model if model is not None else d.model
    max_turns = max_turns if max_turns is not None else d.max_turns
    wall_clock = wall_clock if wall_clock is not None else d.wall_clock_s
    runs_dir = runs_dir if runs_dir is not None else Path(d.runs_dir)
    logs_dir = logs_dir if logs_dir is not None else Path(d.logs_dir)

    log_path = setup_logging(logs_dir)
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

    providers = cfg.providers
    throttler = cfg.throttler
    if providers.default not in providers.entries:
        typer.echo(
            f"error: providers.default={providers.default!r} not found in providers.entries",
            err=True,
        )
        raise typer.Exit(code=1)

    # The throttler-on branch checks every fallback provider's key — otherwise
    # the Router's fallback list contains deployments we can't actually call.
    required_provider_pairs: list[tuple[str, str]] = [
        (providers.default, providers.entries[providers.default].api_key_env)
    ]
    if throttler.enabled:
        for chain in providers.logical_models.values():
            for concrete in chain:
                prov = concrete.split("/", 1)[0]
                if prov in providers.entries:
                    pair = (prov, providers.entries[prov].api_key_env)
                    if pair not in required_provider_pairs:
                        required_provider_pairs.append(pair)

    for prov, env_var in required_provider_pairs:
        if not os.environ.get(env_var):
            typer.echo(
                f"error: {env_var} env var is not set (required for provider {prov!r})",
                err=True,
            )
            raise typer.Exit(code=1)

    # LiteLLM identifies providers by a `provider/model` prefix. If the
    # resolved model name is bare (no slash), prepend the configured default
    # provider — so `gemini-2.5-flash` becomes `gemini/gemini-2.5-flash`.
    # Names that already carry a provider prefix (`anthropic/claude-...`) or
    # match a logical model name are respected.
    if providers.use_litellm and "/" not in model and model not in providers.logical_models:
        model = f"{providers.default}/{model}"

    device = UIAutomatorDevice.connect(chosen)
    if not providers.use_litellm:
        client = GoogleGenaiClient()
    elif throttler.enabled:
        client = LiteLLMRouterClient(cfg)
    else:
        client = LiteLLMClient()
    runs_dir.mkdir(parents=True, exist_ok=True)

    outcome = run_task(
        task=task,
        device=device,
        client=client,
        model=model,
        runs_root=runs_dir,
        max_turns=max_turns,
        wall_clock_s=wall_clock,
        quantize_screenshots=cfg.perception.screenshot_quantized,
        viewport_filter=cfg.perception.viewport_filter,
        resource_id_in_render=cfg.perception.resource_id_in_render,
        sibling_collapse=cfg.perception.sibling_collapse,
        policy=policy,
        confirmer=confirmer,
    )
    typer.echo(f"run dir: {outcome.run_dir}")
    typer.echo(f"status:  {outcome.status}")
    typer.echo(f"success: {outcome.success}")
    typer.echo(f"reason:  {outcome.reason}")
    typer.echo(f"turns:   {outcome.turns}")
    sys.exit(0 if outcome.success else 1)


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
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Host to bind. Leave on 127.0.0.1 (no auth)."
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help=(
            "Path to config.yaml. Defaults to $ANDROIDHARNESS_CONFIG"
            " or ~/.androidharness/config.yaml."
        ),
    ),
) -> None:
    """Run the Settings UI (browser-based config editor)."""
    try:
        from androidharness.web.app import create_app
    except ModuleNotFoundError as e:
        if e.name in _WEB_EXTRA_PACKAGES:
            typer.echo(
                "the `serve` command needs the optional [web] extra:\n"
                "    uv add 'androidharness[web]'\n"
                "    # or: pip install 'androidharness[web]'"
            )
            raise typer.Exit(code=1) from e
        raise

    try:
        import uvicorn
    except ModuleNotFoundError as e:
        typer.echo(
            "the `serve` command needs the optional [web] extra (uvicorn missing):\n"
            "    uv add 'androidharness[web]'"
        )
        raise typer.Exit(code=1) from e

    config_path = _resolve_config_path(config)
    app_obj = create_app(config_path)
    typer.echo(f"AndroidHarness Settings UI — editing {config_path}")
    typer.echo(f"open: http://{host}:{port}/")
    uvicorn.run(app_obj, host=host, port=port, log_level="info")


if __name__ == "__main__":
    app()
