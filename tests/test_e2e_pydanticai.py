"""
tests/test_e2e_pydanticai.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
End-to-end test: simulates a new developer onboarding a PydanticAI project
with biscotti. Exercises the full flow:

    biscotti init → uncomment config → register() → biscotti dev startup
    → API endpoints → run agents → tool calls + structured output

Uses PydanticAI's built-in TestModel so no API key is required.
"""
import json
import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from biscotti import Biscotti
from biscotti.cli import _scan_for_agents, _init_config, _import_user_config
from biscotti.registry import list_agents, get_agent
from biscotti.runner import get_callable, execute_run
from biscotti.models import RunRequest


# ---------------------------------------------------------------------------
# Fixtures: a temporary project that mirrors a real PydanticAI codebase
# ---------------------------------------------------------------------------

_TASTING_NOTES_MODEL = """\
from pydantic import BaseModel, Field

class TastingNotesSummary(BaseModel):
    summary: str = Field(description="Community consensus tasting summary")
    aroma_profile: list[str] = Field(default_factory=list)
    flavor_profile: list[str] = Field(default_factory=list)
    consensus_score: float | None = None
    confidence: str = "medium"
"""

_VINTAGE_MODEL = """\
from pydantic import BaseModel, Field

class VintageAssessment(BaseModel):
    vintage_year: int
    region: str
    overall_quality: str = Field(description="quality rating")
    drinking_window: str
    summary: str
"""

_TASTING_NOTES_AGENT = """\
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
from app.models.tasting_notes import TastingNotesSummary

tasting_notes_agent = Agent(
    "test",
    model_settings=ModelSettings(temperature=0.7),
    output_type=TastingNotesSummary,
    retries=1,
)

@tasting_notes_agent.instructions
def _instructions() -> str:
    return \"\"\"You are a community voice for CellarTracker.
Synthesize tasting notes into a coherent summary.
Be specific about aromas and flavors.\"\"\"
"""

_VINTAGE_AGENT = """\
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings
from app.models.vintage import VintageAssessment

vintage_agent = Agent(
    "test",
    model_settings=ModelSettings(temperature=0.5),
    output_type=VintageAssessment,
    retries=1,
)

@vintage_agent.system_prompt
def vintage_system_prompt() -> str:
    return \"\"\"You are a wine vintage assessment expert.
Evaluate the given vintage using weather data and historical scores.\"\"\"

@vintage_agent.tool_plain
def get_regional_weather(region: str, year: int) -> str:
    \"\"\"Fetch weather data for a wine region and vintage year.\"\"\"
    return f"Weather for {region} {year}: avg temp 22C, rainfall 450mm, dry harvest."

@vintage_agent.tool_plain
def get_historical_scores(region: str, year: int) -> str:
    \"\"\"Fetch historical critic scores for a region's vintage.\"\"\"
    return f"Scores for {region} {year}: Parker 93, Suckling 95."
"""


