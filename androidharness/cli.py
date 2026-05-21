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
from androidharness.logging_setup import setup_file_logging
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
        policy=policy,
        confirmer=confirmer,
    )
    typer.echo(f"run dir: {outcome.run_dir}")
    typer.echo(f"status:  {outcome.status}")
    typer.echo(f"success: {outcome.success}")
    typer.echo(f"reason:  {outcome.reason}")
    typer.echo(f"turns:   {outcome.turns}")
    sys.exit(0 if outcome.success else 1)


if __name__ == "__main__":
    app()
