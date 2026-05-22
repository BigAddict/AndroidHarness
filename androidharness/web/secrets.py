"""Env-var lookups for provider API keys.

Keys are never persisted to config.yaml — only their env-var *names* are.
This module is the single place the UI checks whether a referenced key is
actually present in the running environment.

pydantic-settings does not read arbitrary undeclared env vars into model_dump()
even with extra="allow", so we delegate to os.environ directly for dynamic
key-name lookups. The class wrapper keeps the interface consistent and gives
us a single hook to extend later (secret managers, .env files, etc.).
"""

from __future__ import annotations

import os


class ProviderSecrets:
    """Reads API key env vars from the process environment by name."""

    @classmethod
    def is_set(cls, env_var_name: str) -> bool:
        value = cls.get(env_var_name)
        return bool(value)

    @classmethod
    def get(cls, env_var_name: str) -> str | None:
        value = os.environ.get(env_var_name)
        return value if value else None


__all__ = ["ProviderSecrets"]
