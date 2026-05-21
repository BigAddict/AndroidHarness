# v2 Milestone 3 — Throttler + LiteLLM Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add proactive rate-limit survival (per-`(provider, model)` token buckets) and reactive failover (ordered fallback chains) by wiring LiteLLM's `Router` behind a new `LiteLLMRouterClient` selectable via config.

**Architecture:**

The token-bucket logic and the fallback-on-429 logic both live inside LiteLLM's `Router` — we configure it rather than reinvent it. A new `LiteLLMRouterClient` in `androidharness/llm.py` instantiates `litellm.Router(...)` from `AndroidHarnessConfig` and exposes the same `LLMClient.generate(...)` shape as `LiteLLMClient`. The CLI picks `LiteLLMRouterClient` when `throttler.enabled` is true; otherwise it keeps the direct `LiteLLMClient`. Logical model names (`fast`, `smart`, …) are defined as fallback chains in `providers.logical_models` and resolved at call time by the Router.

**Tech Stack:** `litellm.Router` (already in `litellm>=1.50.0`), Pydantic v2, Typer, pytest with `monkeypatch` of `Router.completion` (mirrors the Task 5 pattern from milestone 2).

**Spec:** `docs/superpowers/specs/2026-05-20-v2-stack-and-scale-design.md` §3 + roadmap item #3.

---

## File Structure

| Path | Purpose |
|---|---|
| `androidharness/config.py` | Modify — flesh out `ThrottlerConfig` (`enabled`, `cooldown_seconds`, `num_retries`, `buckets: dict[str, BucketConfig]`); add `BucketConfig` (`rpm`, `tpm`); add `logical_models: dict[str, list[str]]` to `ProvidersConfig`; validate that every fallback in a logical-model chain is either a known provider-prefixed model or already has a bucket entry. |
| `androidharness/llm.py` | Modify — add `_build_router_kwargs(cfg) -> dict` helper (returns `model_list`, `fallbacks`, `cooldown_time`, `num_retries`) and `LiteLLMRouterClient` class that wraps `litellm.Router` and implements the `LLMClient` Protocol. |
| `androidharness/cli.py` | Modify — when `cfg.throttler.enabled` is true, instantiate `LiteLLMRouterClient(cfg)` instead of `LiteLLMClient()`. Keep the env-var check; expand it so every provider referenced by a logical-model chain has its `api_key_env` set. |
| `tests/test_config.py` | Modify — extend with tests for `BucketConfig`, fleshed-out `ThrottlerConfig`, and `ProvidersConfig.logical_models`. |
| `tests/test_llm.py` | Modify — add tests for `_build_router_kwargs` and `LiteLLMRouterClient.generate`. |
| `tests/test_cli_run_config.py` | Modify — add tests for `throttler.enabled` selecting the Router client and for the multi-provider env-var check. |
| `docs/configuration.md` | Modify — document `throttler.enabled`/`cooldown_seconds`/`num_retries`/`buckets` and `providers.logical_models`. |
| `docs/architecture.md` | Modify — mention `LiteLLMRouterClient` alongside `LiteLLMClient` in the LLM-seam paragraph. |
| `docs/roadmap.md` | Modify — mark milestone 3 as Shipped with the new commit SHAs. |
| `docs/getting-started.md` | Modify — one short paragraph under "Key CLI flags" pointing at logical model names + the throttler. |

Existing `androidharness/agent.py`, `androidharness/runner.py`, `androidharness/perception.py`, `androidharness/tools.py`, `androidharness/device.py`, `androidharness/imaging.py` are **untouched** by this milestone. The agent loop continues to bind to `LLMClient`; both `LiteLLMClient` and the new `LiteLLMRouterClient` satisfy the Protocol.

---

## Task 1: Flesh out `ThrottlerConfig` + add `BucketConfig`

**Files:**
- Modify: `androidharness/config.py`
- Test: `tests/test_config.py`

The on-disk shape we're committing to:

```yaml
throttler:
  enabled: false
  cooldown_seconds: 60
  num_retries: 2
  buckets:
    gemini/gemini-2.5-flash:
      rpm: 10
      tpm: 250000
    anthropic/claude-haiku-4-5:
      rpm: 30
    openai/gpt-4o-mini:
      rpm: 60
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
from androidharness.config import BucketConfig, ThrottlerConfig


def test_throttler_config_defaults_are_off():
    t = ThrottlerConfig()
    assert t.enabled is False
    assert t.cooldown_seconds == 60
    assert t.num_retries == 2
    assert t.buckets == {}


def test_bucket_config_rpm_and_tpm_optional():
    b = BucketConfig()
    assert b.rpm is None
    assert b.tpm is None


def test_bucket_config_rejects_zero_or_negative():
    with pytest.raises(ValidationError):
        BucketConfig(rpm=0)
    with pytest.raises(ValidationError):
        BucketConfig(tpm=-1)


def test_throttler_config_round_trips_buckets_through_yaml(tmp_path):
    yaml_text = """\
version: 1
throttler:
  enabled: true
  cooldown_seconds: 30
  num_retries: 1
  buckets:
    gemini/gemini-2.5-flash:
      rpm: 10
      tpm: 250000
    anthropic/claude-haiku-4-5:
      rpm: 30
"""
    p = tmp_path / "c.yaml"
    p.write_text(yaml_text)
    cfg = load_config(p)
    assert cfg.throttler.enabled is True
    assert cfg.throttler.cooldown_seconds == 30
    assert cfg.throttler.num_retries == 1
    assert cfg.throttler.buckets["gemini/gemini-2.5-flash"].rpm == 10
    assert cfg.throttler.buckets["gemini/gemini-2.5-flash"].tpm == 250000
    assert cfg.throttler.buckets["anthropic/claude-haiku-4-5"].tpm is None
```

