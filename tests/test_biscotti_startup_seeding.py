"""Task 7: Biscotti._seed_defaults flushes pending builder seeds +
backfills default_message for agents without a builder."""
from __future__ import annotations

import os
import pytest
from pydantic_ai import Agent

from biscotti import Biscotti
from biscotti.pydanticai import register, _PENDING_SEEDS
from _builders_for_tests import wine_builder

os.environ.setdefault("OPENAI_API_KEY", "sk-test")


@pytest.fixture(autouse=True)
def _clear_pending():
    _PENDING_SEEDS.clear()
    yield
    _PENDING_SEEDS.clear()


@pytest.mark.asyncio
async def test_startup_seeds_builder_agent():
    a = Agent("openai:gpt-4o", instructions="sys-b")
    h = register(a, name="startup-builder")
    h.user_prompt(wine_builder)

    async with Biscotti(storage=":memory:") as bi:
        cur = await bi.store.get_current_user_message("startup-builder")
        assert cur is not None
        assert "{{wine}}" in cur.template
        assert "{{producer}}" in cur.template
        assert cur.defaults == {"wine": "Unknown", "producer": "Unknown"}


@pytest.mark.asyncio
async def test_startup_seeds_default_message_agent():
    a = Agent("openai:gpt-4o", instructions="sys-d")
    register(a, name="startup-dmsg", default_message="Hello {{name}}, welcome to {{place}}")

    async with Biscotti(storage=":memory:") as bi:
        cur = await bi.store.get_current_user_message("startup-dmsg")
        assert cur is not None
        assert cur.template == "Hello {{name}}, welcome to {{place}}"
        assert sorted(cur.variables) == ["name", "place"]


@pytest.mark.asyncio
async def test_startup_skips_bare_agent():
    a = Agent("openai:gpt-4o", instructions="sys-bare")
    register(a, name="startup-bare")

    async with Biscotti(storage=":memory:") as bi:
        cur = await bi.store.get_current_user_message("startup-bare")
        assert cur is None
        # But system prompt should still be seeded
        sys_cur = await bi.store.get_current_version("startup-bare")
        assert sys_cur is not None


@pytest.mark.asyncio
async def test_system_prompt_still_seeded_when_builder_present():
    """Regression: Task 7 shouldn't break the existing system-prompt seeding."""
    a = Agent("openai:gpt-4o", instructions="sys-regression")
    h = register(a, name="startup-regression")
    h.user_prompt(wine_builder)

    async with Biscotti(storage=":memory:") as bi:
        sys_cur = await bi.store.get_current_version("startup-regression")
        assert sys_cur is not None
        assert "sys-regression" in sys_cur.system_prompt
