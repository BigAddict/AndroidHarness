from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from androidharness import __version__
from androidharness.agent import Agent
from androidharness.llm import LLMClient


@dataclass
class RunOutcome:
    run_dir: str
    status: str
    success: bool | None
    reason: str
    turns: int


def _new_run_dir(root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    short = secrets.token_hex(3)
    p = root / f"{stamp}-{short}"
    p.mkdir(parents=True, exist_ok=False)
    (p / "screenshots").mkdir()
    return p


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2))


def run_task(
    *,
    task: str,
    device: Any,
    client: LLMClient,
    model: str,
    runs_root: Path,
    max_turns: int = 40,
    wall_clock_s: float = 600.0,
    quantize_screenshots: bool = False,
    viewport_filter: bool = False,
    resource_id_in_render: bool = False,
) -> RunOutcome:
    run_dir = _new_run_dir(runs_root)
    start = time.time()

    # Persist meta.json BEFORE the run starts so the run is discoverable even
    # if the loop crashes with no exception handler firing.
    meta: dict[str, Any] = {
        "harness_version": __version__,
        "task": task,
        "model": model,
        "device": {"serial": device.serial, "model": device.model},
        "started_at": start,
        "max_turns": max_turns,
        "wall_clock_s": wall_clock_s,
        "status": "running",
    }
    _write_json(run_dir / "meta.json", meta)

    turns_path = run_dir / "turns.jsonl"
    turns_file = turns_path.open("w")

    def write_turn(turn: dict) -> None:
        # Copy so popping the screenshot doesn't mutate the agent's in-memory log.
        turn = dict(turn)
        obs_payload = turn.get("observation_payload")
        screenshot_bytes = None
        if isinstance(obs_payload, dict):
            obs_payload = dict(obs_payload)
            screenshot_bytes = obs_payload.pop("screenshot", None)
            turn["observation_payload"] = obs_payload
        if screenshot_bytes:
            ss_path = run_dir / "screenshots" / f"turn-{turn['turn']:03d}.png"
            ss_path.write_bytes(screenshot_bytes)
            turn["screenshot_path"] = str(ss_path.relative_to(run_dir))
        turns_file.write(json.dumps(turn, default=str) + "\n")
        turns_file.flush()

    agent = Agent(
        device=device,
        client=client,
        model=model,
        max_turns=max_turns,
        wall_clock_s=wall_clock_s,
        quantize_screenshots=quantize_screenshots,
        viewport_filter=viewport_filter,
        resource_id_in_render=resource_id_in_render,
    )

    try:
        result = agent.run(task, on_turn=write_turn)
    except BaseException as e:
        turns_file.close()
        meta["ended_at"] = time.time()
        meta["status"] = "crashed"
        _write_json(run_dir / "meta.json", meta)
        _write_json(
            run_dir / "result.json",
            {
                "status": "crashed",
                "success": False,
                "reason": f"{type(e).__name__}: {e}",
                "turns": sum(1 for _ in turns_path.open()),
            },
        )
        raise
    finally:
        if not turns_file.closed:
            turns_file.close()

    meta["ended_at"] = time.time()
    meta["status"] = result.status
    _write_json(run_dir / "meta.json", meta)

    _write_json(
        run_dir / "result.json",
        {
            "status": result.status,
            "success": result.success,
            "reason": result.reason,
            "turns": result.turns,
        },
    )

    return RunOutcome(
        run_dir=str(run_dir),
        status=result.status,
        success=result.success,
        reason=result.reason,
        turns=result.turns,
    )