(Merge the new imports into the existing `from androidharness.config import (...)` block at the top of `tests/test_config.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v -k throttler`
Expected: 4 failures (`ImportError: cannot import name 'BucketConfig'`, plus the fleshed-out fields not yet on `ThrottlerConfig`).

- [ ] **Step 3: Replace `ThrottlerConfig` and add `BucketConfig` in `androidharness/config.py`**

Find the existing `ThrottlerConfig` placeholder block (`class ThrottlerConfig(BaseModel):` followed by `enabled: bool = False` and `buckets: dict[str, dict] = Field(default_factory=dict)`). Replace it with:

```python
class BucketConfig(BaseModel):
    """Per-(provider, model) rate-limit budget. None means 'no limit'."""
    model_config = _STRICT

    rpm: int | None = Field(default=None, gt=0)
    tpm: int | None = Field(default=None, gt=0)


class ThrottlerConfig(BaseModel):
    """Token-bucket + fallback config (milestone 3).

    Routes every LLM call through `litellm.Router` when `enabled`. Each entry
    in `buckets` is keyed by the concrete LiteLLM-shaped model id
    (`provider/model`) and gives that deployment's RPM / TPM budget. The
    Router cools a deployment down for `cooldown_seconds` after a rate-limit
    error, retrying via the next entry in the matching `logical_models` chain.
    """

    model_config = _STRICT

    enabled: bool = False
    cooldown_seconds: int = Field(default=60, gt=0)
    num_retries: int = Field(default=2, ge=0)
    buckets: dict[str, BucketConfig] = Field(default_factory=dict)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -v -k throttler`
Expected: all 4 new tests pass.

- [ ] **Step 5: Full suite + ruff**

Run: `uv run pytest -q`
Expected: 116 + 4 = 120 passing (give or take).

Run: `uv run ruff check androidharness/ tests/`
Expected: `All checks passed!`. Auto-fix if it complains.

- [ ] **Step 6: Commit**

```bash
git add androidharness/config.py tests/test_config.py
git commit -m "feat(config): BucketConfig + flesh out ThrottlerConfig (rpm/tpm/cooldown/retries)"
```

---

## Task 2: Add `logical_models` to `ProvidersConfig`

**Files:**
- Modify: `androidharness/config.py`
- Test: `tests/test_config.py`

A logical model name (`fast`, `smart`, `cheap`, …) maps to an ordered list of concrete `provider/model` ids. The first entry is the primary; the rest are fallbacks consulted when the primary errors with a rate-limit / quota signal.

```yaml
providers:
  use_litellm: true
  default: gemini
  entries: ...
  logical_models:
    fast:
      - gemini/gemini-2.5-flash
      - anthropic/claude-haiku-4-5
      - openai/gpt-4o-mini
    smart:
      - anthropic/claude-sonnet-4-6
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_providers_logical_models_default_is_empty():
    cfg = AndroidHarnessConfig()
    assert cfg.providers.logical_models == {}


def test_providers_logical_models_round_trip(tmp_path):
    yaml_text = """\
version: 1
providers:
  logical_models:
    fast:
      - gemini/gemini-2.5-flash
      - anthropic/claude-haiku-4-5
"""
    p = tmp_path / "c.yaml"
    p.write_text(yaml_text)
    cfg = load_config(p)
    assert cfg.providers.logical_models == {
        "fast": ["gemini/gemini-2.5-flash", "anthropic/claude-haiku-4-5"],
    }


def test_providers_logical_models_rejects_empty_chain():
    """A logical model with no entries is meaningless — reject at validation."""
    with pytest.raises(ValidationError):
        ProvidersConfig(
            default="gemini",
            entries=AndroidHarnessConfig().providers.entries,
            logical_models={"fast": []},
        )


def test_providers_logical_models_rejects_bare_model_name():
    """Every entry must be in LiteLLM's `provider/model` form so it routes
    correctly. A bare `gemini-2.5-flash` (no slash) is rejected."""
    with pytest.raises(ValidationError):
        ProvidersConfig(
            default="gemini",
            entries=AndroidHarnessConfig().providers.entries,
            logical_models={"fast": ["gemini-2.5-flash"]},
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v -k logical_models`
Expected: 4 failures (`logical_models` attribute missing on `ProvidersConfig`).

- [ ] **Step 3: Extend `ProvidersConfig` in `androidharness/config.py`**

Locate the existing `ProvidersConfig` class. Add the `logical_models` field and extend `model_post_init` to validate chain entries.

Add to the field block (above `model_post_init`):

```python
    logical_models: dict[str, list[str]] = Field(default_factory=dict)
```

Replace the existing `model_post_init` body with:

```python
    def model_post_init(self, __context) -> None:  # noqa: D401  (pydantic hook)
        if self.default not in self.entries:
            raise ValueError(
                f"providers.default={self.default!r} is not a key in providers.entries "
                f"(have: {sorted(self.entries)})"
            )
        for name, chain in self.logical_models.items():
            if not chain:
                raise ValueError(
                    f"providers.logical_models[{name!r}] is empty — a logical model must "
                    "have at least one concrete model entry"
                )
            for entry in chain:
                if "/" not in entry:
                    raise ValueError(
                        f"providers.logical_models[{name!r}] entry {entry!r} is not in "
                        "`provider/model` form (e.g. 'gemini/gemini-2.5-flash')"
                    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -v -k logical_models`
Expected: all 4 tests pass.

- [ ] **Step 5: Full suite + ruff**

Run: `uv run pytest -q`
Expected: 120 + 4 = 124 passing.

Run: `uv run ruff check androidharness/ tests/`
Expected: `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add androidharness/config.py tests/test_config.py
git commit -m "feat(config): providers.logical_models — ordered fallback chains"
```

---

## Task 3: Add `_build_router_kwargs` helper

Translate the config into the kwargs `litellm.Router(...)` expects:
- `model_list`: one entry per (logical_name × chain_member) plus one entry per bucket key that isn't already covered. Each entry has `model_name`, `litellm_params: {model: <concrete>}`, and `rpm` / `tpm` from the matching bucket.
- `fallbacks`: a list of `{logical_name: [rest_of_chain]}` dicts.
- `cooldown_time`, `num_retries`: from `ThrottlerConfig`.

**Files:**
- Modify: `androidharness/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm.py` (merge the new import into the top-of-file block):

```python
from androidharness.config import AndroidHarnessConfig
from androidharness.llm import _build_router_kwargs


def _cfg_with(throttler: dict | None = None, providers: dict | None = None):
    """Build an AndroidHarnessConfig from partial overrides."""
    base = AndroidHarnessConfig().model_dump(mode="json")
    if throttler:
        base["throttler"].update(throttler)
    if providers:
        base["providers"].update(providers)
    return AndroidHarnessConfig.model_validate(base)


def test_build_router_kwargs_emits_one_entry_per_logical_chain_member():
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"fast": [
            "gemini/gemini-2.5-flash",
            "anthropic/claude-haiku-4-5",
        ]}},
    )
    kw = _build_router_kwargs(cfg)
    names = [m["model_name"] for m in kw["model_list"]]
    targets = [m["litellm_params"]["model"] for m in kw["model_list"]]
    assert "fast" in names
    assert "gemini/gemini-2.5-flash" in targets
    assert "anthropic/claude-haiku-4-5" in targets


def test_build_router_kwargs_applies_buckets_to_matching_entries():
    cfg = _cfg_with(
        throttler={
            "enabled": True,
            "buckets": {
                "gemini/gemini-2.5-flash": {"rpm": 10, "tpm": 250000},
            },
        },
        providers={"logical_models": {"fast": ["gemini/gemini-2.5-flash"]}},
    )
    kw = _build_router_kwargs(cfg)
    primary = next(m for m in kw["model_list"] if m["model_name"] == "fast")
    assert primary["rpm"] == 10
    assert primary["tpm"] == 250000


def test_build_router_kwargs_emits_fallbacks_map_in_chain_order():
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"fast": [
            "gemini/gemini-2.5-flash",
            "anthropic/claude-haiku-4-5",
            "openai/gpt-4o-mini",
        ]}},
    )
    kw = _build_router_kwargs(cfg)
    # Expect fallbacks = [{"fast": ["anthropic/claude-haiku-4-5", "openai/gpt-4o-mini"]}]
    assert kw["fallbacks"] == [{
        "fast": ["anthropic/claude-haiku-4-5", "openai/gpt-4o-mini"],
    }]


def test_build_router_kwargs_no_fallbacks_when_single_entry_chain():
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"only": ["gemini/gemini-2.5-flash"]}},
    )
    kw = _build_router_kwargs(cfg)
    assert kw["fallbacks"] == []


def test_build_router_kwargs_adds_bare_buckets_as_concrete_entries():
    """If a bucket names a concrete model that isn't in any logical chain,
    expose it under its own model_name so a direct `--model gemini/gemini-2.5-flash`
    call still gets throttled."""
    cfg = _cfg_with(
        throttler={
            "enabled": True,
            "buckets": {"gemini/gemini-2.5-flash": {"rpm": 10}},
        },
    )
    kw = _build_router_kwargs(cfg)
    assert any(
        m["model_name"] == "gemini/gemini-2.5-flash"
        and m["litellm_params"]["model"] == "gemini/gemini-2.5-flash"
        and m["rpm"] == 10
        for m in kw["model_list"]
    )


def test_build_router_kwargs_forwards_cooldown_and_retries():
    cfg = _cfg_with(throttler={"enabled": True, "cooldown_seconds": 90, "num_retries": 5})
    kw = _build_router_kwargs(cfg)
    assert kw["cooldown_time"] == 90
    assert kw["num_retries"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm.py -v -k build_router_kwargs`
Expected: 6 failures — `ImportError: cannot import name '_build_router_kwargs'`.

- [ ] **Step 3: Add the helper to `androidharness/llm.py`**

Append (after `_contents_to_openai_messages`, before `LiteLLMClient`):

```python
def _build_router_kwargs(cfg) -> dict:
    """Translate an AndroidHarnessConfig into kwargs for `litellm.Router(...)`.

    Produces a flat `model_list` covering:
      * Every (logical_name, concrete_model) pair from `providers.logical_models`,
        so `router.completion(model="fast")` reaches the primary then falls
        back through the chain.
      * Every entry in `providers.logical_models` chains exposed under its own
        concrete name, so direct `router.completion(model="gemini/gemini-2.5-flash")`
        also works.
      * Every key in `throttler.buckets` that isn't already covered above —
        so concrete-only buckets still get throttled when called directly.

    Rate-limit budgets from `throttler.buckets` are attached to every entry
    that targets the matching concrete model.
    """
    throttler = cfg.throttler
    providers = cfg.providers
    bucket_kwargs: dict[str, dict] = {}
    for key, b in throttler.buckets.items():
        kw: dict = {}
        if b.rpm is not None:
            kw["rpm"] = b.rpm
        if b.tpm is not None:
            kw["tpm"] = b.tpm
        bucket_kwargs[key] = kw

    model_list: list[dict] = []
    covered_concrete: set[str] = set()

    for logical_name, chain in providers.logical_models.items():
        primary = chain[0]
        # Logical-name entry → primary.
        model_list.append({
            "model_name": logical_name,
            "litellm_params": {"model": primary},
            **bucket_kwargs.get(primary, {}),
        })
        # Each concrete model also exposed under its own model_name so
        # direct calls (and Router fallback resolution) can target it.
        for concrete in chain:
            if concrete in covered_concrete:
                continue
            model_list.append({
                "model_name": concrete,
                "litellm_params": {"model": concrete},
                **bucket_kwargs.get(concrete, {}),
            })
            covered_concrete.add(concrete)

    # Bare buckets that didn't appear in any logical chain.
    for key in throttler.buckets:
        if key in covered_concrete:
            continue
        model_list.append({
            "model_name": key,
            "litellm_params": {"model": key},
            **bucket_kwargs.get(key, {}),
        })
        covered_concrete.add(key)

    fallbacks: list[dict] = []
    for logical_name, chain in providers.logical_models.items():
        rest = chain[1:]
        if rest:
            fallbacks.append({logical_name: list(rest)})

    return {
        "model_list": model_list,
        "fallbacks": fallbacks,
        "cooldown_time": throttler.cooldown_seconds,
        "num_retries": throttler.num_retries,
    }
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_llm.py -v -k build_router_kwargs`
Expected: all 6 tests pass.

- [ ] **Step 5: Full suite + ruff**

Run: `uv run pytest -q`
Expected: 124 + 6 = 130 passing.

Run: `uv run ruff check androidharness/ tests/`
Expected: `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add androidharness/llm.py tests/test_llm.py
git commit -m "feat(llm): _build_router_kwargs — config -> litellm.Router kwargs"
```

---

## Task 4: Implement `LiteLLMRouterClient.generate`

Same shape as `LiteLLMClient` — `generate(*, model, system_instruction, contents, tools) -> dict` — but instead of calling `litellm.completion(...)` it calls `self._router.completion(...)` on a `litellm.Router` instance built from config.

**Files:**
- Modify: `androidharness/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm.py`:

```python
from androidharness.llm import LiteLLMRouterClient


def test_litellm_router_client_routes_via_router_completion(monkeypatch):
    """LiteLLMRouterClient calls self._router.completion(...) — verify the
    kwargs forwarded (model, messages, tools, tool_choice) and the response
    parsing follow the same contract as LiteLLMClient."""
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"fast": ["gemini/gemini-2.5-flash"]}},
    )

    tool_call = _StubToolCall("tap", json.dumps({"id": 7}))
    resp = _StubResponse([_StubChoice(_StubMessage(tool_calls=[tool_call]))])

    client = LiteLLMRouterClient(cfg)

    captured: list[dict] = []

    def fake_router_completion(**kwargs):
        captured.append(kwargs)
        return resp

    monkeypatch.setattr(client._router, "completion", fake_router_completion)

    out = client.generate(
        model="fast",
        system_instruction="SYS",
        contents=[{"role": "user", "task": "open settings"}],
        tools=[
            {
                "name": "tap",
                "description": "Tap.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"id": {"type": "INTEGER"}},
                    "required": ["id"],
                },
            }
        ],
    )
    assert out == {"name": "tap", "args": {"id": 7}}
    assert captured[0]["model"] == "fast"
    assert captured[0]["tool_choice"] == "required"
    assert captured[0]["messages"][0] == {"role": "system", "content": "SYS"}


def test_litellm_router_client_falls_back_to_done_on_empty_choices(monkeypatch):
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"fast": ["gemini/gemini-2.5-flash"]}},
    )
    client = LiteLLMRouterClient(cfg)
    monkeypatch.setattr(client._router, "completion", lambda **kw: _StubResponse([]))

    out = client.generate(
        model="fast",
        system_instruction="SYS",
        contents=[{"role": "user", "task": "t"}],
        tools=[],
    )
    assert out["name"] == "done"
    assert out["args"]["success"] is False


def test_litellm_router_client_handles_pre_parsed_dict_args(monkeypatch):
    cfg = _cfg_with(
        throttler={"enabled": True},
        providers={"logical_models": {"fast": ["gemini/gemini-2.5-flash"]}},
    )
    client = LiteLLMRouterClient(cfg)
    tool_call = _StubToolCall("tap", {"id": 3})
    resp = _StubResponse([_StubChoice(_StubMessage(tool_calls=[tool_call]))])
    monkeypatch.setattr(client._router, "completion", lambda **kw: resp)

    out = client.generate(
        model="fast",
        system_instruction="SYS",
        contents=[{"role": "user", "task": "t"}],
        tools=[],
    )
    assert out == {"name": "tap", "args": {"id": 3}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm.py -v -k LiteLLMRouterClient`
Expected: 3 failures — `ImportError: cannot import name 'LiteLLMRouterClient'`.

- [ ] **Step 3: Implement `LiteLLMRouterClient` in `androidharness/llm.py`**

Append (after `LiteLLMClient`):

```python
class LiteLLMRouterClient:
    """LiteLLM Router-backed `LLMClient`. Same contract as `LiteLLMClient`,
    but routes through `litellm.Router` so calls get per-`(provider, model)`
    rate limiting and ordered fallback on rate-limit errors.

    The Router is built once at construction time from `_build_router_kwargs(cfg)`.
    Re-instantiate the client to pick up config changes.
    """

    def __init__(self, cfg) -> None:
        # Lazy import — see LiteLLMClient.__init__ for why.
        from litellm import Router

        kw = _build_router_kwargs(cfg)
        self._router = Router(**kw)

    def generate(
        self,
        *,
        model: str,
        system_instruction: str,
        contents: list,
        tools: list,
    ) -> dict:
        messages = _contents_to_openai_messages(
            system_instruction=system_instruction,
            contents=contents,
        )
        openai_tools = _tools_to_openai_tools(tools)

        response = self._router.completion(
            model=model,
            messages=messages,
            tools=openai_tools,
            tool_choice="required",
        )

        if not response.choices:
            _llm_log.warning("router returned zero choices for model=%s", model)
            return {
                "name": "done",
                "args": {"success": False, "reason": "model did not call a tool"},
            }

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            _llm_log.info("router: no tool_calls in response; falling back to done()")
            return {
                "name": "done",
                "args": {"success": False, "reason": "model did not call a tool"},
            }

        first = tool_calls[0]
        name = first.function.name
        raw_args = first.function.arguments
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                _llm_log.warning("router: tool args were not valid JSON: %r", raw_args)
                args = {}
        else:
            args = dict(raw_args or {})

        return {"name": name, "args": args}
```

Note: `json` and `_llm_log` are already imported at the top of `androidharness/llm.py` from milestone 2. No new imports needed.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_llm.py -v -k LiteLLMRouterClient`
Expected: all 3 tests pass.

- [ ] **Step 5: Full suite + ruff**

Run: `uv run pytest -q`
Expected: 130 + 3 = 133 passing.

Run: `uv run ruff check androidharness/ tests/`
Expected: `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add androidharness/llm.py tests/test_llm.py
git commit -m "feat(llm): LiteLLMRouterClient — Router-backed adapter with throttle + fallback"
```

---

## Task 5: Wire the CLI to pick `LiteLLMRouterClient` when `throttler.enabled`

Logic in `run_cmd`:
- If `providers.use_litellm` is False → keep `GoogleGenaiClient` (no change).
- Else if `throttler.enabled` is True → `LiteLLMRouterClient(cfg)`.
- Else → `LiteLLMClient()` (current default).

Env-var check: when the throttler is on, every provider referenced by any logical-model chain must have its `api_key_env` set. When the throttler is off, only the selected `providers.default` provider's `api_key_env` is required (current behavior).

**Files:**
- Modify: `androidharness/cli.py`
- Test: `tests/test_cli_run_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_run_config.py`:

```python
def test_cli_run_uses_router_client_when_throttler_enabled(tmp_path, monkeypatch):
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg["throttler"]["enabled"] = True
    cfg["providers"]["logical_models"] = {"fast": ["gemini/gemini-2.5-flash"]}
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")

    with patch("androidharness.cli.LiteLLMRouterClient") as router, \
         patch("androidharness.cli.LiteLLMClient") as lite, \
         patch("androidharness.cli.GoogleGenaiClient") as google, \
         patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]), \
         patch("androidharness.cli.run_task") as run_task:
        run_task.return_value = type("O", (), {
            "run_dir": "/tmp/x", "status": "done", "success": True,
            "reason": "ok", "turns": 1,
        })()
        result = runner.invoke(app, ["run", "open settings", "--config", str(cfg_path)])

    assert result.exit_code == 0, result.stdout
    router.assert_called_once()
    lite.assert_not_called()
    google.assert_not_called()


