"""Tests for the @handle.user_prompt decorator and the _PENDING_SEEDS queue."""
from __future__ import annotations

import os
import pytest
from pydantic_ai import Agent

from biscotti.pydanticai import register, _PENDING_SEEDS, flush_pending_seeds
from biscotti.store import PromptStore


os.environ.setdefault("OPENAI_API_KEY", "sk-test")


@pytest.fixture(autouse=True)
def _clear_pending_seeds():
    _PENDING_SEEDS.clear()
    yield
    _PENDING_SEEDS.clear()


def test_user_prompt_without_extras():
    a = Agent("openai:gpt-4o", instructions="sys")
    h = register(a, name="t-basic")

    @h.user_prompt
    def builder(info):
        name = info.get("wine", "Unknown")
        return f"Wine: {name}"

    assert len(_PENDING_SEEDS) == 1
    seed = _PENDING_SEEDS[0]
    assert seed.agent_name == "t-basic"
    assert seed.template == "Wine: {{wine}}"
    assert seed.variables == ["wine"]
    assert seed.defaults == {"wine": "Unknown"}
    assert "wine" in h.meta.variables


def test_user_prompt_with_extras():
    a = Agent("openai:gpt-4o", instructions="sys")
    h = register(a, name="t-extras")

    @h.user_prompt(extras={"include_vintage": True})
    def builder(info, include_vintage=False):
        name = info.get("wine", "Unknown")
        vintage = info.get("vintage", "")
        line = f"\nVintage: {vintage}" if include_vintage else ""
        return f"Wine: {name}{line}"

    seed = _PENDING_SEEDS[0]
    # Truthy branch picked — Vintage line present
    assert "{{wine}}" in seed.template
    assert "{{vintage}}" in seed.template


def test_user_prompt_stacked_decorators_seed_multiple_agents():
    a = Agent("openai:gpt-4o", instructions="sA")
    b = Agent("openai:gpt-4o", instructions="sB")
    h_a = register(a, name="t-stack-a")
    h_b = register(b, name="t-stack-b")

    @h_a.user_prompt
    @h_b.user_prompt
    def shared(info):
        return f"X: {info.get('x', '')}"

    assert len(_PENDING_SEEDS) == 2
    names = sorted(s.agent_name for s in _PENDING_SEEDS)
    assert names == ["t-stack-a", "t-stack-b"]


def test_user_prompt_returns_fn_unchanged():
    """Decorator must return the original function so prod can still call it."""
    a = Agent("openai:gpt-4o", instructions="sys")
    h = register(a, name="t-passthrough")

    @h.user_prompt
    def builder(info):
        return f"Wine: {info.get('wine', 'X')}"

    # builder should still be callable with a real dict
    assert builder({"wine": "Cheval Blanc"}) == "Wine: Cheval Blanc"


@pytest.mark.asyncio
async def test_flush_pending_seeds_creates_user_message_version():
    a = Agent("openai:gpt-4o", instructions="sys")
    h = register(a, name="t-flush")

    @h.user_prompt
    def builder(info):
        return f"Wine: {info.get('wine', 'Unknown')}"

    store = PromptStore(":memory:")
    await store.connect()
    count = await flush_pending_seeds(store)

    assert count == 1
    cur = await store.get_current_user_message("t-flush")
    assert cur is not None
    assert cur.template == "Wine: {{wine}}"
    assert cur.version == 1
    assert cur.defaults == {"wine": "Unknown"}


@pytest.mark.asyncio
async def test_flush_is_idempotent_skips_existing_agents():
    """Second flush must not clobber a user-edited template."""
    a = Agent("openai:gpt-4o", instructions="sys")
    h = register(a, name="t-idempotent")

    @h.user_prompt
    def builder(info):
        return f"Wine: {info.get('wine', 'Unknown')}"

    store = PromptStore(":memory:")
    await store.connect()
    await flush_pending_seeds(store)

    # Simulate a user edit: promote a new v2
    from biscotti.models import UserMessageVersionCreate, PromptStatus
    v2 = await store.create_user_message_version(UserMessageVersionCreate(
        agent_name="t-idempotent",
        template="UPDATED by user: {{wine}}",
    ))
    await store.set_user_message_status(v2.id, PromptStatus.current)

    # Re-queue the same seed and flush again (simulates app restart)
    @h.user_prompt
    def builder_again(info):
        return f"Wine: {info.get('wine', 'Unknown')}"

    count = await flush_pending_seeds(store)
    assert count == 0, "Existing agents should be skipped"

    cur = await store.get_current_user_message("t-idempotent")
    assert cur.template == "UPDATED by user: {{wine}}"
