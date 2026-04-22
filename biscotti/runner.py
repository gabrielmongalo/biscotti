"""
biscotti.runner
~~~~~~~~~~~~~~~~
Executes a test run against an agent callable and persists the result.

The runner is model-agnostic: it calls whatever async callable is registered
for the agent (PydanticAI, raw OpenAI, Anthropic SDK, etc.).
"""
from __future__ import annotations

import inspect
import re
import time
from typing import Any, Awaitable, Callable

from .models import RunLog, RunOutcome, RunRequest, RunResponse
from .registry import get_agent
from .store import PromptStore


# Type alias for agent callables
AgentCallable = Callable[[str, str], Awaitable[str]]
# Signature: async def fn(user_message: str, system_prompt: str) -> str
# Extended:  async def fn(user_message: str, system_prompt: str, params: dict) -> str|dict


# ---------------------------------------------------------------------------
# Token pricing (per 1M tokens)
# ---------------------------------------------------------------------------
PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o":           {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":      {"input": 0.15,  "output": 0.60},
    "gpt-4.1":          {"input": 2.00,  "output": 8.00},
    "gpt-4.1-mini":     {"input": 0.40,  "output": 1.60},
    "gpt-4.1-nano":     {"input": 0.10,  "output": 0.40},
    "o3":               {"input": 2.00,  "output": 8.00},
    "o3-mini":          {"input": 1.10,  "output": 4.40},
    "o4-mini":          {"input": 1.10,  "output": 4.40},
    # Anthropic
    "claude-opus-4-6":           {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00},
    "claude-sonnet-4-5":         {"input": 3.00,  "output": 15.00},
    "claude-haiku-4-5":          {"input": 0.80,  "output": 4.00},
    # Google
    "gemini-2.5-pro":   {"input": 1.25,  "output": 10.00},
    "gemini-2.5-flash": {"input": 0.15,  "output": 0.60},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate cost in USD. Returns None if model is not in pricing table."""
    # Try exact match, then prefix match (e.g. "gpt-4o-2024-08-06" → "gpt-4o")
    prices = PRICING.get(model)
    if prices is None:
        for key in PRICING:
            if model.startswith(key):
                prices = PRICING[key]
                break
    if prices is None:
        return None
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


def _callable_accepts_params(fn: Any) -> bool:
    """Check if callable accepts a third 'params' argument."""
    try:
        sig = inspect.signature(fn)
        params = list(sig.parameters.keys())
        return len(params) >= 3
    except (ValueError, TypeError):
        return False


def detect_model_from_callable(fn: Any) -> str | None:
    """Try to auto-detect the model name from the callable's source or attributes.

    Checks (in order):
    1. ``_biscotti_meta.models[0]`` — first declared model
    2. ``fn.model`` or ``fn.model_name`` attribute (common in SDK wrappers)
    3. Source code inspection for ``model=`` string literals
    """
    # 1. Check meta
    meta = getattr(fn, '_biscotti_meta', None)
    if meta and getattr(meta, 'models', None):
        return meta.models[0]

    # 2. Check common attributes
    for attr in ('model', 'model_name', '_model'):
        val = getattr(fn, attr, None)
        if isinstance(val, str) and val:
            return val

    # 3. Try to read source and find model= patterns
    try:
        source = inspect.getsource(fn)
        # Match model="..." or model='...'
        match = re.search(r'model\s*=\s*["\']([^"\']+)["\']', source)
        if match:
            return match.group(1)
    except (OSError, TypeError):
        pass

    return None

_AGENT_CALLABLES: dict[str, AgentCallable] = {}


def register_callable(agent_name: str, fn: AgentCallable) -> None:
    """Register the actual async callable for a given agent name."""
    _AGENT_CALLABLES[agent_name] = fn


def get_callable(agent_name: str) -> AgentCallable | None:
    return _AGENT_CALLABLES.get(agent_name)


def _render_prompt(template: str, variables: dict[str, str]) -> str:
    """Replace {{var}} placeholders with values."""
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", value)
    remaining = re.findall(r"\{\{(\w+)\}\}", result)
    if remaining:
        import logging
        logging.getLogger("biscotti").warning(f"Unresolved template variables: {remaining}")
    return result


async def execute_run(
    request: RunRequest,
    store: PromptStore,
) -> RunResponse:
    """
    Execute a single test run.

    1. Resolve the system prompt (current version or specified version).
    2. Render variable placeholders.
    3. Call the registered agent callable.
    4. Persist the RunLog.
    5. Return a RunResponse.
    """
    # --- Resolve system prompt ---
    if request.prompt_version_id is not None:
        pv = await store.get_prompt_version(request.prompt_version_id)
        if pv is None:
            raise ValueError(f"Prompt version {request.prompt_version_id} not found")
    else:
        pv = await store.get_current_version(request.agent_name)
        if pv is None:
            # Fall back to default prompt from registry
            meta = get_agent(request.agent_name)
            if meta is None:
                raise ValueError(f"Agent '{request.agent_name}' not registered")
            from .models import PromptVersionCreate
            create = PromptVersionCreate(
                agent_name=request.agent_name,
                system_prompt=meta.default_system_prompt,
                notes="Auto-seeded from default_system_prompt",
            )
            pv = await store.create_prompt_version(create)
            # Set as current immediately (first-run bootstrap)
            from .models import PromptStatus
            pv = await store.set_status(pv.id, PromptStatus.current)

    rendered_prompt = _render_prompt(pv.system_prompt, request.variable_values)
    rendered_user_message = _render_prompt(request.user_message, request.variable_values)

    # --- Call the agent ---
    callable_fn = get_callable(request.agent_name)

    output = ""
    error_msg = None
    outcome = RunOutcome.success
    input_tokens = 0
    output_tokens = 0
    model_used = "unknown"
    tool_calls = []

    start = time.monotonic()

    # Build params dict for callables that accept it
    run_params = {"variable_values": request.variable_values}
    if request.model:
        run_params["model"] = request.model
    if request.temperature is not None:
        run_params["temperature"] = request.temperature
    if request.reasoning_effort:
        run_params["reasoning_effort"] = request.reasoning_effort

    if callable_fn is None:
        # No callable registered → return a helpful placeholder
        output = (
            f"[biscotti] No callable registered for '{request.agent_name}'. "
            "Call biscotti.register_callable(name, fn) to connect your agent."
        )
        outcome = RunOutcome.error
        error_msg = "No callable registered"
    else:
        try:
            if run_params and _callable_accepts_params(callable_fn):
                result = await callable_fn(rendered_user_message, rendered_prompt, run_params)
            else:
                result = await callable_fn(rendered_user_message, rendered_prompt)
            if isinstance(result, dict):
                output = result.get("output", str(result))
                input_tokens = result.get("input_tokens", 0)
                output_tokens = result.get("output_tokens", 0)
                model_used = result.get("model", "unknown")
                tool_calls = result.get("tool_calls", [])
            else:
                output = str(result)
        except Exception as exc:
            output = ""
            outcome = RunOutcome.error
            error_msg = str(exc)

    latency_ms = int((time.monotonic() - start) * 1000)

    # Use the model from callable response if available, else selected, else auto-detected
    effective_model = model_used if model_used != "unknown" else (
        request.model or detect_model_from_callable(callable_fn) or "unknown"
    )
    cost = estimate_cost(effective_model, input_tokens, output_tokens)

    # --- Persist ---
    run = RunLog(
        agent_name=request.agent_name,
        prompt_version=pv.version,
        test_case_name=request.test_case_name,
        user_message=rendered_user_message,
        variable_values=request.variable_values,
        system_prompt_rendered=rendered_prompt,
        output=output,
        outcome=outcome,
        error_message=error_msg,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_used=effective_model,
        model_selected=request.model or "",
        temperature=request.temperature,
        reasoning_effort=request.reasoning_effort,
        estimated_cost=cost,
        tool_calls=tool_calls,
    )
    saved = await store.save_run(run)

    return RunResponse(
        run_id=saved.id,
        output=output,
        outcome=outcome,
        error_message=error_msg,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        score=None,
        score_reasoning=None,
        model_used=effective_model,
        prompt_version=pv.version,
        estimated_cost=cost,
        tool_calls=tool_calls,
    )