def test_cli_run_keeps_litellm_client_when_throttler_disabled(tmp_path, monkeypatch):
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg["throttler"]["enabled"] = False
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")

    with patch("androidharness.cli.LiteLLMRouterClient") as router, \
         patch("androidharness.cli.LiteLLMClient") as lite, \
         patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]), \
         patch("androidharness.cli.run_task") as run_task:
        run_task.return_value = type("O", (), {
            "run_dir": "/tmp/x", "status": "done", "success": True,
            "reason": "ok", "turns": 1,
        })()
        result = runner.invoke(app, ["run", "open settings", "--config", str(cfg_path)])

    assert result.exit_code == 0, result.stdout
    lite.assert_called_once()
    router.assert_not_called()


def test_cli_run_with_throttler_requires_keys_for_every_fallback_provider(tmp_path, monkeypatch):
    """With throttler enabled and a chain that includes anthropic, the CLI
    must require ANTHROPIC_API_KEY too — not just the default provider's key."""
    cfg = AndroidHarnessConfig().model_dump(mode="json")
    cfg["throttler"]["enabled"] = True
    cfg["providers"]["logical_models"] = {"fast": [
        "gemini/gemini-2.5-flash",
        "anthropic/claude-haiku-4-5",
    ]}
    cfg_path = _write_cfg(tmp_path, cfg)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with patch("androidharness.cli.UIAutomatorDevice.connect"), \
         patch("androidharness.cli.list_devices", return_value=[
             type("I", (), {"serial": "FAKE", "model": "FakePixel"})(),
         ]):
        result = runner.invoke(app, ["run", "open settings", "--config", str(cfg_path)])

    assert result.exit_code == 1
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "ANTHROPIC_API_KEY" in combined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_run_config.py -v -k "router_client or throttler or fallback_provider"`
Expected: 3 failures (`LiteLLMRouterClient` not importable from `androidharness.cli`, no multi-provider env-var check).

- [ ] **Step 3: Modify `androidharness/cli.py`**

Widen the import:

```python
from androidharness.llm import GoogleGenaiClient, LiteLLMClient, LiteLLMRouterClient
```

Find the block in `run_cmd` (currently around lines 161-183 in the working tree) that reads:

```python
    providers = cfg.providers
    if providers.default not in providers.entries:
        typer.echo(
            f"error: providers.default={providers.default!r} not found in providers.entries",
            err=True,
        )
        raise typer.Exit(code=1)
    selected = providers.entries[providers.default]
    if not os.environ.get(selected.api_key_env):
        typer.echo(
            f"error: {selected.api_key_env} env var is not set "
            f"(required for providers.default={providers.default!r})",
            err=True,
        )
        raise typer.Exit(code=1)

    # LiteLLM identifies providers by a `provider/model` prefix. If the
    # resolved model name is bare (no slash), prepend the selected provider —
    # so `gemini-2.5-flash` becomes `gemini/gemini-2.5-flash`. Names that
    # already carry a provider prefix (`anthropic/claude-...`) are respected.
    if providers.use_litellm and "/" not in model:
        model = f"{providers.default}/{model}"

    device = UIAutomatorDevice.connect(chosen)
    client = LiteLLMClient() if providers.use_litellm else GoogleGenaiClient()
