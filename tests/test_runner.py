import json
from pathlib import Path

import pytest

from androidharness.runner import run_task

HIERARCHY = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[40,200][520,320]" class="android.widget.Button" text="Settings" clickable="true"/>
  </node>
</hierarchy>
"""


def test_run_task_writes_meta_turns_and_result(tmp_path, fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    result = run_task(
        task="open settings",
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        runs_root=tmp_path,
    )
    run_dir = Path(result.run_dir)
    assert run_dir.exists()
    assert run_dir.parent == tmp_path

    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["task"] == "open settings"
    assert meta["model"] == "gemini-2.5-flash"
    assert meta["device"]["serial"] == "FAKE"
    assert meta["device"]["model"] == "FakePixel"

    final = json.loads((run_dir / "result.json").read_text())
    assert final["status"] == "done"
    assert final["success"] is True
    assert final["reason"] == "ok"

    lines = (run_dir / "turns.jsonl").read_text().splitlines()
    assert len(lines) == 2
    turn0 = json.loads(lines[0])
    assert turn0["tool_call"]["name"] == "tap"


def test_run_task_writes_screenshot_only_when_requested(tmp_path, fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    fake_device.screenshot_bytes = b"PNGDATA"
    client = fake_gemini(
        [
            {"name": "show_screen", "args": {}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    result = run_task(
        task="look",
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        runs_root=tmp_path,
    )
    run_dir = Path(result.run_dir)
    screenshots = list((run_dir / "screenshots").glob("*.png"))
    assert len(screenshots) == 1
    assert screenshots[0].read_bytes() == b"PNGDATA"


def test_run_task_persists_turns_incrementally_on_crash(tmp_path, fake_device):
    """If the LLM client raises mid-run, turns completed before the crash must
    survive to disk. meta.json must exist. A crash result.json must be written."""
    fake_device.hierarchy_xml = HIERARCHY

    class CrashingClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            if self.calls >= 2:
                raise RuntimeError("simulated LLM outage")
            return {"name": "tap", "args": {"id": 1}}

    with pytest.raises(RuntimeError, match="simulated LLM outage"):
        run_task(
            task="crash on turn 2",
            device=fake_device,
            client=CrashingClient(),
            model="gemini-2.5-flash",
            runs_root=tmp_path,
        )

    run_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1
    rd = run_dirs[0]

    meta = json.loads((rd / "meta.json").read_text())
    assert meta["task"] == "crash on turn 2"

    lines = (rd / "turns.jsonl").read_text().splitlines()
    assert len(lines) == 1
    turn0 = json.loads(lines[0])
    assert turn0["tool_call"]["name"] == "tap"

    crash_result = json.loads((rd / "result.json").read_text())
    assert crash_result["status"] == "crashed"
    assert "simulated LLM outage" in crash_result["reason"]


def test_run_task_captures_effective_policy_in_meta(tmp_path, fake_device, fake_gemini):
    """meta.json must snapshot the policy that was in effect for the run so
    two artifacts of the same task under different gates are distinguishable.
    The snapshot uses the same string mode values that round-trip via YAML."""
    from androidharness.config import PolicyConfig
    from androidharness.policy import Policy

    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    result = run_task(
        task="t",
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        runs_root=tmp_path,
        policy=Policy.from_config(
            PolicyConfig(default_mode="auto", per_tool={"type": "deny", "tap": "confirm"})
        ),
    )
    meta = json.loads((Path(result.run_dir) / "meta.json").read_text())
    assert meta["policy"] == {
        "default_mode": "auto",
        "per_tool": {"type": "deny", "tap": "confirm"},
    }


def test_run_task_meta_policy_uses_defaults_when_no_policy_passed(tmp_path, fake_device, fake_gemini):
    """When the caller passes no policy, the recorded snapshot is the
    permissive default (auto, empty per_tool) — NOT the spec-mandated
    PolicyConfig defaults, because run_task only sees the bare Policy()."""
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    result = run_task(
        task="t",
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        runs_root=tmp_path,
    )
    meta = json.loads((Path(result.run_dir) / "meta.json").read_text())
    assert meta["policy"]["default_mode"] == "auto"
    assert meta["policy"]["per_tool"] == {}
