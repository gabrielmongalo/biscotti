"""
biscotti.eval
~~~~~~~~~~~~~
Internal PydanticAI agents for evaluation: judge generator, judge, and prompt coach.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from pydantic_ai import Agent

from .key_store import get_key
from .models import CoachResponse, EvalScore, JudgeCriteria, TestCase


# ---------------------------------------------------------------------------
# Judge Generator — creates eval criteria from a system prompt
# ---------------------------------------------------------------------------

_JUDGE_GEN_SYSTEM = """You are an expert at creating evaluation criteria for AI agents.

Given a system prompt and its variables, produce specific, measurable criteria
that an agent's output should be scored against.

Rules:
- Each criterion must be independently assessable from the output alone
- Criteria should cover: accuracy, completeness, format compliance, and instruction-following
- Be specific to THIS agent's purpose — no generic criteria
- Weight important criteria higher (default 1.0, max 3.0)
- Aim for 3-6 criteria (not too many, not too few)"""


def build_judge_generation_prompt(system_prompt: str, variables: list[str]) -> str:
    """Build the user message for the judge generator agent."""
    var_section = ""
    if variables:
        var_section = "\n\nTemplate variables used:\n" + "\n".join(f"- {{{{{v}}}}}" for v in variables)
    return f"System prompt to evaluate:\n\n{system_prompt}{var_section}"


def infer_azure_wire(endpoint: str = "", model: str | None = None) -> str:
    """Infer the Foundry wire route.

    Preference order:
      1. ``/anthropic`` in the endpoint URL path → anthropic wire.
      2. Model name starts with ``claude`` (anywhere in the string) → anthropic.
      3. Default → openai.
    """
    url = (endpoint or "").lower()
    if "/anthropic" in url:
        return "anthropic"
    m = (model or "").lower()
    if "claude" in m:
        return "anthropic"
    return "openai"


def derive_azure_endpoint(base: str, wire: str) -> str:
    """Given a connection's base endpoint and a target wire, return the URL
    that biscotti should hit for requests.

    - Anthropic wire: append ``/anthropic`` if not already present.
    - OpenAI wire: use the base URL as-is (AsyncAzureOpenAI builds paths
      itself from ``azure_endpoint``).
    """
    base = (base or "").rstrip("/")
    if wire == "anthropic" and not base.endswith("/anthropic"):
        return f"{base}/anthropic"
    if wire == "openai" and base.endswith("/anthropic"):
        return base[: -len("/anthropic")]
    return base


def resolve_model(model: str):
    """Resolve a model string.

    For ``azure:<connection>:<deployment>`` IDs, builds a PydanticAI model
    bound to the right Foundry resource and wire route. Everything else is
    returned as-is (PydanticAI parses bare ``provider:model`` strings).
    """
    if not model.startswith("azure:"):
        return model

    parts = model.split(":", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        raise ValueError(
            f"Invalid azure model id {model!r}. "
            "Expected 'azure:<connection>:<deployment>'."
        )
    _, conn_name, dep_name = parts

    from .key_store import get_azure_connection
    conn = get_azure_connection(conn_name)
    if conn is None:
        raise ValueError(
            f"Azure connection {conn_name!r} not configured. "
            "Add it under Settings → Azure Foundry."
        )

    dep = next((d for d in conn.get("deployments", []) if d["name"] == dep_name), None)
    if dep is None:
        known = [d["name"] for d in conn.get("deployments", [])]
        raise ValueError(
            f"Deployment {dep_name!r} not found on Azure connection {conn_name!r}. "
            f"Known deployments: {known or '(add one under Settings → Azure Foundry)'}."
        )

    # Base URL lives on the connection. Wire is inferred from the deployment's
    # underlying model name (claude* → anthropic, else openai), and the
    # effective URL is derived from base + wire. A per-deployment endpoint
    # override is still respected for edge cases.
    base = (conn.get("endpoint") or "").rstrip("/")
    if not base:
        raise ValueError(
            f"Azure connection {conn_name!r} has no endpoint set."
        )

    wire = dep.get("wire") or infer_azure_wire(endpoint=dep.get("endpoint") or "",
                                                model=dep.get("model"))
    endpoint = dep.get("endpoint") or derive_azure_endpoint(base, wire)
    conn_view = {**conn, "endpoint": endpoint}
    dep_view = {**dep, "endpoint": endpoint, "wire": wire}

    if wire == "anthropic":
        return _build_azure_anthropic_model(conn_view, dep_view)
    return _build_azure_openai_model(conn_view, dep_view)


def _build_azure_openai_model(conn: dict, dep: dict):
    from openai import AsyncAzureOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    client_kwargs: dict = {
        "azure_endpoint": conn["endpoint"],
        "api_version": conn["api_version"],
    }
    if conn.get("auth") == "aad":
        client_kwargs["azure_ad_token_provider"] = _make_sync_aad_token_provider()
    else:
        client_kwargs["api_key"] = conn["key"]

    client = AsyncAzureOpenAI(**client_kwargs)
    return OpenAIChatModel(dep["name"], provider=OpenAIProvider(openai_client=client))


def _build_azure_anthropic_model(conn: dict, dep: dict):
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    # If the user pasted an endpoint that already ends in /anthropic (common on
    # Foundry), use it as-is. Otherwise derive the /anthropic sibling route
    # from the /openai path or bare resource URL.
    endpoint = conn["endpoint"].rstrip("/")
    if endpoint.endswith("/anthropic"):
        anthropic_base = endpoint
    else:
        if endpoint.endswith("/openai"):
            endpoint = endpoint[: -len("/openai")]
        anthropic_base = f"{endpoint}/anthropic"

    if conn.get("auth") == "aad":
        # Anthropic SDK does not expose a token-provider hook, so for AAD
        # we acquire a token up-front and pass it as the api_key. Tokens
        # expire (typically 1h); users on long-running sessions will need
        # to re-open the agent or restart to refresh.
        token = _sync_fetch_aad_token()
        provider = AnthropicProvider(api_key=token, base_url=anthropic_base)
    else:
        provider = AnthropicProvider(api_key=conn["key"], base_url=anthropic_base)

    return AnthropicModel(dep["name"], provider=provider)


def _sync_fetch_aad_token() -> str:
    """Fetch an AAD bearer token synchronously. Uses the sync
    DefaultAzureCredential so it's safe to call from inside an async context."""
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise ValueError(
            "AAD auth requires the 'azure-identity' package. "
            "Install with: pip install biscotti[azure]"
        ) from exc
    credential = DefaultAzureCredential()
    try:
        return credential.get_token("https://cognitiveservices.azure.com/.default").token
    finally:
        credential.close()