```

Replace with:

```python
    providers = cfg.providers
    throttler = cfg.throttler
    if providers.default not in providers.entries:
        typer.echo(
            f"error: providers.default={providers.default!r} not found in providers.entries",
            err=True,
        )
        raise typer.Exit(code=1)

    # Determine which provider keys are required. When the throttler is on,
    # every provider referenced by any logical-model chain needs its key —
    # otherwise the Router's fallback list contains deployments we can't
    # actually call. When off, only the default provider's key is required.
    required_provider_keys: list[tuple[str, str]] = [
        (providers.default, providers.entries[providers.default].api_key_env)
    ]
    if throttler.enabled:
        for chain in providers.logical_models.values():
            for concrete in chain:
                prov = concrete.split("/", 1)[0]
                if prov in providers.entries:
                    pair = (prov, providers.entries[prov].api_key_env)
                    if pair not in required_provider_keys:
                        required_provider_keys.append(pair)

    for prov, env_var in required_provider_keys:
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
```

- [ ] **Step 4: Run the new CLI tests**

Run: `uv run pytest tests/test_cli_run_config.py -v -k "router_client or throttler or fallback_provider"`
Expected: all 3 new tests pass.

- [ ] **Step 5: Full suite + ruff**

Run: `uv run pytest -q`
Expected: 133 + 3 = 136 passing.

Run: `uv run ruff check androidharness/ tests/`
Expected: `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add androidharness/cli.py tests/test_cli_run_config.py
git commit -m "feat(cli): select LiteLLMRouterClient when throttler.enabled; multi-provider key check"
```

---

## Task 6: Update docs

This milestone introduces two user-visible config sections (`throttler.*`, `providers.logical_models`) and changes when which client is used. Document in one focused commit. **Do not edit anything under `docs/superpowers/`** — those are specs/plans and stay frozen.

**Files:**
- Modify: `docs/configuration.md`
- Modify: `docs/architecture.md`
- Modify: `docs/roadmap.md`
- Modify: `docs/getting-started.md`

- [ ] **Step 1: Update `docs/configuration.md`**

Find the `### throttler` block (currently a 2-row table with `enabled` and `buckets`). Replace with:

