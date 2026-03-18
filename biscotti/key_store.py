"""
biscotti.key_store
~~~~~~~~~~~~~~~~~~~
In-memory API key store. Keys set via UI are held in server memory only —
never persisted to disk or database.

Resolution order: env var > in-memory > None
"""
from __future__ import annotations

import os

_KEYS: dict[str, str] = {}


def set_key(provider: str, key: str) -> None:
    _KEYS[provider] = key


def get_key(provider: str) -> str | None:
    """Get API key: env var takes priority, then in-memory."""
    env_map = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
    env_val = os.environ.get(env_map.get(provider, ""))
    if env_val:
        return env_val
    return _KEYS.get(provider)


def available_providers() -> dict[str, bool]:
    return {
        "anthropic": get_key("anthropic") is not None,
        "openai": get_key("openai") is not None,
    }
