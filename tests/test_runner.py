import json
from pathlib import Path

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
    client = fake_gemini([
        {"name": "tap", "args": {"id": 1}},
        {"name": "done", "args": {"success": True, "reason": "ok"}},
    ])
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
    client = fake_gemini([
        {"name": "show_screen", "args": {}},
        {"name": "done", "args": {"success": True, "reason": "ok"}},
    ])
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
