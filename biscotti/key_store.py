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

# Map provider id → environment variable name
_PROVIDER_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "xai": "XAI_API_KEY",
    "together": "TOGETHER_API_KEY",
    "cohere": "COHERE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# Display labels for the UI
PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic",
    "azure": "Azure OpenAI",
    "cohere": "Cohere",
    "deepseek": "DeepSeek",
    "gemini": "Google (Gemini)",
    "groq": "Groq",
    "mistral": "Mistral",
    "openai": "OpenAI",
    "together": "Together AI",
    "xai": "xAI (Grok)",
}

# Ordered list used for the UI settings panel (alphabetical by label)
KNOWN_PROVIDERS: list[str] = sorted(PROVIDER_LABELS.keys(), key=lambda p: PROVIDER_LABELS[p].lower())


def set_key(provider: str, key: str) -> None:
    _KEYS[provider] = key


def get_key(provider: str) -> str | None:
    """Get API key: env var takes priority, then in-memory."""
    env_var = _PROVIDER_ENV.get(provider, "")
    env_val = os.environ.get(env_var) if env_var else None
    if env_val:
        return env_val
    return _KEYS.get(provider)


def remove_key(provider: str) -> None:
    """Remove an in-memory API key. Has no effect on env-var keys."""
    _KEYS.pop(provider, None)


def available_providers() -> dict[str, bool]:
    result = {p: get_key(p) is not None for p in KNOWN_PROVIDERS}
    result["azure_foundry"] = _AZURE_CONFIG is not None
    return result


# ---------------------------------------------------------------------------
# Azure Foundry config (in-memory only)
# ---------------------------------------------------------------------------

_AZURE_CONFIG: dict | None = None


def set_azure_config(
    endpoint: str,
    key: str,
    api_version: str = "2024-10-21",
    deployments: list[str] | None = None,
) -> None:
    global _AZURE_CONFIG
    _AZURE_CONFIG = {
        "endpoint": endpoint.rstrip("/"),
        "key": key,
        "api_version": api_version,
        "deployments": deployments or [],
    }


def get_azure_config() -> dict | None:
    return _AZURE_CONFIG


def remove_azure_config() -> None:
    global _AZURE_CONFIG
    _AZURE_CONFIG = None
