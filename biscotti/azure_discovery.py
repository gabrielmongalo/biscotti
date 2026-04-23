"""
biscotti.azure_discovery
~~~~~~~~~~~~~~~~~~~~~~~~
Fetch deployment lists from an Azure OpenAI / Foundry resource.

The function is pure: it takes connection details and returns a normalized
list of deployments. State mutation (caching the result onto a connection
record) is the caller's responsibility.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .key_store import AzureAuth, AzureDeployment

logger = logging.getLogger(__name__)


class DiscoveryError(RuntimeError):
    """Raised when discovery fails with a user-actionable reason.

    The message is short and safe to show in the UI. The full underlying
    exception chain is logged via ``logger.exception(...)`` at the point
    where the DiscoveryError is constructed.
    """


_AAD_SCOPE = "https://cognitiveservices.azure.com/.default"


async def _aad_bearer_token() -> str:
    """Fetch a bearer token via DefaultAzureCredential. Import lazily so
    azure-identity remains an optional dependency."""
    try:
        from azure.identity.aio import DefaultAzureCredential
    except ImportError as exc:
        raise DiscoveryError(
            "AAD auth requires the 'azure-identity' package. "
            "Install with: pip install biscotti[azure]"
        ) from exc

    credential = DefaultAzureCredential()
    try:
        token = await credential.get_token(_AAD_SCOPE)
    except Exception as exc:
        # Full credential-chain trace goes to the server log; UI gets a
        # short actionable message. DefaultAzureCredential errors tend to
        # be long and intimidating.
        logger.exception("Azure Foundry discovery: AAD token acquisition failed")
        raise DiscoveryError(
            "AAD sign-in failed. Run `az login`, or set env vars "
            "AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET. "
            "See server logs for the full credential-chain trace."
        ) from exc
    finally:
        await credential.close()
    return token.token


def _normalize_deployment(raw: dict[str, Any]) -> AzureDeployment:
    """Map the raw Azure deployment object into biscotti's shape."""
    # Deployment name lives under `id` on the data-plane listing and under
    # `name` on some Foundry project endpoints — accept both.
    name = raw.get("id") or raw.get("name") or ""

    model_obj = raw.get("model")
    if isinstance(model_obj, dict):
        model_name = model_obj.get("name")
        model_format = (model_obj.get("format") or "").lower()
        version = model_obj.get("version")
    else:
        # Older/alternate shape: {"model": "gpt-4o", "modelFormat": "OpenAI"}
        model_name = model_obj if isinstance(model_obj, str) else None
        model_format = (raw.get("modelFormat") or "").lower()
        version = raw.get("modelVersion")

    wire = "anthropic" if model_format == "anthropic" else "openai"

    return {
        "name": name,
        "model": model_name or None,
        "wire": wire,
        "version": version or None,
    }


def _normalize_endpoint(endpoint: str) -> str:
    """Strip trailing slash and any wire-format sub-routes the user may
    have pasted (``/openai``, ``/anthropic``, ``/models``). Discovery always
    hits the resource base URL."""
    endpoint = endpoint.rstrip("/")
    for suffix in ("/openai", "/anthropic", "/models"):
        if endpoint.endswith(suffix):
            endpoint = endpoint[: -len(suffix)].rstrip("/")
    return endpoint


async def discover_deployments(
    endpoint: str,
    *,
    auth: AzureAuth = "key",
    key: str | None = None,
    api_version: str = "2024-10-21",
    timeout: float = 15.0,
) -> list[AzureDeployment]:
    """Fetch the deployment list from an Azure OpenAI / Foundry resource.

    Returns a list of normalized deployment records. Raises DiscoveryError
    with a clear message on any failure.
    """
    endpoint = _normalize_endpoint(endpoint)

    if auth == "key":
        if not key:
            raise DiscoveryError("Key auth requires a non-empty API key")
        headers = {"api-key": key}
    elif auth == "aad":
        token = await _aad_bearer_token()
        headers = {"Authorization": f"Bearer {token}"}
    else:
        raise DiscoveryError(f"Unknown auth mode: {auth!r}")

    # Try several known listing paths in order. Different Azure resources
    # expose the deployment catalog under different URLs.
    candidate_paths = [
        "/openai/deployments",       # classic Azure OpenAI
        "/openai/v1/deployments",    # newer Foundry data-plane
        "/models",                   # some multi-provider Foundry projects
    ]
    params = {"api-version": api_version}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = None
            for path in candidate_paths:
                r = await client.get(f"{endpoint}{path}", headers=headers, params=params)
                if r.status_code != 404:
                    resp = r
                    break
            if resp is None:
                raise DiscoveryError(
                    "No deployment-listing endpoint found. Tried: "
                    + ", ".join(candidate_paths)
                    + ". This resource may require AAD auth or ARM (management-plane) "
                    "access for listing — add deployments manually below."
                )

            if resp.status_code in (401, 403):
                hint = (
                    "The API key was rejected."
                    if auth == "key"
                    else "AAD token was rejected — check your Azure role assignments."
                )
                raise DiscoveryError(f"Discovery failed ({resp.status_code}): {hint}")

            if resp.status_code >= 400:
                raise DiscoveryError(
                    f"Discovery failed ({resp.status_code}): {resp.text[:300]}"
                )

            try:
                body = resp.json()
            except ValueError as exc:
                raise DiscoveryError(f"Discovery returned non-JSON response: {exc}") from exc
    except httpx.ConnectError as exc:
        raise DiscoveryError(f"Could not reach {endpoint} — check the URL: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise DiscoveryError(f"Discovery timed out against {endpoint}: {exc}") from exc
    except httpx.HTTPError as exc:
        raise DiscoveryError(f"Discovery network error: {exc}") from exc

    raw_list = body.get("data") if isinstance(body, dict) else None
    if raw_list is None:
        raw_list = body.get("value") if isinstance(body, dict) else None
    if raw_list is None:
        raise DiscoveryError(
            f"Discovery response missing 'data'/'value' array. Got keys: "
            f"{list(body.keys()) if isinstance(body, dict) else type(body).__name__}"
        )

    return [_normalize_deployment(item) for item in raw_list if isinstance(item, dict)]