````markdown
### `throttler`

Routes every LLM call through `litellm.Router` when enabled, adding proactive rate limiting and reactive fallback on 429 / quota errors.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | When true, the CLI uses `LiteLLMRouterClient` instead of the direct `LiteLLMClient`. |
| `cooldown_seconds` | int > 0 | `60` | How long Router waits before re-trying a rate-limited deployment. |
| `num_retries` | int >= 0 | `2` | Retries against the same deployment before consulting the fallback list. |
| `buckets` | dict[str, `BucketConfig`] | `{}` | Per-deployment rate-limit budget. Keys are LiteLLM-shaped `provider/model` ids; values are `{rpm: int?, tpm: int?}`. Both rpm and tpm are optional — `None` means no limit. |

Example:

```yaml
throttler:
  enabled: true
  cooldown_seconds: 60
  num_retries: 2
  buckets:
    gemini/gemini-2.5-flash:
      rpm: 10
      tpm: 250000
    anthropic/claude-haiku-4-5:
      rpm: 30
```
````

Find the `### providers` block. Append (after the existing description paragraph about default `entries`):

````markdown
#### Logical models (fallback chains)

`providers.logical_models` defines alias names that resolve to an ordered chain of concrete deployments. The first entry is the primary; on rate-limit / quota errors the Router falls through to the next entry.

