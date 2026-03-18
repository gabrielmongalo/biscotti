"""
biscotti.registry
~~~~~~~~~~~~~~~~~~
Global agent registry and the @biscotti decorator.

Usage::

    from biscotti import biscotti

    @biscotti(name="recipe agent")
    async def recipe_agent(user_message: str, system_prompt: str) -> str:
        \"\"\"You are a creative chef. Suggest recipes the user will love.\"\"\"
        result = await agent.run(user_message, instructions=system_prompt)
        return result.output
"""
from __future__ import annotations

import functools
import re
from typing import Any, Callable

from .models import AgentMeta

# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, AgentMeta] = {}


def get_registry() -> dict[str, AgentMeta]:
    """Return the current agent registry (name → AgentMeta)."""
    return _REGISTRY


def register_agent(meta: AgentMeta) -> None:
    """Manually register an agent (used internally by @biscotti)."""
    _REGISTRY[meta.name] = meta


def get_agent(name: str) -> AgentMeta | None:
    return _REGISTRY.get(name)


def list_agents() -> list[AgentMeta]:
    return list(_REGISTRY.values())


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def biscotti(
    name: str,
    description: str = "",
    variables: list[str] | None = None,
    default_system_prompt: str = "",
    tags: list[str] | None = None,
    models: list[str] | None = None,
) -> Callable:
    """
    Decorator that registers an agent function with biscotti.

    The function's docstring is used as the initial system prompt seed.
    Variables (``{{var}}``) are auto-detected from it.

    Parameters
    ----------
    name:
        Human-readable name shown in the UI. Must be unique.
    description:
        Short description shown in the agent list.
    default_system_prompt:
        Override for the initial prompt. If omitted, uses the docstring.
    """
    def decorator(fn: Callable) -> Callable:
        # Docstring is the primary source for the initial prompt
        prompt = default_system_prompt or (fn.__doc__ or "").strip()

        # Auto-detect variables from the prompt
        detected = re.findall(r"\{\{(\w+)\}\}", prompt)
        resolved_vars = list(dict.fromkeys((variables or []) + detected))

        # Description: use explicit, or first line of docstring only if
        # docstring isn't being used as the prompt (i.e. explicit prompt given)
        desc = description
        if not desc:
            if default_system_prompt and fn.__doc__:
                desc = fn.__doc__.strip().split("\n")[0].strip()
            else:
                desc = name

        meta = AgentMeta(
            name=name,
            description=desc,
            variables=resolved_vars,
            default_system_prompt=prompt,
            tags=tags or [],
            models=models or [],
        )
        register_agent(meta)

        # Attach metadata to the function for introspection
        fn._biscotti_meta = meta  # type: ignore[attr-defined]

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await fn(*args, **kwargs)

        wrapper._biscotti_meta = meta  # type: ignore[attr-defined]

        # Auto-register the callable so no separate bind() is needed
        from .runner import register_callable
        register_callable(name, wrapper)

        return wrapper

    return decorator
