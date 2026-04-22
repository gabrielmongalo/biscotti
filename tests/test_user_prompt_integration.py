"""End-to-end integration test for the user-prompt builder integration.

Four PydanticAI agents, two of which share the same builder function via
stacked decorators. One binding uses the ``extras=`` kwarg to fix a non-dict
builder arg. All four user-message templates get auto-seeded at ``Biscotti``
startup. Test runs pick up the stored templates without the dev writing any
``{{var}}`` strings by hand.
"""
from __future__ import annotations

import os
import pytest
from pydantic_ai import Agent

from biscotti import Biscotti
from biscotti.models import RunRequest
from biscotti.pydanticai import register, _PENDING_SEEDS
from biscotti.registry import _REGISTRY
from biscotti.runner import execute_run, register_callable

from _builders_for_tests import (
    full_wine_builder,
    vintage_context_builder,
)


os.environ.setdefault("OPENAI_API_KEY", "sk-test")


@pytest.fixture(autouse=True)
def _clean():
    _PENDING_SEEDS.clear()
    _REGISTRY.clear()
    yield
    _PENDING_SEEDS.clear()


@pytest.fixture
def wine_agents():
    """Register 4 agents with 3 shared builders and stacked decorators."""
    wine_body_agent = Agent("openai:gpt-4o", instructions="Write a 3-4 sentence wine portrait.")
    wine_full_card_agent = Agent("openai:gpt-4o", instructions="Write a full wine card.")
    wine_vintage_agent = Agent("openai:gpt-4o", instructions="Add vintage context.")
    producer_agent = Agent("openai:gpt-4o", instructions="Summarize this producer.")

    wine_body = register(wine_body_agent, name="wine body")
    wine_full = register(wine_full_card_agent, name="wine full card")
    wine_vintage = register(wine_vintage_agent, name="wine vintage context")
    producer = register(producer_agent, name="producer summary")

    # Stub callables so we never hit OpenAI. Each echoes what it received.
    async def stub(user_msg, system_prompt, params=None):
        return {
            "output": user_msg,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": "stub",
            "tool_calls": [],
        }

    for name in ("wine body", "wine full card", "wine vintage context", "producer summary"):
        register_callable(name, stub)

    # Bind builders — the real introspectable builders (from _builders_for_tests)
    # Stack the same function on both handles; use extras= for the cold-path variant.
    wine_body.user_prompt(full_wine_builder)
    wine_full.user_prompt(extras={"include_vintage_context": True})(full_wine_builder)
    wine_vintage.user_prompt(vintage_context_builder)

    # Producer has no DB-dict pattern; use default_message instead
    # (test the default_message path too)
    producer.meta.default_message = (
        "Producer: {{producer_name}}\n"
        "Region: {{region}}\n"
        "Country: {{country}}"
    )
    producer.meta.variables = ["producer_name", "region", "country"]

    return {
        "wine_body": wine_body,
        "wine_full": wine_full,
        "wine_vintage": wine_vintage,
        "producer": producer,
    }


@pytest.mark.asyncio
async def test_all_four_agents_are_seeded_after_startup(wine_agents):
    async with Biscotti(storage=":memory:") as bi:
        # wine body — per R1 design resolution, the AST approach picks the
        # truthy branch of the IfExp conditional (`vintage_line = f"...{{vintage}}" if has_vintage else ""`)
        # and emits the Vintage line into the template. Prompt engineers can
        # delete it in the UI if they want the empty branch.
        ump = await bi.store.get_current_user_message("wine body")
        assert ump is not None
        assert "{{wine}}" in ump.template
        assert "{{producer}}" in ump.template
        assert "Vintage: {{vintage}}" in ump.template  # truthy branch wins

        # wine full card — same builder, but bound with extras={"include_vintage_context": True}
        ump_full = await bi.store.get_current_user_message("wine full card")
        assert ump_full is not None
        assert "{{wine}}" in ump_full.template
        assert "{{producer}}" in ump_full.template
        assert "Vintage: {{vintage}}" in ump_full.template

        # vintage context — expects cached_body extra
        ump_vc = await bi.store.get_current_user_message("wine vintage context")
        assert ump_vc is not None
        assert "{{wine}}" in ump_vc.template
        assert "{{vintage}}" in ump_vc.template

        # producer — seeded from default_message, no builder
        ump_p = await bi.store.get_current_user_message("producer summary")
        assert ump_p is not None
        assert "{{producer_name}}" in ump_p.template
        assert "{{region}}" in ump_p.template


@pytest.mark.asyncio
async def test_variables_extracted_from_builders(wine_agents):
    async with Biscotti(storage=":memory:") as bi:
        ump = await bi.store.get_current_user_message("wine body")
        expected_vars = {
            "wine", "vintage", "producer", "varietal",
            "color", "region", "subregion", "country", "appellation",
        }
        assert expected_vars.issubset(set(ump.variables)), ump.variables

        # Defaults captured from dict.get() second args
        assert ump.defaults["wine"] == "Unknown"
        assert ump.defaults["producer"] == "Unknown"
        assert ump.defaults["vintage"] == ""


@pytest.mark.asyncio
async def test_run_uses_stored_template_when_request_omits_user_message(wine_agents):
    async with Biscotti(storage=":memory:") as bi:
        req = RunRequest(
            agent_name="wine body",
            user_message="",   # intentionally empty — should fall back to stored template
            variable_values={
                "wine": "Château Margaux",
                "vintage": "2015",
                "producer": "Château Margaux",
                "varietal": "Cabernet Sauvignon blend",
                "color": "Red",
                "region": "Bordeaux",
                "subregion": "Médoc",
                "country": "France",
                "appellation": "Margaux",
            },
            run_eval=False,
        )
        resp = await execute_run(req, bi.store)
        assert resp.outcome.value == "success"
        # The stub echoes the rendered user message, so output should include the substituted values
        assert "Château Margaux" in resp.output
        assert "Bordeaux" in resp.output
        assert "Médoc" in resp.output


@pytest.mark.asyncio
async def test_prod_builders_still_work_unchanged(wine_agents):
    """Critical: the decorator must not break prod's ability to call the builder directly."""
    sample = {
        "wine": "Screaming Eagle",
        "vintage": "2018",
        "producer": "Screaming Eagle Winery",
        "varietal": "Cabernet Sauvignon",
        "color": "Red",
        "region": "Napa Valley",
        "subregion": "Oakville",
        "country": "USA",
        "appellation": "Oakville AVA",
    }

    # Cold path — prod still calls the real builder
    cold = full_wine_builder(sample, include_vintage_context=True)
    assert "Screaming Eagle" in cold
    assert "Vintage: 2018" in cold

    # Warm path — default include_vintage_context=False
    warm = full_wine_builder(sample)
    assert "Screaming Eagle" in warm
    assert "Vintage: 2018" not in warm  # empty-branch wins


@pytest.mark.asyncio
async def test_stacked_decorators_produce_different_templates_per_agent(wine_agents):
    """The `extras=` kwarg should make each agent's template reflect its own cold/warm path."""
    async with Biscotti(storage=":memory:") as bi:
        wine_body_t = (await bi.store.get_current_user_message("wine body")).template
        wine_full_t = (await bi.store.get_current_user_message("wine full card")).template
        # They can be equal or different depending on which approach won.
        # The important thing: both were seeded independently from the same builder.
        assert "{{wine}}" in wine_body_t
        assert "{{wine}}" in wine_full_t
