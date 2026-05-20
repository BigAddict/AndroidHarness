
from androidharness.agent import Agent, RunResult

HIERARCHY = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node bounds="[0,0][1080,2400]" class="android.widget.FrameLayout" clickable="false">
    <node bounds="[40,200][520,320]" class="android.widget.Button" text="Settings" clickable="true"/>
  </node>
</hierarchy>
"""


def test_agent_stops_on_done_success(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    result = agent.run("open settings")
    assert isinstance(result, RunResult)
    assert result.status == "done"
    assert result.success is True
    assert result.reason == "ok"
    assert result.turns == 2


def test_agent_returns_max_turns_when_budget_exhausted(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini([{"name": "tap", "args": {"id": 1}}] * 3)
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=3)
    result = agent.run("loop forever")
    assert result.status == "max_turns"
    assert result.success is None
    assert result.turns == 3


def test_agent_validation_error_becomes_tool_result_turn(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 999}},  # invalid
            {"name": "done", "args": {"success": False, "reason": "gave up"}},
        ]
    )
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    result = agent.run("try a bad id")
    assert result.status == "done"
    assert result.success is False
    # The validation error must have been surfaced back to the model as a tool result.
    second_call_contents = client.generate_calls[1]["contents"]
    rendered = "\n".join(part for turn in second_call_contents for part in [str(turn)])
    assert "999" in rendered


def test_agent_show_screen_attaches_screenshot_next_turn(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    fake_device.screenshot_bytes = b"PNGDATA"
    client = fake_gemini(
        [
            {"name": "show_screen", "args": {}},
            {"name": "done", "args": {"success": True, "reason": "saw screen"}},
        ]
    )
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    agent.run("look")
    # Turn 1 should not have screenshotted yet.
    assert ("screenshot", {}) not in fake_device.calls[:1]
    # By the time of the 2nd generate, a screenshot was taken.
    assert ("screenshot", {}) in fake_device.calls


def test_agent_records_each_turn(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    result = agent.run("open settings")
    assert len(result.turn_log) == 2
    assert result.turn_log[0]["tool_call"]["name"] == "tap"
    assert result.turn_log[1]["tool_call"]["name"] == "done"
    assert "observation_summary" in result.turn_log[0]
    assert "tool_result" in result.turn_log[0]


def test_agent_device_exception_becomes_tool_error_and_run_continues(
    fake_device, fake_gemini
):
    """A device-driver exception during a tool call must NOT crash the run. It
    must surface back to the model as a tool_result with ok=False so the agent
    can react. The run keeps looping."""
    fake_device.hierarchy_xml = HIERARCHY

    def boom(*args, **kwargs):
        raise RuntimeError("simulated device crash")

    fake_device.tap = boom

    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": False, "reason": "after boom"}},
        ]
    )
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    result = agent.run("trigger crash")

    assert result.status == "done"
    assert len(result.turn_log) == 2
    tr = result.turn_log[0]["tool_result"]
    assert tr["ok"] is False
    assert "RuntimeError" in tr["message"] or "simulated device crash" in tr["message"]


def test_agent_invokes_on_turn_callback_per_turn(fake_device, fake_gemini):
    """Caller can pass on_turn=... to receive each turn as soon as it completes,
    enabling incremental persistence."""
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    seen: list[dict] = []
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    agent.run("ok", on_turn=lambda t: seen.append(dict(t)))

    assert [t["turn"] for t in seen] == [1, 2]
    assert seen[0]["tool_call"]["name"] == "tap"
    assert seen[1]["tool_call"]["name"] == "done"


def test_no_progress_warning_injected_after_3_identical_stalled_turns(
    fake_device, fake_gemini
):
    # FakeDevice returns the same hierarchy on every dump → observation never changes.
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},  # turn 1
            {"name": "tap", "args": {"id": 1}},  # turn 2
            {"name": "tap", "args": {"id": 1}},  # turn 3 — completes the 3x stall window
            {"name": "tap", "args": {"id": 1}},  # turn 4 — warning must be in contents now
            {"name": "done", "args": {"success": False, "reason": "gave up"}},
        ]
    )
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    agent.run("stuck")
    fourth_call_contents = client.generate_calls[3]["contents"]
    serialized = " ".join(str(c) for c in fourth_call_contents)
    assert "NO_PROGRESS" in serialized

    # And the first call should NOT have a warning — nothing to detect yet.
    first_call_contents = client.generate_calls[0]["contents"]
    assert "NO_PROGRESS" not in " ".join(str(c) for c in first_call_contents)
