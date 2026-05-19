from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from androidharness.agent import Agent, GeminiClient


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


def run_task(
    *,
    task: str,
    device: Any,
    client: GeminiClient,
    model: str,
    runs_root: Path,
    max_turns: int = 40,
    wall_clock_s: float = 600.0,
) -> RunOutcome:
    run_dir = _new_run_dir(runs_root)
    start = time.time()

    agent = Agent(
        device=device,
        client=client,
        model=model,
        max_turns=max_turns,
        wall_clock_s=wall_clock_s,
    )

    result = agent.run(task)

    # Persist turn-by-turn log; pull screenshots out of observation payloads if present.
    with (run_dir / "turns.jsonl").open("w") as f:
        for turn in result.turn_log:
            screenshot_bytes = None
            obs_payload = turn.get("observation_payload")
            if isinstance(obs_payload, dict):
                screenshot_bytes = obs_payload.pop("screenshot", None)
            if screenshot_bytes:
                ss_path = run_dir / "screenshots" / f"turn-{turn['turn']:03d}.png"
                ss_path.write_bytes(screenshot_bytes)
                turn["screenshot_path"] = str(ss_path.relative_to(run_dir))
            f.write(json.dumps(turn, default=str) + "\n")

    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "task": task,
                "model": model,
                "device": {"serial": device.serial, "model": device.model},
                "started_at": start,
                "ended_at": time.time(),
                "max_turns": max_turns,
                "wall_clock_s": wall_clock_s,
            },
            indent=2,
        )
    )

    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "status": result.status,
                "success": result.success,
                "reason": result.reason,
                "turns": result.turns,
            },
            indent=2,
        )
    )

    return RunOutcome(
        run_dir=str(run_dir),
        status=result.status,
        success=result.success,
        reason=result.reason,
        turns=result.turns,
    )