```yaml
providers:
  logical_models:
    fast:
      - gemini/gemini-2.5-flash
      - anthropic/claude-haiku-4-5
      - openai/gpt-4o-mini
    smart:
      - anthropic/claude-sonnet-4-6
```

With this config, `androidharness run "..." --model fast` starts on Gemini and falls back to Claude then GPT-4o-mini on rate-limit errors. Every entry must be in `provider/model` form. When `throttler.enabled` is true, every distinct provider in any chain must have its `api_key_env` set; the CLI checks this up-front.
````

- [ ] **Step 2: Update `docs/architecture.md`**

In the LLM-seam paragraph (the one that describes `LiteLLMClient` and `GoogleGenaiClient`), replace the existing paragraph with:

```markdown
`LLMClient` Protocol + adapters live in `androidharness/llm.py`. Three concrete clients implement it: `LiteLLMClient` (default — direct `litellm.completion` per call), `LiteLLMRouterClient` (selected when `throttler.enabled` — wraps `litellm.Router` for per-deployment rate limiting and ordered fallback on 429 errors), and `GoogleGenaiClient` (escape hatch — direct `google-genai` SDK with its own retry/backoff). All three flatten the agent's internal `contents` list and fall back to `done(success=False)` when the model returns no function call. Two private helpers in the same module translate the agent's tool declarations and contents into OpenAI-shaped schemas, and a third (`_build_router_kwargs`) translates `AndroidHarnessConfig` into the kwargs `litellm.Router(...)` expects.
```

