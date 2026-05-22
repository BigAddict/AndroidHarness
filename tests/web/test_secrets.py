from __future__ import annotations

import pytest

from androidharness.web.secrets import ProviderSecrets


def test_is_set_true_when_env_var_present(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MY_FAKE_KEY", "x")
    assert ProviderSecrets.is_set("MY_FAKE_KEY") is True


def test_is_set_false_when_env_var_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MY_FAKE_KEY", raising=False)
    assert ProviderSecrets.is_set("MY_FAKE_KEY") is False


def test_is_set_false_when_env_var_empty(monkeypatch: pytest.MonkeyPatch):
    """Empty string is treated as unset — the agent won't be able to auth either way."""
    monkeypatch.setenv("MY_FAKE_KEY", "")
    assert ProviderSecrets.is_set("MY_FAKE_KEY") is False


def test_get_returns_value_when_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MY_FAKE_KEY", "sekret")
    assert ProviderSecrets.get("MY_FAKE_KEY") == "sekret"


def test_get_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MY_FAKE_KEY", raising=False)
    assert ProviderSecrets.get("MY_FAKE_KEY") is None