def _make_sync_aad_token_provider():
    """Token provider for AsyncAzureOpenAI. Called on every request; the
    SDK caches short-term. DefaultAzureCredential handles expiry on repeat
    get_token() calls."""
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise ValueError(
            "AAD auth requires the 'azure-identity' package. "
            "Install with: pip install biscotti[azure]"
        ) from exc
    credential = DefaultAzureCredential()

    def _provider() -> str:
        return credential.get_token("https://cognitiveservices.azure.com/.default").token

    return _provider


def make_judge_generator(model: str | None = None) -> Agent:
    """Create a PydanticAI agent that generates judge criteria."""
    if not model:
        raise ValueError(
            "No judge model configured. Set a model in the Evals configuration."
        )
    return Agent(
        resolve_model(model),
        output_type=JudgeCriteria,
        system_prompt=_JUDGE_GEN_SYSTEM,
    )


# ---------------------------------------------------------------------------
# Judge — scores agent output against criteria
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM_TEMPLATE = """You are an expert evaluator for AI agent outputs.

Score the agent output against these criteria:

{criteria}

For each criterion, determine if the output passes or fails it, and provide a brief note.
Then give an overall score from 1.0 to 5.0:
- 5.0: Exceptional — all criteria met, high quality
- 4.0: Good — most criteria met, minor issues
- 3.0: Acceptable — some criteria met, notable gaps
- 2.0: Poor — few criteria met, significant issues
- 1.0: Failing — criteria not met

Be rigorous but fair. Judge only what the criteria ask for."""


def build_judge_system_prompt(criteria_text: str) -> str:
    """Build the judge system prompt from criteria text."""
    return _JUDGE_SYSTEM_TEMPLATE.format(criteria=criteria_text)


def build_judge_user_prompt(
    user_message: str,
    system_prompt: str,
    agent_output: str,
) -> str:
    """Build the user message for the judge agent."""
    return f"""## Agent's System Prompt
{system_prompt}

## User Message
{user_message}

## Agent Output
{agent_output}

Evaluate the agent output against the criteria."""


def make_judge(model: str, criteria_text: str) -> Agent:
    """Create a PydanticAI agent that judges output against criteria."""
    return Agent(
        resolve_model(model),
        output_type=EvalScore,
        system_prompt=build_judge_system_prompt(criteria_text),
    )


# ---------------------------------------------------------------------------
# API key bridging
# ---------------------------------------------------------------------------

_PROVIDER_ENV_MAP: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "cohere": "COHERE_API_KEY",
}


