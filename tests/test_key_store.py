import os
import pytest
from biscotti.key_store import set_key, get_key, remove_key, available_providers, _KEYS


def test_get_key_returns_env_over_memory(monkeypatch):
    """Env var takes priority over in-memory key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    set_key("anthropic", "mem-key")
    assert get_key("anthropic") == "env-key"


def test_get_key_returns_memory_when_no_env(monkeypatch):
    """Falls back to in-memory when no env var."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    set_key("anthropic", "mem-key")
    assert get_key("anthropic") == "mem-key"


def test_get_key_returns_none_when_nothing(monkeypatch):
    """Returns None when no key is set anywhere."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert get_key("nonexistent") is None


def test_remove_key_only_removes_memory(monkeypatch):
    """remove_key clears in-memory but env var still works."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    set_key("anthropic", "mem-key")
    remove_key("anthropic")
    assert get_key("anthropic") == "env-key"


def test_remove_key_makes_get_return_none(monkeypatch):
    """After remove, get_key returns None if no env var."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    set_key("anthropic", "mem-key")
    remove_key("anthropic")
    assert get_key("anthropic") is None


def test_available_providers(monkeypatch):
    """available_providers reflects current state."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    set_key("anthropic", "key1")
    result = available_providers()
    assert result["anthropic"] is True
    assert result["openai"] is False
