from __future__ import annotations

import pytest

from androidharness.web.forms import FormError, unflatten


def test_unflatten_passes_through_simple_keys():
    assert unflatten({"a": "1", "b": "2"}) == {"a": "1", "b": "2"}


def test_unflatten_nests_dotted_keys():
    assert unflatten({"policy.default_mode": "confirm"}) == {
        "policy": {"default_mode": "confirm"}
    }


def test_unflatten_nests_two_deep():
    assert unflatten({"providers.entries.gemini.api_key_env": "GEMINI_API_KEY"}) == {
        "providers": {"entries": {"gemini": {"api_key_env": "GEMINI_API_KEY"}}}
    }


def test_unflatten_merges_sibling_paths():
    flat = {
        "policy.default_mode": "confirm",
        "policy.confirm_timeout_s": "30",
    }
    assert unflatten(flat) == {
        "policy": {"default_mode": "confirm", "confirm_timeout_s": "30"}
    }


def test_unflatten_rejects_value_then_dict_collision():
    """Cannot have both `a` and `a.b` in the same form."""
    with pytest.raises(FormError):
        unflatten({"a": "1", "a.b": "2"})


def test_unflatten_drops_empty_string_values():
    """Empty form fields collapse to absence so Pydantic defaults apply."""
    assert unflatten({"defaults.device_serial": ""}) == {"defaults": {}}
