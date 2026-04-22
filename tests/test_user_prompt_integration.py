"""Integration test for the ``@handle.user_prompt`` decorator.

Four PydanticAI agents, two of which share the same builder function via
stacked decorators. One binding uses the ``extras=`` kwarg to fix a non-dict
builder arg. The decorator writes the AST-extracted ``{{var}}`` template to
each agent's ``default_message``, which the UI shows as the starter user
message in Ad hoc mode. Prompt engineers edit it in place and save as a
test case; no separate versioning.
"""
from __future__ import annotations

import os
import pytest
from pydantic_ai import Agent

from biscotti import Biscotti
from biscotti.pydanticai import register
from biscotti.registry import _REGISTRY
from biscotti.runner import register_callable

from _builders_for_tests import (
    full_wine_builder,
    vintage_context_builder,
)


os.environ.setdefault("OPENAI_API_KEY", "sk-test")


@pytest.fixture(autouse=True)
def _clean():
    _REGISTRY.clear()
    yield


@pytest.fixture
def wine_agents():
    """Register 4 agents with shared builders and stacked decorators."""
    wine_body_agent = Agent("openai:gpt-4o", instructions="Write a 3-4 sentence wine portrait.")
    wine_full_card_agent = Agent("openai:gpt-4o", instructions="Write a full wine card.")
    wine_vintage_agent = Agent("openai:gpt-4o", instructions="Add vintage context.")
    producer_agent = Agent("openai:gpt-4o", instructions="Summarize this producer.")

    wine_body = register(wine_body_agent, name="wine body")
    wine_full = register(wine_full_card_agent, name="wine full card")
    wine_vintage = register(wine_vintage_agent, name="wine vintage context")
    producer = register(producer_agent, name="producer summary", default_message=(
        "Producer: {{producer_name}}\nRegion: {{region}}\nCountry: {{country}}"
    ))

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

    # Bind builders — real introspectable functions from _builders_for_tests.
    # Stack the same function on both handles; use extras= for the cold-path variant.
    wine_body.user_prompt(full_wine_builder)
    wine_full.user_prompt(extras={"include_vintage_context": True})(full_wine_builder)
    wine_vintage.user_prompt(vintage_context_builder)

    return {
        "wine_body": wine_body,
        "wine_full": wine_full,
        "wine_vintage": wine_vintage,
        "producer": producer,
    }


@pytest.mark.asyncio
async def test_builder_populates_default_message(wine_agents):
    """Each @handle.user_prompt-decorated agent has meta.default_message set
    to the AST-extracted {{var}} template. The UI reads this when showing the
    Ad hoc User Message field."""
    body = wine_agents["wine_body"].meta.default_message
    assert "{{wine}}" in body
    assert "{{producer}}" in body
    # Per R1: AST approach picks the truthy branch of the IfExp conditional
    assert "Vintage: {{vintage}}" in body


@pytest.mark.asyncio
async def test_default_message_kwarg_works_without_builder(wine_agents):
    """register(..., default_message=...) sets meta.default_message when
    there is no @handle.user_prompt-decorated builder."""
    producer = wine_agents["producer"].meta.default_message
    assert "{{producer_name}}" in producer
    assert "{{region}}" in producer


@pytest.mark.asyncio
async def test_variables_auto_detected_from_builder(wine_agents):
    """Variables from the builder's dict.get() calls flow into meta.variables."""
    body_vars = set(wine_agents["wine_body"].meta.variables)
    expected = {"wine", "vintage", "producer", "varietal", "color",
                "region", "subregion", "country", "appellation"}
    assert expected.issubset(body_vars), body_vars


@pytest.mark.asyncio
async def test_builder_defaults_captured(wine_agents):
    """dict.get() second args become builder_defaults on the meta."""
    defaults = wine_agents["wine_body"].meta._builder_defaults
    assert defaults["wine"] == "Unknown"
    assert defaults["producer"] == "Unknown"
    assert defaults["vintage"] == ""


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

    cold = full_wine_builder(sample, include_vintage_context=True)
    assert "Screaming Eagle" in cold
    assert "Vintage: 2018" in cold

    warm = full_wine_builder(sample)
    assert "Screaming Eagle" in warm
    assert "Vintage: 2018" not in warm


@pytest.mark.asyncio
async def test_agent_api_endpoint_exposes_default_message(wine_agents):
    """The GET /api/agents/{name} endpoint returns default_message so the UI
    can seed it into the Ad hoc User Message field."""
    from fastapi.testclient import TestClient

    bi = Biscotti(storage=":memory:")
    client = TestClient(bi.app)

    r = client.get("/api/agents/wine%20body")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "{{wine}}" in data["default_message"]
    assert "wine" in data["variables"]
