"""Task 9: runner falls back to the stored user-message template when
the RunRequest doesn't specify a user_message."""
from __future__ import annotations

import os
import pytest
from pydantic_ai import Agent

from biscotti import Biscotti
from biscotti.models import RunRequest
from biscotti.pydanticai import register, _PENDING_SEEDS
from biscotti.runner import execute_run
from _builders_for_tests import wine_builder

os.environ.setdefault("OPENAI_API_KEY", "sk-test")


@pytest.fixture(autouse=True)
def _clear_pending():
    _PENDING_SEEDS.clear()
    yield
    _PENDING_SEEDS.clear()


@pytest.mark.asyncio
async def test_runner_uses_stored_user_message_when_request_omits_one():
    """Register a stub agent, seed via builder, run without user_message —
    the rendered user prompt should come from the stored template."""
    # Stub agent that echoes the user_message it received
    a = Agent("openai:gpt-4o", instructions="sys")
    h = register(a, name="runner-fallback")
    h.user_prompt(wine_builder)

    # Override the registered callable with a local stub so we don't hit OpenAI
    from biscotti.runner import register_callable

    async def stub_callable(user_msg, system_prompt, params=None):
        return {"output": f"GOT: {user_msg}", "input_tokens": 0, "output_tokens": 0, "model": "stub", "tool_calls": []}

    register_callable("runner-fallback", stub_callable)

    async with Biscotti(storage=":memory:") as bi:
        req = RunRequest(
            agent_name="runner-fallback",
            user_message="",  # intentionally empty
            variable_values={"wine": "Cheval Blanc", "producer": "Château Cheval Blanc"},
            run_eval=False,
        )
        resp = await execute_run(req, bi.store)

        assert resp.outcome.value == "success"
        assert "Wine: Cheval Blanc" in resp.output
        assert "Producer: Château Cheval Blanc" in resp.output


@pytest.mark.asyncio
async def test_runner_honors_explicit_user_message_over_stored_one():
    a = Agent("openai:gpt-4o", instructions="sys")
    h = register(a, name="runner-explicit")
    h.user_prompt(wine_builder)

    from biscotti.runner import register_callable

    async def stub_callable(user_msg, system_prompt, params=None):
        return {"output": f"GOT: {user_msg}", "input_tokens": 0, "output_tokens": 0, "model": "stub", "tool_calls": []}

    register_callable("runner-explicit", stub_callable)

    async with Biscotti(storage=":memory:") as bi:
        req = RunRequest(
            agent_name="runner-explicit",
            user_message="Custom override: {{wine}}",
            variable_values={"wine": "Screaming Eagle"},
            run_eval=False,
        )
        resp = await execute_run(req, bi.store)
        # Explicit override wins — stored template is not used
        assert "Custom override: Screaming Eagle" in resp.output
        assert "Producer:" not in resp.output