@pytest.fixture
def project_dir():
    """Create a temporary PydanticAI project with two agents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create package structure
        (root / "app").mkdir()
        (root / "app" / "__init__.py").write_text("")
        (root / "app" / "models").mkdir()
        (root / "app" / "models" / "__init__.py").write_text("")
        (root / "app" / "agents").mkdir()
        (root / "app" / "agents" / "__init__.py").write_text("")

        # Write models
        (root / "app" / "models" / "tasting_notes.py").write_text(_TASTING_NOTES_MODEL)
        (root / "app" / "models" / "vintage.py").write_text(_VINTAGE_MODEL)

        # Write agents
        (root / "app" / "agents" / "tasting_notes_agent.py").write_text(_TASTING_NOTES_AGENT)
        (root / "app" / "agents" / "vintage_agent.py").write_text(_VINTAGE_AGENT)

        yield root


# ---------------------------------------------------------------------------
# Phase 1: biscotti init — agent scanning
# ---------------------------------------------------------------------------

class TestInit:
    def test_scan_finds_both_agents(self, project_dir):
        agents = _scan_for_agents(project_dir)
        names = sorted([a[1] for a in agents])
        assert "tasting_notes_agent" in names
        assert "vintage_agent" in names

    def test_init_generates_config(self, project_dir):
        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            _init_config()
            config = (project_dir / "biscotti_config.py").read_text()
            assert "from biscotti.pydanticai import register" in config
            assert "tasting_notes_agent" in config
            assert "vintage_agent" in config
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# Phase 2: register() — agent introspection
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_both_agents(self, project_dir):
        """Import config in the project dir, verify both agents register."""
        import sys
        old_path = sys.path[:]
        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            sys.path.insert(0, str(project_dir))

            from biscotti.pydanticai import register

            # Import agents the same way the config would
            sys.modules.pop("app.agents.tasting_notes_agent", None)
            sys.modules.pop("app.agents.vintage_agent", None)
            sys.modules.pop("app.models.tasting_notes", None)
            sys.modules.pop("app.models.vintage", None)
            sys.modules.pop("app", None)
            sys.modules.pop("app.agents", None)
            sys.modules.pop("app.models", None)

            from app.agents.tasting_notes_agent import tasting_notes_agent
            from app.agents.vintage_agent import vintage_agent

            register(tasting_notes_agent, name="tasting-notes")
            register(vintage_agent, name="vintage")

            # Verify tasting-notes
            meta_tn = get_agent("tasting-notes")
            assert meta_tn is not None
            assert "CellarTracker" in meta_tn.default_system_prompt
            assert meta_tn._pydanticai_output["type"] == "TastingNotesSummary"
            assert len(getattr(meta_tn, "_pydanticai_tools", [])) == 0
            assert get_callable("tasting-notes") is not None

            # Verify vintage
            meta_v = get_agent("vintage")
            assert meta_v is not None
            assert "vintage" in meta_v.default_system_prompt.lower()
            assert meta_v._pydanticai_output["type"] == "VintageAssessment"
            tools = getattr(meta_v, "_pydanticai_tools", [])
            tool_names = [t["name"] for t in tools]
            assert "get_regional_weather" in tool_names
            assert "get_historical_scores" in tool_names
            assert get_callable("vintage") is not None

        finally:
            os.chdir(old_cwd)
            sys.path[:] = old_path


# ---------------------------------------------------------------------------
# Phase 3: run agents — structured output + tool calls
# ---------------------------------------------------------------------------

class TestRunAgents:
    @pytest.fixture(autouse=True)
    def _register_agents(self, project_dir):
        """Register both agents for run tests."""
        import sys
        old_path = sys.path[:]
        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            sys.path.insert(0, str(project_dir))

            # Clear cached modules to get fresh imports
            for mod in list(sys.modules):
                if mod.startswith("app"):
                    del sys.modules[mod]

            from biscotti.pydanticai import register
            from app.agents.tasting_notes_agent import tasting_notes_agent
            from app.agents.vintage_agent import vintage_agent

            register(tasting_notes_agent, name="tasting-notes")
            register(vintage_agent, name="vintage")
            yield
        finally:
            os.chdir(old_cwd)
            sys.path[:] = old_path

    @pytest.mark.anyio
    async def test_tasting_notes_structured_output(self):
        """Tasting notes agent returns structured TastingNotesSummary."""
        fn = get_callable("tasting-notes")
        result = await fn(
            "Wine: Margaux 2015. Notes: blackcurrant, cedar, long finish.",
            "You are a wine summarizer.",
            {},
        )

        assert "output" in result
        assert result["input_tokens"] > 0
        assert result["output_tokens"] > 0

        # Output should be valid JSON (structured output serialized)
        parsed = json.loads(result["output"])
        assert "summary" in parsed

    @pytest.mark.anyio
    async def test_vintage_agent_calls_tools(self):
        """Vintage agent uses tools and returns structured VintageAssessment."""
        fn = get_callable("vintage")
        result = await fn(
            "Assess Burgundy 2019 vintage.",
            "You are a vintage expert. Use the tools.",
            {},
        )

        assert "output" in result
        assert result["input_tokens"] > 0

        # Should have tool calls (TestModel calls all tools by default)
        tool_calls = result.get("tool_calls", [])
        assert len(tool_calls) >= 1, f"Expected tool calls, got {tool_calls}"

        # Check tool call structure
        tool_names = [tc.get("tool_name") for tc in tool_calls]
        # TestModel calls tools — at minimum we should see some calls
        assert any("get_regional_weather" in str(n) or "get_historical_scores" in str(n)
                    or "final_result" in str(n)
                    for n in tool_names), f"Unexpected tool names: {tool_names}"

        # Check tool calls have args
        for tc in tool_calls:
            assert "args" in tc

        # Check return values are captured
        non_final = [tc for tc in tool_calls if tc.get("tool_name") != "final_result"]
        for tc in non_final:
            assert "return_value" in tc, f"Missing return_value for {tc.get('tool_name')}"

    @pytest.mark.anyio
    async def test_tool_calls_persist_through_runner(self):
        """Tool calls flow through execute_run and persist in the store."""
        from biscotti import Biscotti

        async with Biscotti(storage=":memory:") as bi:
            req = RunRequest(
                agent_name="vintage",
                user_message="Assess Burgundy 2019.",
            )
            resp = await execute_run(req, bi.store)

            assert resp.outcome.value == "success"
            assert len(resp.tool_calls) >= 1

            # Verify persistence
            runs = await bi.store.list_runs("vintage")
            assert len(runs) == 1
            assert len(runs[0].tool_calls) >= 1


# ---------------------------------------------------------------------------
# Phase 4: API endpoints — full server simulation
# ---------------------------------------------------------------------------

class TestAPI:
    @pytest_asyncio.fixture
    async def client(self, project_dir):
        """Boot a full biscotti app with registered agents."""
        import sys
        from httpx import AsyncClient, ASGITransport
        from fastapi import FastAPI

        old_path = sys.path[:]
        old_cwd = os.getcwd()
        try:
            os.chdir(project_dir)
            sys.path.insert(0, str(project_dir))

            for mod in list(sys.modules):
                if mod.startswith("app"):
                    del sys.modules[mod]

            from biscotti.pydanticai import register
            from app.agents.tasting_notes_agent import tasting_notes_agent
            from app.agents.vintage_agent import vintage_agent

            register(tasting_notes_agent, name="tasting-notes")
            register(vintage_agent, name="vintage")

            bi = Biscotti(storage=":memory:")
            app = FastAPI()
            app.mount("/biscotti", bi.app)

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                timeout=30,
            ) as c:
                yield c
        finally:
            os.chdir(old_cwd)
            sys.path[:] = old_path

    @pytest.mark.anyio
    async def test_list_agents_includes_tools_and_output(self, client):
        resp = await client.get("/biscotti/api/agents")
        assert resp.status_code == 200
        agents = resp.json()

        by_name = {a["name"]: a for a in agents}

        assert "tasting-notes" in by_name
        assert by_name["tasting-notes"]["output_type"] == "TastingNotesSummary"
        assert by_name["tasting-notes"]["tool_count"] == 0

        assert "vintage" in by_name
        assert by_name["vintage"]["output_type"] == "VintageAssessment"
        assert by_name["vintage"]["tool_count"] == 2

    @pytest.mark.anyio
    async def test_agent_detail_has_tool_definitions(self, client):
        resp = await client.get("/biscotti/api/agents/vintage")
        assert resp.status_code == 200
        detail = resp.json()

        assert detail["output_type"]["type"] == "VintageAssessment"
        assert "properties" in detail["output_type"]["schema"]

        tools = detail["tools"]
        assert len(tools) == 2
        tool_names = [t["name"] for t in tools]
        assert "get_regional_weather" in tool_names
        assert "get_historical_scores" in tool_names

        # Tools should have descriptions
        for t in tools:
            assert t["description"], f"Tool {t['name']} missing description"

    @pytest.mark.anyio
    async def test_run_returns_tool_calls(self, client):
        resp = await client.post("/biscotti/api/run", json={
            "agent_name": "vintage",
            "user_message": "Assess Burgundy 2019.",
        })
        assert resp.status_code == 200
        result = resp.json()

        assert result["outcome"] == "success"
        assert result["tool_calls"], "Expected tool_calls in response"

    @pytest.mark.anyio
    async def test_run_returns_structured_output(self, client):
        resp = await client.post("/biscotti/api/run", json={
            "agent_name": "tasting-notes",
            "user_message": "Wine: Margaux 2015. Rich blackcurrant and cedar.",
        })
        assert resp.status_code == 200
        result = resp.json()

        assert result["outcome"] == "success"
        parsed = json.loads(result["output"])
        assert "summary" in parsed

    @pytest.mark.anyio
    async def test_run_history_persists_tool_calls(self, client):
        # Run first
        await client.post("/biscotti/api/run", json={
            "agent_name": "vintage",
            "user_message": "Assess Burgundy 2019.",
        })

        # Check history
        resp = await client.get("/biscotti/api/agents/vintage/runs")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) >= 1
        assert runs[0]["tool_calls"], "tool_calls not persisted in run history"
