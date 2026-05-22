# Development

## Setup

```bash
uv sync          # install runtime + dev deps into .venv
```

Dev dependencies (`pytest`, `ruff`) are declared in `pyproject.toml` under `[dependency-groups] dev`.

## Running tests

```bash
uv run pytest                # run all tests
uv run pytest tests/test_perception.py   # one file
uv run pytest -x             # stop on first failure
```

Test configuration is in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

The integration test (`tests/test_device_integration.py`) requires a real ADB-connected device. It skips automatically when none is present; see that file for the skip guard.

## Linting and formatting

```bash
uv run ruff check .          # lint
uv run ruff check --fix .    # lint with auto-fix
uv run ruff format .         # format
```

Ruff config in `pyproject.toml`:
- Line length: 100
- Rules: `E`, `F`, `I` (imports), `B` (bugbear), `UP` (pyupgrade)
- `androidharness/cli.py` suppresses `B008` (Typer uses `Option()` in argument defaults)
- `tests/*.py` suppresses `E501` (XML fixture strings)

## Test fixtures

All shared fixtures live in `tests/conftest.py`.

### `FakeDevice`

A dataclass implementing the full `Device` Protocol. Every method appends `(method_name, args_dict)` to `calls`.

```python
from tests.conftest import FakeDevice

dev = FakeDevice(hierarchy_xml="<hierarchy rotation='0'><node .../></hierarchy>")
dev.tap(100, 200)
assert dev.calls == [("tap", {"x": 100, "y": 200})]
```

Constructor fields:
- `serial` — defaults to `"FAKE"`
- `model` — defaults to `"FakePixel"`
- `hierarchy_xml` — the XML returned by `dump_hierarchy()`
- `screenshot_bytes` — the bytes returned by `screenshot()`

### `FakeGeminiClient`

A scripted stand-in for the `LLMClient` protocol (the fixture predates the rename and the class name stuck). Constructed with a list of dicts (`{"name": str, "args": dict}`), one per expected `generate()` call. Returns them in order; raises `AssertionError` if called more times than there are entries.

```python
from tests.conftest import FakeGeminiClient

client = FakeGeminiClient([
    {"name": "tap", "args": {"id": 1}},
    {"name": "done", "args": {"success": True, "reason": "all done"}},
])
```

The `fake_gemini` pytest fixture is a factory function — call it with your list:

```python
def test_something(fake_device, fake_gemini):
    client = fake_gemini([
        {"name": "done", "args": {"success": True, "reason": "done"}},
    ])
    ...
```

`FakeGeminiClient.generate_calls` accumulates every call's arguments for per-turn assertions.

## Adding a new tool

1. **Implement in `tools.py`**

   Add a branch to `execute()` (`tools.py:49`):

   ```python
   if name == "my_tool":
       # validate args
       # call device method
       return ToolResult(message="my_tool ran")
   ```

   Validate all args before calling any device method. Use `_require_id` for id args. Return `ToolError(...)` for invalid input rather than raising.

2. **Add the device method** (if needed)

   Add the method signature to the `Device` Protocol (`device.py:14`) and implement it in `UIAutomatorDevice` (`device.py:68`). Also add a no-op implementation to `FakeDevice` in `tests/conftest.py` that appends to `self.calls`.

3. **Register in `GEMINI_FUNCTION_DECLARATIONS`** (`tools.py:144`)

   Add an entry following the existing pattern:

   ```python
   {
       "name": "my_tool",
       "description": "...",
       "parameters": {
           "type": "OBJECT",
           "properties": { ... },
           "required": ["arg1"],
       },
   }
   ```

   The description is what the model sees. Be specific about semantics — the model uses this to decide when to call the tool.

4. **Write tests**

   Add test cases to `tests/test_tools.py` covering valid input, invalid id, and any arg validation branches. For device-integration behavior, add to `tests/test_device_integration.py` with an appropriate skip guard.

## Project layout quick reference

```
androidharness/
  __init__.py      version string
  cli.py           Typer app — commands: devices, run, config *
  config.py        Pydantic schema + load/save
  agent.py         Agent loop, SYSTEM_PROMPT
  llm.py           LLMClient Protocol + LiteLLMClient + GoogleGenaiClient
  tools.py         execute() + GEMINI_FUNCTION_DECLARATIONS
  perception.py    XML → Observation (Node list)
  device.py        Device protocol + UIAutomatorDevice
  runner.py        run_task() — artifact I/O
  imaging.py       quantize_png()
  logging_setup.py setup_logging() — file + stderr stream
tests/
  conftest.py      FakeDevice, FakeGeminiClient fixtures
  test_*.py        unit + integration tests
runs/              per-run artifact directories (git-ignored)
logs/              rotating log files (git-ignored)
docs/              user-facing docs (this tree)
  superpowers/
    specs/         design docs — do not edit
    plans/         implementation plans — do not edit
```