@contextmanager
def _ensure_api_keys():
    """Temporarily set API keys from key_store if not already in env."""
    restored = {}
    for provider, env_var in _PROVIDER_ENV_MAP.items():
        if not os.environ.get(env_var):
            key = get_key(provider)
            if key:
                os.environ[env_var] = key
                restored[env_var] = True
    try:
        yield
    finally:
        for env_var in restored:
            del os.environ[env_var]


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

async def generate_judge_criteria(
    system_prompt: str,
    variables: list[str],
    model: str | None = None,
) -> JudgeCriteria:
    """Generate judge criteria for a given system prompt."""
    if not model:
        raise ValueError(
            "No judge model configured. Set a model in the Evals configuration."
        )
    with _ensure_api_keys():
        agent = make_judge_generator(model)
        user_msg = build_judge_generation_prompt(system_prompt, variables)
        result = await agent.run(user_msg)
        return result.output


async def judge_output(
    criteria_text: str,
    user_message: str,
    system_prompt: str,
    agent_output: str,
    model: str | None = None,
) -> EvalScore:
    """Score an agent output against criteria."""
    if not model:
        raise ValueError(
            "No judge model configured. Set a model in the Evals configuration."
        )
    with _ensure_api_keys():
        agent = make_judge(model, criteria_text)
        user_msg = build_judge_user_prompt(user_message, system_prompt, agent_output)
        result = await agent.run(user_msg)
        return result.output


# ---------------------------------------------------------------------------
# Coach — analyzes eval results and suggests prompt improvements
# ---------------------------------------------------------------------------

_COACH_SYSTEM = """You are an expert prompt engineer. Your job is to review
an AI agent's system prompt and suggest specific, actionable improvements.

You may receive:
- The current system prompt (always provided)
- Evaluation criteria and results (if available from a prior eval run)

Your suggestions must be:
- Specific: include the exact text to add, replace, or remove
- Actionable: each suggestion should be independently implementable
- Prioritized: list the highest-impact change first
- Practical: focus on clarity, structure, constraint specificity, and output formatting

When eval results are provided, ground suggestions in the specific failures.
When reviewing a prompt without eval results, focus on best practices:
  - Clear role definition
  - Explicit output format instructions
  - Well-defined constraints and edge cases
  - Effective use of examples (few-shot)
  - Variable placeholder usage

Do not rewrite the prompt's core purpose or domain.
Always provide a complete revised_prompt with all suggestions applied."""


def build_coach_user_prompt(
    system_prompt: str,
    criteria_text: str,
    case_details: list[dict],
    test_cases: list[TestCase],
) -> str:
    """Build the user message for the coach agent."""
    parts = [
        "## Current System Prompt",
        system_prompt,
        "",
        "## Evaluation Criteria",
        criteria_text,
        "",
        "## Eval Results",
    ]
    for cd in case_details:
        tc_msg = next(
            (tc.user_message for tc in test_cases if tc.name == cd["test_case"]),
            "(unknown)",
        )
        parts.append(f"### Test Case: {cd['test_case']}")
        parts.append(f"User message: {tc_msg}")
        parts.append(f"Score: {cd.get('score', 'N/A')}")
        for cr in cd.get("criteria_results", []):
            status = "PASS" if cr["passed"] else "FAIL"
            parts.append(f"  - [{status}] {cr['criterion']}: {cr['note']}")
        parts.append(f"Judge reasoning: {cd.get('reasoning', '')}")
        parts.append("")

    parts.append("Analyze these results and suggest specific improvements to the system prompt.")
    return "\n".join(parts)


def make_coach(model: str, custom_system_prompt: str | None = None) -> Agent:
    """Create a PydanticAI agent that coaches on prompt improvements."""
    return Agent(
        resolve_model(model),
        output_type=CoachResponse,
        system_prompt=custom_system_prompt or _COACH_SYSTEM,
    )


async def generate_coaching(
    system_prompt: str,
    criteria_text: str,
    case_details: list[dict],
    test_cases: list[TestCase],
    model: str | None = None,
    custom_system_prompt: str | None = None,
) -> CoachResponse:
    """Analyze eval results and suggest prompt improvements."""
    with _ensure_api_keys():
        agent = make_coach(model, custom_system_prompt)
        user_msg = build_coach_user_prompt(system_prompt, criteria_text, case_details, test_cases)
        result = await agent.run(user_msg)
        return result.output


async def coach_prompt(
    system_prompt: str,
    model: str | None = None,
    custom_system_prompt: str | None = None,
) -> CoachResponse:
    """Review a prompt directly and suggest improvements (no eval needed)."""
    with _ensure_api_keys():
        agent = make_coach(model, custom_system_prompt)
        user_msg = f"## Current System Prompt\n{system_prompt}\n\nReview this prompt and suggest specific improvements."
        result = await agent.run(user_msg)
        return result.output
