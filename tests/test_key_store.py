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


class TestAzureConfig:
    def test_set_and_get_azure_config(self):
        from biscotti.key_store import set_azure_config, get_azure_config
        set_azure_config(
            endpoint="https://myresource.openai.azure.com/",
            key="test-key-123",
            api_version="2024-10-21",
            deployments=["gpt4o-deploy", "embed-deploy"],
        )
        config = get_azure_config()
        assert config is not None
        assert config["endpoint"] == "https://myresource.openai.azure.com"
        assert config["key"] == "test-key-123"
        assert config["api_version"] == "2024-10-21"
        assert config["deployments"] == ["gpt4o-deploy", "embed-deploy"]

    def test_get_azure_config_returns_none_when_not_set(self):
        from biscotti.key_store import get_azure_config
        assert get_azure_config() is None

    def test_remove_azure_config(self):
        from biscotti.key_store import set_azure_config, get_azure_config, remove_azure_config
        set_azure_config(
            endpoint="https://test.openai.azure.com/",
            key="key",
            api_version="2024-10-21",
            deployments=["deploy1"],
        )
        remove_azure_config()
        assert get_azure_config() is None

    def test_azure_config_updates_provider_status(self):
        from biscotti.key_store import set_azure_config, available_providers
        set_azure_config(
            endpoint="https://test.openai.azure.com/",
            key="key",
            api_version="2024-10-21",
            deployments=["deploy1"],
        )
        status = available_providers()
        assert status.get("azure_foundry") is True