- [ ] **Step 3: Update `docs/roadmap.md`**

Find the row for milestone 3 (currently `| 3 | Throttler — token-bucket + Router fallback | Pending | |`). Replace with:

```markdown
| 3 | Throttler — token-bucket + Router fallback | **Shipped** | <NEW_COMMIT_SHAS> |
```

Replace `<NEW_COMMIT_SHAS>` with the actual SHAs from this milestone — collect them via `git log --oneline 488888e..HEAD` and paste in chronological order.

Also update the "Current focus" paragraph at the bottom. Replace:

```markdown
Milestones 1 (config schema) and 2 (LiteLLM provider seam) are complete — the harness is now multi-provider via `LiteLLMClient`. Milestones 3–5 remain in the "v2 minimum" block: throttler, policy seam, and Settings UI.
```

with:

```markdown
Milestones 1 (config schema), 2 (LiteLLM provider seam), and 3 (throttler + Router fallback) are complete. Milestones 4 (policy seam) and 5 (Settings UI) remain in the "v2 minimum" block.
```

- [ ] **Step 4: Update `docs/getting-started.md`**

Append a new section after "Key CLI flags for `run`":

````markdown
## Logical model names and the throttler

If you've set up logical model names in your config, pass them as `--model`:

```bash
uv run androidharness run "..." --model fast
```

