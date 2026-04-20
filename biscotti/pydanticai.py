"""
biscotti.pydanticai
~~~~~~~~~~~~~~~~~~~~
First-class PydanticAI integration for biscotti.

Register a PydanticAI Agent with biscotti in one call::

    from pydantic_ai import Agent
    from biscotti.pydanticai import register

    agent = Agent("claude-sonnet-4-20250514", instructions="You are a helpful chef.")

    register(agent, name="recipe agent", description="Suggests recipes")

The agent is then visible in the biscotti UI, where you can version its
system prompt, run tests, and evaluate outputs -- all without touching code.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .models import AgentMeta
from .registry import register_agent
from .runner import register_callable


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register(
    agent: Any,
    *,
    name: str,
    description: str = "",
    variables: list[str] | None = None,
    tags: list[str] | None = None,
) -> AgentMeta:
    """Register a PydanticAI Agent with biscotti.

    Parameters
    ----------
    agent:
        A ``pydantic_ai.Agent`` instance.
    name:
        Human-readable name shown in the biscotti UI. Must be unique.
    description:
        Short description shown in the agent list.
    variables:
        Template variables (``{{var}}``) the system prompt uses.
        Auto-detected from the prompt if omitted.
    tags:
        Optional tags for filtering in the UI.

    Returns
    -------
    AgentMeta
        The registered metadata object.
    """
    # Extract everything we can from the PydanticAI Agent
    system_prompt = _extract_system_prompt(agent)
    model_name = _extract_model_name(agent)
    output_info = _extract_output_info(agent)
    tools = _extract_tools(agent)

    # Auto-detect variables from the prompt
    detected = re.findall(r"\{\{(\w+)\}\}", system_prompt)
    resolved_vars = list(dict.fromkeys((variables or []) + detected))

    # Build the AgentMeta
    meta = AgentMeta(
        name=name,
        description=description or name,
        variables=resolved_vars,
        default_system_prompt=system_prompt,
        tags=tags or [],
        models=[model_name] if model_name else [],
    )

    # Stash PydanticAI-specific info on the meta for later use
    meta._pydanticai_agent = agent  # type: ignore[attr-defined]
    meta._pydanticai_tools = tools  # type: ignore[attr-defined]
    meta._pydanticai_output = output_info  # type: ignore[attr-defined]

    register_agent(meta)

    # Build and register the async callable
    callable_fn = _build_callable(agent, output_info)
    register_callable(name, callable_fn)

    return meta


# ---------------------------------------------------------------------------
# Introspection helpers (private)
# ---------------------------------------------------------------------------

def _extract_system_prompt(agent: Any) -> str:
    """Extract the system prompt from a PydanticAI Agent.

    Checks ``agent._instructions`` (str, list[str], or list[callable]) and
    ``agent._system_prompt_functions`` (list of SystemPromptRunner objects).
    Callables (from ``@agent.instructions`` decorator) are called to get strings.
    For dynamic ones (that require RunContext), inserts a placeholder.
    """
    parts: list[str] = []

    # 1. Instructions (the `instructions=` kwarg or @agent.instructions decorator)
    # PydanticAI stores these as a list — items can be strings (from instructions=)
    # or callables (from @agent.instructions decorator).
    instructions = getattr(agent, "_instructions", None)
    if instructions:
        if isinstance(instructions, str):
            parts.append(instructions)
        elif isinstance(instructions, (list, tuple)):
            for item in instructions:
                if isinstance(item, str):
                    parts.append(item)
                elif callable(item):
                    # @agent.instructions stores a callable — call it
                    try:
                        result = item()
                        if isinstance(result, str):
                            parts.append(result)
                    except Exception:
                        fn_name = getattr(item, "__name__", "instructions")
                        parts.append(f"[dynamic: {fn_name}]")

    # 2. System prompt functions (@agent.system_prompt decorators)
    prompt_functions = getattr(agent, "_system_prompt_functions", None) or []
    for runner in prompt_functions:
        takes_ctx = getattr(runner, "_takes_ctx", None)
        is_async = getattr(runner, "_is_async", False)
        fn = getattr(runner, "function", None)

        if fn is None:
            continue

        if takes_ctx:
            # Dynamic prompt -- cannot call without RunContext
            fn_name = getattr(fn, "__name__", "dynamic_prompt")
            parts.append(f"[dynamic: {fn_name}]")
        elif is_async:
            # Async no-arg -- cannot call synchronously, use placeholder
            fn_name = getattr(fn, "__name__", "async_prompt")
            parts.append(f"[async: {fn_name}]")
        else:
            # Static no-arg callable -- safe to call
            try:
                result = fn()
                if isinstance(result, str):
                    parts.append(result)
            except Exception:
                fn_name = getattr(fn, "__name__", "prompt")
                parts.append(f"[error calling: {fn_name}]")

    return "\n\n".join(parts)


def _extract_model_name(agent: Any) -> str:
    """Extract the default model name from a PydanticAI Agent.

    Checks ``agent._model`` for a ``.model_name`` attribute, falling back
    to ``str(model)`` if needed. Returns empty string if no model is set.
    """
    model = getattr(agent, "_model", None)
    if model is None:
        return ""

    # Most PydanticAI model objects have .model_name
    model_name = getattr(model, "model_name", None)
    if isinstance(model_name, str) and model_name:
        return model_name

    # Fallback: model_id (e.g. "openai:gpt-4o")
    model_id = getattr(model, "model_id", None)
    if isinstance(model_id, str) and model_id:
        return model_id

    # Last resort
    return str(model)


def _extract_output_info(agent: Any) -> dict[str, Any]:
    """Extract output type information from a PydanticAI Agent.

    Returns a dict with:
    - ``type``: "str" or the class name (e.g. "Recipe")
    - ``schema``: JSON schema dict for Pydantic BaseModel types, else None
    """
    output_type = getattr(agent, "_output_type", str)

    if output_type is str:
        return {"type": "str", "schema": None}

    type_name = getattr(output_type, "__name__", str(output_type))

    # Check if it's a Pydantic BaseModel
    try:
        from pydantic import BaseModel
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            schema = output_type.model_json_schema()
            return {"type": type_name, "schema": schema}
    except Exception:
        pass

    return {"type": type_name, "schema": None}


def _extract_tools(agent: Any) -> list[dict[str, Any]]:
    """Extract tool metadata from a PydanticAI Agent.

    Reads ``agent._function_toolset.tools`` (dict of name -> Tool) and
    ``agent._builtin_tools`` (tuple of built-in tool identifiers).
    """
    tools: list[dict[str, Any]] = []

    # 1. Function tools
    function_toolset = getattr(agent, "_function_toolset", None)
    if function_toolset is not None:
        tool_dict = getattr(function_toolset, "tools", None) or {}
        for tool_name, tool_obj in tool_dict.items():
            tool_info: dict[str, Any] = {
                "name": tool_name,
                "description": getattr(tool_obj, "description", "") or "",
                "parameters": {},
            }

            # Extract parameters from tool_def if available
            tool_def = getattr(tool_obj, "tool_def", None)
            if tool_def is not None:
                params = getattr(tool_def, "parameters_json_schema", None)
                if params is not None:
                    tool_info["parameters"] = params

            tools.append(tool_info)

    # 2. Built-in tools (e.g. code_execution, web_search)
    builtin_tools = getattr(agent, "_builtin_tools", None) or ()
    for bt in builtin_tools:
        bt_name = getattr(bt, "value", None) or getattr(bt, "name", None) or str(bt)
        tools.append({
            "name": bt_name,
            "description": f"Built-in tool: {bt_name}",
            "parameters": {},
            "builtin": True,
        })

    return tools


# ---------------------------------------------------------------------------
# Callable builder
# ---------------------------------------------------------------------------

def _build_callable(
    agent: Any,
    output_info: dict[str, Any],
) -> Any:
    """Build an async callable adapter for the biscotti runner.

    Returns an async function with signature::

        async def(user_message: str, system_prompt: str, params: dict) -> dict

    The returned dict has keys: ``output``, ``input_tokens``,
    ``output_tokens``, ``model``, ``tool_calls``.
    """
    async def callable_fn(
        user_message: str,
        system_prompt: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .key_store import get_key

        params = params or {}

        # Bridge API keys from biscotti key store into env vars
        _bridge_api_keys(get_key)

        # Build model_settings from params
        model_settings: dict[str, Any] = {}
        if "temperature" in params:
            model_settings["temperature"] = params["temperature"]
        if "reasoning_effort" in params:
            model_settings["reasoning_effort"] = params["reasoning_effort"]

        # Build run kwargs
        run_kwargs: dict[str, Any] = {
            "user_prompt": user_message,
            "instructions": system_prompt,
        }

        # Model override
        model_override = params.get("model")
        if model_override:
            run_kwargs["model"] = model_override

        if model_settings:
            run_kwargs["model_settings"] = model_settings

        # Execute the agent
        result = await agent.run(**run_kwargs)

        # Extract output
        raw_output = result.output
        if isinstance(raw_output, str):
            output_str = raw_output
        else:
            # Structured output (Pydantic BaseModel or other)
            try:
                from pydantic import BaseModel
                if isinstance(raw_output, BaseModel):
                    output_str = raw_output.model_dump_json(indent=2)
                else:
                    output_str = json.dumps(raw_output, default=str, indent=2)
            except Exception:
                output_str = str(raw_output)

        # Extract usage
        usage = result.usage()
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

        # Determine model used
        model_used = _resolve_model_used(result, agent, model_override)

        # Extract tool calls
        tool_calls = _extract_tool_calls(result)

        return {
            "output": output_str,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model_used,
            "tool_calls": tool_calls,
        }

    return callable_fn


def _resolve_model_used(
    result: Any,
    agent: Any,
    model_override: str | None,
) -> str:
    """Determine the model name actually used for a run.

    Checks the result object first, then falls back to the override
    or the agent's default model.
    """
    # Try to get model from result metadata
    # PydanticAI doesn't expose this directly on result, so fall back
    if model_override:
        return model_override

    return _extract_model_name(agent) or "unknown"


def _extract_tool_calls(result: Any) -> list[dict[str, Any]]:
    """Extract tool call traces from a PydanticAI result.

    Walks ``result.all_messages()`` looking for parts with
    ``part_kind == 'tool-call'`` and ``part_kind == 'tool-return'``.
    """
    tool_calls: list[dict[str, Any]] = []
    returns: dict[str, Any] = {}  # tool_call_id -> return content

    try:
        messages = result.all_messages()
    except Exception:
        return tool_calls

    # First pass: collect all tool returns by tool_call_id
    for msg in messages:
        parts = getattr(msg, "parts", None) or []
        for part in parts:
            part_kind = getattr(part, "part_kind", None)
            if part_kind == "tool-return":
                call_id = getattr(part, "tool_call_id", None)
                content = getattr(part, "content", None)
                if call_id is not None:
                    returns[call_id] = content

    # Second pass: collect tool calls and match with returns
    for msg in messages:
        parts = getattr(msg, "parts", None) or []
        for part in parts:
            part_kind = getattr(part, "part_kind", None)
            if part_kind == "tool-call":
                call_id = getattr(part, "tool_call_id", None)
                tool_name = getattr(part, "tool_name", "unknown")
                args = getattr(part, "args", None)

                # Serialize args if needed
                if isinstance(args, dict):
                    args_serialized = args
                elif args is not None:
                    try:
                        args_serialized = json.loads(args) if isinstance(args, str) else str(args)
                    except (json.JSONDecodeError, TypeError):
                        args_serialized = str(args)
                else:
                    args_serialized = {}

                call_info: dict[str, Any] = {
                    "tool_name": tool_name,
                    "args": args_serialized,
                }

                # Attach return value if available
                if call_id and call_id in returns:
                    ret = returns[call_id]
                    if isinstance(ret, str):
                        call_info["return_value"] = ret
                    else:
                        call_info["return_value"] = str(ret)

                tool_calls.append(call_info)

    return tool_calls


# ---------------------------------------------------------------------------
# API key bridging
# ---------------------------------------------------------------------------

_PROVIDER_ENV_MAP: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "cohere": "COHERE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "together": "TOGETHER_API_KEY",
}


def _bridge_api_keys(get_key: Any) -> None:
    """Set API keys from biscotti key store into env vars for PydanticAI."""
    import os
    for provider, env_var in _PROVIDER_ENV_MAP.items():
        if not os.environ.get(env_var):
            key = get_key(provider)
            if key:
                os.environ[env_var] = key
