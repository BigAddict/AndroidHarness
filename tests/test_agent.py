
from androidharness.agent import Agent, RunResult
from androidharness.config import PolicyConfig
from androidharness.policy import (
    AlwaysApproveConfirmer,
    AlwaysRejectConfirmer,
    Policy,
    RecordingConfirmer,
)

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


def test_agent_empty_exception_message_includes_source_frame(fake_device, fake_gemini):
    """Bare AssertionError (no message) used to produce 'AssertionError:' with
    a trailing empty colon — useless to the model. The formatter must now fall
    back to the originating file:line so the model has something to act on."""
    fake_device.hierarchy_xml = HIERARCHY

    def assert_no_message(*args, **kwargs):
        # Raise directly so pytest's assertion rewriter does not inject a
        # message. Mirrors uiautomator2's `assert y >= 0` after the rewriter
        # is out of the picture (production code).
        raise AssertionError

    fake_device.scroll = assert_no_message

    client = fake_gemini(
        [
            {"name": "scroll", "args": {"id": 1, "direction": "down"}},
            {"name": "done", "args": {"success": False, "reason": "stop"}},
        ]
    )
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    result = agent.run("trigger bare assert")

    msg = result.turn_log[0]["tool_result"]["message"]
    assert msg.endswith(":") is False, f"trailing-colon-only message: {msg!r}"
    assert "AssertionError" in msg
    # The originating frame must be cited.
    assert " at " in msg and ".py:" in msg


def test_agent_quantizes_screenshot_when_enabled(fake_device, fake_gemini):
    """With quantize_screenshots=True, the screenshot in obs_payload should be
    the quantized PNG, not the raw bytes from the device."""
    import io

    from PIL import Image

    # Build a valid PNG so quantize_png can decode it.
    img = Image.new("RGB", (16, 16), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw_png = buf.getvalue()

    fake_device.hierarchy_xml = HIERARCHY
    fake_device.screenshot_bytes = raw_png

    client = fake_gemini(
        [
            {"name": "show_screen", "args": {}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    agent = Agent(
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        max_turns=10,
        quantize_screenshots=True,
    )
    result = agent.run("look")

    # Turn 2's observation_payload (the one with the screenshot) should have
    # the quantized image, not the raw bytes.
    turn2_payload = result.turn_log[1]["observation_payload"]
    assert "screenshot" in turn2_payload
    assert turn2_payload["screenshot"] != raw_png
    # Quantized PNG decodes to a P-mode image.
    decoded = Image.open(io.BytesIO(turn2_payload["screenshot"]))
    assert decoded.mode == "P"


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


def test_agent_default_policy_passes_calls_through_unchanged(fake_device, fake_gemini):
    """Existing behavior preservation: with the default permissive Policy,
    the agent dispatches every tool call to the device, just like before."""
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    agent = Agent(device=fake_device, client=client, model="gemini-2.5-flash", max_turns=10)
    result = agent.run("open settings")
    assert result.status == "done"
    # The tap actually reached the device.
    assert any(c[0] == "tap" for c in fake_device.calls)


def test_agent_confirm_mode_asks_confirmer_and_routes_rejection_back(
    fake_device, fake_gemini
):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "type", "args": {"id": 1, "text": "secret"}},
            {"name": "done", "args": {"success": False, "reason": "rejected"}},
        ]
    )
    confirmer = RecordingConfirmer(answers=[False])
    agent = Agent(
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        max_turns=10,
        policy=Policy.from_config(PolicyConfig(per_tool={"type": "confirm"})),
        confirmer=confirmer,
    )
    result = agent.run("type some text")

    assert result.status == "done"
    # The confirmer was called once with the type call.
    assert len(confirmer.calls) == 1
    assert confirmer.calls[0].name == "type"
    # The device was NEVER asked to type — the policy blocked it.
    assert not any(c[0] == "type_text" for c in fake_device.calls)
    # The rejection reached the model as a tool_result with ok=False.
    second_call_contents = client.generate_calls[1]["contents"]
    rendered = " ".join(str(c) for c in second_call_contents)
    assert "user rejected" in rendered.lower()


def test_agent_dry_run_mode_short_circuits_and_marks_ok_true(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": True, "reason": "dry-ran"}},
        ]
    )
    agent = Agent(
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        max_turns=10,
        policy=Policy.from_config(PolicyConfig(per_tool={"tap": "dry-run"})),
        confirmer=AlwaysRejectConfirmer(),
    )
    result = agent.run("tap something")

    assert result.status == "done"
    # The device was NEVER tapped.
    assert not any(c[0] == "tap" for c in fake_device.calls)
    # The tool_result the model saw was ok=True.
    tr = result.turn_log[0]["tool_result"]
    assert tr["ok"] is True
    assert "dry-run" in tr["message"].lower()


def test_agent_deny_mode_short_circuits_and_marks_ok_false(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "tap", "args": {"id": 1}},
            {"name": "done", "args": {"success": False, "reason": "denied"}},
        ]
    )
    agent = Agent(
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        max_turns=10,
        policy=Policy.from_config(PolicyConfig(per_tool={"tap": "deny"})),
        confirmer=AlwaysApproveConfirmer(),
    )
    result = agent.run("tap something")

    assert not any(c[0] == "tap" for c in fake_device.calls)
    tr = result.turn_log[0]["tool_result"]
    assert tr["ok"] is False
    assert "deny" in tr["message"].lower()


def test_agent_confirm_approved_lets_call_through_to_device(fake_device, fake_gemini):
    fake_device.hierarchy_xml = HIERARCHY
    client = fake_gemini(
        [
            {"name": "type", "args": {"id": 1, "text": "hi"}},
            {"name": "done", "args": {"success": True, "reason": "ok"}},
        ]
    )
    agent = Agent(
        device=fake_device,
        client=client,
        model="gemini-2.5-flash",
        max_turns=10,
        policy=Policy.from_config(PolicyConfig(per_tool={"type": "confirm"})),
        confirmer=AlwaysApproveConfirmer(),
    )
    agent.run("type some text")
    assert any(c[0] == "type_text" for c in fake_device.calls)