With `throttler.enabled: true`, calls flow through `litellm.Router` so they respect per-deployment RPM / TPM budgets and fall back to the next entry in the chain on rate-limit errors. See [configuration.md](configuration.md#throttler) for the on-disk shape.

The throttler is off by default — until you've actually hit a rate limit, the direct `LiteLLMClient` is simpler and fine.
````

- [ ] **Step 5: Verify the doc changes**

Run: `grep -rn "milestone 3\|throttler" docs/*.md | grep -iv "shipped\|spec\|plan"`
Expected: no remaining `Pending` references to milestone 3 outside the superpowers/ tree.

- [ ] **Step 6: Commit**

```bash
git add docs/configuration.md docs/architecture.md docs/roadmap.md docs/getting-started.md
git commit -m "docs: throttler + logical models for v2 milestone 3"
```

---

## Task 7: Manual smoke test (human-run)

Same shape as milestone 2's Task 8 — needs a real ADB device + GEMINI_API_KEY (plus optionally a second provider key to test fallback). No commit.

- [ ] **Step 1: Write a throttler config**

```bash
uv run androidharness config init --force
cat >> ~/.androidharness/config.yaml <<'EOF'
throttler:
  enabled: true
  cooldown_seconds: 30
  num_retries: 1
  buckets:
    gemini/gemini-2.5-flash:
      rpm: 60
providers:
  logical_models:
    fast:
      - gemini/gemini-2.5-flash
EOF
```

(Open the file and ensure the new keys merged into the right sections — the heredoc above appends raw, so manual edit may be needed.)

- [ ] **Step 2: Verify Router instantiation does not crash**

Run: `uv run androidharness run "press the home button" --model fast --max-turns 3 --wall-clock 60`
Expected:
- Exit code 0 or 1 (1 is fine if the model `done(success=False)`s).
- No LiteLLM Router traceback.
- `runs/<id>/turns.jsonl` exists.

- [ ] **Step 3: Verify rollback**

Set `throttler.enabled: false` and rerun. Expected: works identically, no Router involvement.

---

## Self-review

**Spec coverage (§3 + roadmap item #3):**

| Spec line | Where it lands |
|---|---|
| "Throttler wrapper that maintains a token-bucket per `(provider, model)` key" | Task 1 (BucketConfig + ThrottlerConfig.buckets); Task 3 (_build_router_kwargs attaches rpm/tpm to matching model_list entries) |
| "On 429 or quota-style error, blocks until the bucket refills, then retries via LiteLLM's `Router` fallback list" | Tasks 3–4. Cooldown comes from `throttler.cooldown_seconds`; fallback chain from `providers.logical_models` → Router `fallbacks` |
| "ordered fallback list per logical model name (`fast` → `gemini-2.5-flash` → `claude-haiku-4-5` → `gpt-4o-mini`)" | Task 2 (logical_models) + Task 3 (_build_router_kwargs emits `fallbacks` map) |
| "Cost ledger: LiteLLM emits per-call cost; we sum into the run's SQLite row" | **Deferred to milestone 7 (SQLiteSink).** Still no SQLite row to sum into. |

**Placeholder scan:** Every code step shows literal code, every test step shows the literal test body, every run step names the command + expected outcome. Task 6 Step 3 has a `<NEW_COMMIT_SHAS>` token that's intentionally a runtime fill-in — the implementer collects the actual SHAs at commit time via the `git log` command given inline. Not a planning placeholder.

**Type consistency:**
- `BucketConfig(rpm, tpm)` — defined Task 1, referenced Task 3.
- `ThrottlerConfig(enabled, cooldown_seconds, num_retries, buckets)` — defined Task 1, consumed Task 3 / Task 5.
- `ProvidersConfig.logical_models: dict[str, list[str]]` — defined Task 2, consumed Task 3 / Task 5.
- `_build_router_kwargs(cfg) -> dict` — defined Task 3 with keys `model_list`, `fallbacks`, `cooldown_time`, `num_retries`. `LiteLLMRouterClient.__init__` in Task 4 calls `Router(**kw)` where `kw` is the return value — that key naming aligns with `litellm.Router.__init__`.
- `LiteLLMRouterClient(cfg)` constructor signature — defined Task 4, referenced Task 5.

**Deferred items (explicit, not bugs):**
- Cost ledger persistence → milestone 7.
- Settings UI Throttler panel → milestone 5.
- Live throttler-state display → milestone 8 (live monitoring).
