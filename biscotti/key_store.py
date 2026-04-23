"""
biscotti.key_store
~~~~~~~~~~~~~~~~~~~
In-memory API key store. Keys set via UI are held in server memory only —
never persisted to disk or database.

Resolution order: env var > in-memory > None
"""
from __future__ import annotations

import os
from typing import Any, Literal, TypedDict

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
    result["azure_foundry"] = bool(_AZURE_CONNECTIONS)
    return result


# ---------------------------------------------------------------------------
# Azure Foundry connections (in-memory only, multi-connection)
# ---------------------------------------------------------------------------

AzureAuth = Literal["key", "aad"]
AzureWire = Literal["openai", "anthropic"]


class AzureDeployment(TypedDict, total=False):
    name: str                  # deployment label (e.g. "insights-chat")
    endpoint: str | None       # full endpoint URL (optional; falls back to connection's)
    model: str | None          # underlying canonical model (e.g. "gpt-4o")
    wire: AzureWire            # inferred from endpoint; may be overridden explicitly
    version: str | None


class AzureConnection(TypedDict, total=False):
    endpoint: str
    auth: AzureAuth
    key: str | None            # None when auth == "aad"
    api_version: str
    deployments: list[AzureDeployment]
    discovered_at: float | None
    discovery_error: str | None


_AZURE_CONNECTIONS: dict[str, AzureConnection] = {}


def add_azure_connection(
    name: str,
    *,
    endpoint: str,
    auth: AzureAuth = "key",
    key: str | None = None,
    api_version: str = "2024-10-21",
) -> AzureConnection:
    """Register a new Azure Foundry connection. Raises ValueError if the name is taken."""
    if name in _AZURE_CONNECTIONS:
        raise ValueError(f"Azure connection {name!r} already exists")
    if auth == "key" and not key:
        raise ValueError("Key auth requires a non-empty API key")
    conn: AzureConnection = {
        "endpoint": (endpoint or "").rstrip("/"),
        "auth": auth,
        "key": key if auth == "key" else None,
        "api_version": api_version,
        "deployments": [],
        "discovered_at": None,
        "discovery_error": None,
    }
    _AZURE_CONNECTIONS[name] = conn
    return conn


def get_azure_connection(name: str) -> AzureConnection | None:
    return _AZURE_CONNECTIONS.get(name)


def list_azure_connections() -> dict[str, AzureConnection]:
    return dict(_AZURE_CONNECTIONS)


def remove_azure_connection(name: str) -> None:
    _AZURE_CONNECTIONS.pop(name, None)


def set_azure_deployments(
    name: str,
    deployments: list[AzureDeployment],
    *,
    discovered_at: float | None = None,
    discovery_error: str | None = None,
) -> None:
    """Update the cached deployment list for a connection."""
    conn = _AZURE_CONNECTIONS.get(name)
    if conn is None:
        raise ValueError(f"Azure connection {name!r} not found")
    conn["deployments"] = deployments
    conn["discovered_at"] = discovered_at
    conn["discovery_error"] = discovery_error


def iter_azure_models() -> list[str]:
    """Return all azure:<conn>:<deployment> model IDs across all connections."""
    out: list[str] = []
    for conn_name, conn in _AZURE_CONNECTIONS.items():
        for dep in conn.get("deployments", []):
            out.append(f"azure:{conn_name}:{dep['name']}")
    return out


def reset_azure_connections_for_tests() -> None:
    _AZURE_CONNECTIONS.clear()


# ---------------------------------------------------------------------------
# Legacy single-config API — kept as a thin shim over the "default" connection
# so any straggler callers keep working. All new code should use the
# multi-connection API above.
# ---------------------------------------------------------------------------

_LEGACY_DEFAULT = "default"


def set_azure_config(
    endpoint: str,
    key: str,
    api_version: str = "2024-10-21",
    deployments: list[str] | None = None,
) -> None:
    """Legacy single-config setter. Maps to connection named 'default'."""
    remove_azure_connection(_LEGACY_DEFAULT)
    add_azure_connection(
        _LEGACY_DEFAULT,
        endpoint=endpoint,
        auth="key",
        key=key,
        api_version=api_version,
    )
    if deployments:
        set_azure_deployments(
            _LEGACY_DEFAULT,
            [
                {"name": d, "model": None, "wire": "openai", "version": None}
                for d in deployments
            ],
        )


def get_azure_config() -> dict | None:
    """Legacy single-config getter. Returns the 'default' connection in the old shape."""
    conn = _AZURE_CONNECTIONS.get(_LEGACY_DEFAULT)
    if conn is None:
        return None
    return {
        "endpoint": conn["endpoint"],
        "key": conn.get("key"),
        "api_version": conn["api_version"],
        "deployments": [d["name"] for d in conn.get("deployments", [])],
    }


def remove_azure_config() -> None:
    remove_azure_connection(_LEGACY_DEFAULT)
