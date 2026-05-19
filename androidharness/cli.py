from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import typer

from androidharness.agent import GoogleGenaiClient
from androidharness.device import UIAutomatorDevice, list_devices
from androidharness.runner import run_task

app = typer.Typer(add_completion=False, help="AI harness for Android devices.")


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
    serial: Optional[str] = typer.Option(None, "--serial", "-s"),
    device_index: Optional[int] = typer.Option(None, "--device-index", "-i"),
    model: str = typer.Option("gemini-2.5-flash", "--model"),
    max_turns: int = typer.Option(40, "--max-turns"),
    wall_clock: float = typer.Option(600.0, "--wall-clock"),
    runs_dir: Path = typer.Option(Path("./runs"), "--run-dir"),
) -> None:
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


if __name__ == "__main__":
    app()
