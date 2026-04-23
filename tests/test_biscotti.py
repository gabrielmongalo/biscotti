"""
tests/test_biscotti.py
~~~~~~~~~~~~~~~~~~~~~~~
Core unit tests for biscotti.
"""
import pytest
import pytest_asyncio

from biscotti import Biscotti, biscotti
from biscotti.models import PromptStatus, PromptVersionCreate, TestCaseCreate
from biscotti.store import PromptStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def store():
    s = PromptStore(":memory:")
    await s.connect()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def docs():
    d = Biscotti(storage=":memory:")
    await d.__aenter__()
    yield d
    await d.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

def test_biscotti_decorator():
    @biscotti(
        name="test agent",
        description="A test agent",
        default_system_prompt="You are helpful. User data: {{user_data}}",
    )
    async def my_agent(msg: str, sys: str) -> str:
        return "ok"

    from biscotti.registry import get_agent
    meta = get_agent("test agent")
    assert meta is not None
    assert meta.name == "test agent"
    assert "user_data" in meta.variables


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_and_retrieve_version(store: PromptStore):
    pv = await store.create_prompt_version(PromptVersionCreate(
        agent_name="test_agent",
        system_prompt="You are {{role}}.",
        notes="initial",
    ))
    assert pv.id is not None
    assert pv.version == 1
    assert "role" in pv.variables

    retrieved = await store.get_prompt_version(pv.id)
    assert retrieved.system_prompt == "You are {{role}}."


@pytest.mark.asyncio
async def test_promote_to_current(store: PromptStore):
    pv1 = await store.create_prompt_version(PromptVersionCreate(
        agent_name="test_agent", system_prompt="v1 prompt"))
    pv2 = await store.create_prompt_version(PromptVersionCreate(
        agent_name="test_agent", system_prompt="v2 prompt"))

    await store.set_status(pv1.id, PromptStatus.current)
    current = await store.get_current_version("test_agent")
    assert current.version == 1

    # Promoting v2 should demote v1
    await store.set_status(pv2.id, PromptStatus.current)
    current = await store.get_current_version("test_agent")
    assert current.version == 2

    pv1_updated = await store.get_prompt_version(pv1.id)
    assert pv1_updated.status == PromptStatus.archived


@pytest.mark.asyncio
async def test_test_case_crud(store: PromptStore):
    tc = await store.upsert_test_case(TestCaseCreate(
        agent_name="test_agent",
        name="quick dinner",
        user_message="Suggest a quick dinner recipe",
        variable_values={"occasion": "weeknight"},
    ))
    assert tc.id is not None

    cases = await store.list_test_cases("test_agent")
    assert len(cases) == 1
    assert cases[0].name == "quick dinner"

    await store.delete_test_case("test_agent", "quick dinner")
    assert await store.list_test_cases("test_agent") == []


# ---------------------------------------------------------------------------
# Runner tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_with_callable(docs: Biscotti):
    from biscotti.registry import register_agent
    from biscotti.models import AgentMeta
    from biscotti.runner import register_callable
    from biscotti.models import RunRequest

    register_agent(AgentMeta(
        name="run_test_agent",
        default_system_prompt="You are helpful. Context: {{ctx}}",
    ))

    async def my_fn(user_msg: str, system_prompt: str) -> str:
        return f"Echo: {user_msg}"

    register_callable("run_test_agent", my_fn)

    from biscotti.runner import execute_run
    response = await execute_run(
        RunRequest(
            agent_name="run_test_agent",
            user_message="Hello!",
            variable_values={"ctx": "test context"},
        ),
        docs.store,
    )

    assert response.outcome == "success"
    assert "Hello!" in response.output


@pytest.mark.asyncio
async def test_run_no_callable(docs: Biscotti):
    from biscotti.registry import register_agent
    from biscotti.models import AgentMeta, RunRequest
    from biscotti.runner import execute_run

    register_agent(AgentMeta(
        name="no_callable_agent",
        default_system_prompt="You are helpful.",
    ))

    response = await execute_run(
        RunRequest(agent_name="no_callable_agent", user_message="test"),
        docs.store,
    )
    assert response.outcome == "error"
    assert "No callable" in (response.error_message or "")


# ---------------------------------------------------------------------------
# Eval model tests
# ---------------------------------------------------------------------------

from biscotti.models import JudgeCriteria, Criterion, EvalScore, CriterionResult, AgentSettings, EvalRun


def test_judge_criteria_model():
    criteria = JudgeCriteria(criteria=[
        Criterion(name="Uses ingredients", description="Output references provided ingredients"),
        Criterion(name="Respects restrictions", description="Honors dietary restrictions", weight=2.0),
    ])
    assert len(criteria.criteria) == 2
    assert criteria.criteria[1].weight == 2.0


def test_eval_score_model():
    score = EvalScore(
        score=4.2,
        reasoning="Good overall",
        criteria_results=[
            CriterionResult(criterion="Uses ingredients", passed=True, note="yes"),
        ],
    )
    assert score.score == 4.2
    assert score.criteria_results[0].passed is True


def test_agent_settings_defaults():
    s = AgentSettings(agent_name="test")
    assert s.judge_criteria == ""
    assert s.judge_model == "anthropic:claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Eval store tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_settings_crud(store: PromptStore):
    s = await store.get_agent_settings("recipe_agent")
    assert s.judge_criteria == ""
    assert s.judge_model == "anthropic:claude-sonnet-4-6"

    await store.update_agent_settings("recipe_agent", judge_criteria="Be accurate", judge_model="openai:gpt-4o")
    s = await store.get_agent_settings("recipe_agent")
    assert s.judge_criteria == "Be accurate"
    assert s.judge_model == "openai:gpt-4o"


@pytest.mark.asyncio
async def test_save_eval_run(store: PromptStore):
    er = await store.save_eval_run(EvalRun(
        agent_name="test_agent",
        prompt_version=1,
        judge_model="anthropic:claude-sonnet-4-6",
        test_case_count=5,
        avg_score=4.2,
        min_score=3.0,
        max_score=5.0,
        pass_count=4,
        fail_count=1,
    ))
    assert er.id is not None

    runs = await store.list_eval_runs("test_agent")
    assert len(runs) == 1
    assert runs[0].avg_score == 4.2


# ---------------------------------------------------------------------------
# Mount tests
# ---------------------------------------------------------------------------

class TestBiscottiMount:
    def test_mount_adds_sub_app(self):
        """bi.mount(app) should mount biscotti sub-app at /biscotti."""
        from fastapi import FastAPI
        from biscotti import Biscotti

        host_app = FastAPI()
        bi = Biscotti(storage=":memory:")
        bi.mount(host_app)

        routes = [r.path for r in host_app.routes]
        assert "/biscotti" in routes or any("/biscotti" in str(r.path) for r in host_app.routes)

    def test_mount_custom_path(self):
        """bi.mount(app, path='/tools/biscotti') should use custom path."""
        from fastapi import FastAPI
        from biscotti import Biscotti

        host_app = FastAPI()
        bi = Biscotti(storage=":memory:")
        bi.mount(host_app, path="/tools/biscotti")

        routes = [r.path for r in host_app.routes]
        assert any("/tools/biscotti" in str(r.path) for r in host_app.routes)


# ---------------------------------------------------------------------------
# Eval module tests
# ---------------------------------------------------------------------------

class TestAzureModelRouting:
    def _setup(self, *, name="prod", deployments=None):
        from biscotti.key_store import (
            add_azure_connection,
            set_azure_deployments,
            remove_azure_connection,
        )
        remove_azure_connection(name)
        add_azure_connection(
            name,
            endpoint="https://test.openai.azure.com/",
            auth="key",
            key="test-key",
            api_version="2024-10-21",
        )
        if deployments:
            set_azure_deployments(name, deployments)

    def test_resolve_azure_openai_wire_returns_openai_model(self):
        from biscotti.eval import resolve_model
        from pydantic_ai.models.openai import OpenAIChatModel
        self._setup(deployments=[{"name": "my-gpt4o", "model": "gpt-4o", "wire": "openai", "version": None}])
        model = resolve_model("azure:prod:my-gpt4o")
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "my-gpt4o"

    def test_resolve_azure_anthropic_wire_returns_anthropic_model(self):
        from biscotti.eval import resolve_model
        from pydantic_ai.models.anthropic import AnthropicModel
        self._setup(deployments=[{"name": "insights-chat", "model": "claude-opus-4-6", "wire": "anthropic", "version": None}])
        model = resolve_model("azure:prod:insights-chat")
        assert isinstance(model, AnthropicModel)
        assert model.model_name == "insights-chat"
        # Base URL should route to /anthropic, not /openai
        base_url = str(getattr(model._provider, "base_url", ""))
        assert base_url.rstrip("/").endswith("/anthropic"), f"expected /anthropic route, got {base_url!r}"

    def test_resolve_non_azure_model_returns_string(self):
        from biscotti.eval import resolve_model
        result = resolve_model("anthropic:claude-sonnet-4-6")
        assert result == "anthropic:claude-sonnet-4-6"

    def test_resolve_azure_bad_shape_raises(self):
        import pytest
        from biscotti.eval import resolve_model
        with pytest.raises(ValueError, match="azure:<connection>:<deployment>"):
            resolve_model("azure:some-deploy")  # missing deployment

    def test_resolve_azure_connection_not_configured_raises(self):
        import pytest
        from biscotti.eval import resolve_model
        from biscotti.key_store import remove_azure_connection
        remove_azure_connection("ghost")
        with pytest.raises(ValueError, match="not configured"):
            resolve_model("azure:ghost:some-deploy")

    def test_resolve_azure_unknown_deployment_raises(self):
        import pytest
        from biscotti.eval import resolve_model
        self._setup(deployments=[{"name": "my-gpt4o", "model": "gpt-4o", "wire": "openai", "version": None}])
        with pytest.raises(ValueError, match="Deployment 'unknown-deploy' not found"):
            resolve_model("azure:prod:unknown-deploy")


class TestAzureRoundTrip:
    """Issue #1 + #4: the model ID the UI displays must round-trip back
    through resolve_model() without the user adding prefixes by hand."""

    def test_extract_and_resolve_round_trip(self):
        from biscotti.key_store import (
            add_azure_connection,
            set_azure_deployments,
            remove_azure_connection,
        )
        from biscotti.eval import resolve_model
        from biscotti.pydanticai import _extract_model_name
        from pydantic_ai import Agent

        remove_azure_connection("prod")
        add_azure_connection(
            "prod",
            endpoint="https://test.openai.azure.com",
            auth="key",
            key="test-key",
            api_version="2024-10-21",
        )
        set_azure_deployments(
            "prod",
            [{"name": "insights-chat", "model": "gpt-4o", "wire": "openai", "version": None}],
        )
        model = resolve_model("azure:prod:insights-chat")
        agent = Agent(model)
        # _extract_model_name must return the three-part form, not the bare deployment
        assert _extract_model_name(agent) == "azure:prod:insights-chat"


class TestAzureDiscoveryParser:
    """Unit-test the pure parsing logic in azure_discovery without hitting
    the network — pass canned Azure responses through _normalize_deployment."""

    def test_openai_wire_from_format(self):
        from biscotti.azure_discovery import _normalize_deployment
        result = _normalize_deployment({
            "id": "insights-gpt",
            "model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-08-06"},
        })
        assert result == {
            "name": "insights-gpt",
            "model": "gpt-4o",
            "wire": "openai",
            "version": "2024-08-06",
        }

    def test_anthropic_wire_from_format(self):
        from biscotti.azure_discovery import _normalize_deployment
        result = _normalize_deployment({
            "id": "insights-claude",
            "model": {"format": "Anthropic", "name": "claude-opus-4-6"},
        })
        assert result["wire"] == "anthropic"
        assert result["model"] == "claude-opus-4-6"

    def test_defaults_to_openai_when_format_missing(self):
        from biscotti.azure_discovery import _normalize_deployment
        result = _normalize_deployment({"id": "anon", "model": {"name": "gpt-4o"}})
        assert result["wire"] == "openai"


class TestAzureLegacyMigration:
    """The legacy set_azure_config() API should map to a 'default' connection
    so any straggler callers keep working."""

    def test_legacy_set_creates_default_connection(self):
        from biscotti.key_store import (
            set_azure_config,
            get_azure_connection,
            remove_azure_connection,
        )
        remove_azure_connection("default")
        set_azure_config(
            endpoint="https://legacy.openai.azure.com",
            key="legacy-key",
            deployments=["foo", "bar"],
        )
        conn = get_azure_connection("default")
        assert conn is not None
        assert conn["auth"] == "key"
        assert [d["name"] for d in conn["deployments"]] == ["foo", "bar"]
        assert all(d["wire"] == "openai" for d in conn["deployments"])


class TestListModelsFilter:
    """Issue #3: list_models should hide models whose provider isn't connected."""

    async def test_unconnected_providers_hidden(self, tmp_path, monkeypatch):
        import httpx
        from httpx import ASGITransport
        from fastapi import FastAPI
        from biscotti.store import PromptStore
        from biscotti.router import build_router
        from biscotti.registry import _REGISTRY, AgentMeta
        from biscotti.key_store import _KEYS, set_key, _AZURE_CONNECTIONS

        for p in [
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
            "MISTRAL_API_KEY", "COHERE_API_KEY", "GROQ_API_KEY",
            "XAI_API_KEY", "TOGETHER_API_KEY", "DEEPSEEK_API_KEY",
            "AZURE_OPENAI_API_KEY",
        ]:
            monkeypatch.delenv(p, raising=False)
        _KEYS.clear()
        _AZURE_CONNECTIONS.clear()

        # Connect only Anthropic.
        set_key("anthropic", "test-key")

        _REGISTRY["demo"] = AgentMeta(
            name="demo", prompt="", variables=[], models=[],
            default_model=None, default_user_message=None, output=None, tools=None,
        )

        store = PromptStore(str(tmp_path / "db.sqlite"))
        await store.connect()
        app = FastAPI()
        app.include_router(build_router(store))

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/agents/demo/models")
        assert resp.status_code == 200
        all_models = resp.json()["all"]
        # Anthropic models visible; OpenAI hidden
        assert any(m.startswith("claude-") or m.startswith("anthropic:") for m in all_models), all_models
        assert not any(m.startswith("gpt-") or m.startswith("openai:") for m in all_models), all_models
        await store.close()


class TestAzurePricing:
    def test_estimate_cost_resolves_azure_underlying_model(self):
        from biscotti.key_store import (
            add_azure_connection,
            set_azure_deployments,
            remove_azure_connection,
        )
        from biscotti.runner import estimate_cost
        remove_azure_connection("prod")
        add_azure_connection("prod", endpoint="https://x.openai.azure.com", auth="key", key="k")
        set_azure_deployments("prod", [
            {"name": "insights", "model": "gpt-4o", "wire": "openai", "version": None}
        ])
        cost = estimate_cost("azure:prod:insights", 1_000_000, 1_000_000)
        # gpt-4o: $2.50 input + $10.00 output per 1M = $12.50
        assert cost == 12.5

    def test_estimate_cost_none_when_underlying_unknown(self):
        from biscotti.key_store import (
            add_azure_connection,
            set_azure_deployments,
            remove_azure_connection,
        )
        from biscotti.runner import estimate_cost
        remove_azure_connection("prod")
        add_azure_connection("prod", endpoint="https://x.openai.azure.com", auth="key", key="k")
        set_azure_deployments("prod", [
            {"name": "mystery", "model": None, "wire": "openai", "version": None}
        ])
        assert estimate_cost("azure:prod:mystery", 1000, 1000) is None


def test_build_judge_criteria_prompt():
    from biscotti.eval import build_judge_generation_prompt
    prompt = build_judge_generation_prompt(
        system_prompt="You are a chef. Ingredients: {{ingredients}}. Diet: {{dietary_restrictions}}.",
        variables=["ingredients", "dietary_restrictions"],
    )
    assert "ingredients" in prompt
    assert "dietary_restrictions" in prompt
    assert "chef" in prompt.lower()


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_settings_endpoint(docs: Biscotti):
    import httpx
    from biscotti.registry import register_agent
    from biscotti.models import AgentMeta

    register_agent(AgentMeta(name="settings_test_agent", default_system_prompt="You are helpful."))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=docs.app), base_url="http://test") as client:
        resp = await client.get("/api/agents/settings_test_agent/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["judge_criteria"] == ""
        assert "anthropic" in data["judge_model"]

        resp = await client.put("/api/agents/settings_test_agent/settings", json={
            "judge_criteria": "Be accurate",
            "judge_model": "openai:gpt-4o",
        })
        assert resp.status_code == 200

        resp = await client.get("/api/agents/settings_test_agent/settings")
        assert resp.json()["judge_criteria"] == "Be accurate"


# ---------------------------------------------------------------------------
# Integration test: full eval flow (mocked LLM)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_eval_flow(docs: Biscotti):
    from unittest.mock import AsyncMock, patch
    import httpx
    from biscotti.registry import register_agent
    from biscotti.models import AgentMeta, TestCaseCreate, EvalScore, CriterionResult
    from biscotti.runner import register_callable

    register_agent(AgentMeta(
        name="eval_test_agent",
        default_system_prompt="You are a helper. Topic: {{topic}}",
    ))
    async def stub_fn(msg, sys): return "Here is some helpful info about the topic."
    register_callable("eval_test_agent", stub_fn)

    await docs.store.upsert_test_case(TestCaseCreate(
        agent_name="eval_test_agent", name="basic", user_message="Help me", variable_values={"topic": "cooking"},
    ))

    await docs.store.update_agent_settings("eval_test_agent", judge_criteria="- Mentions topic\n- Is helpful")

    mock_score = EvalScore(score=4.0, reasoning="Good", criteria_results=[
        CriterionResult(criterion="Mentions topic", passed=True, note="yes"),
        CriterionResult(criterion="Is helpful", passed=True, note="yes"),
    ])

    with patch("biscotti.eval.judge_output", new_callable=AsyncMock, return_value=mock_score):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=docs.app), base_url="http://test") as client:
            resp = await client.post("/api/agents/eval_test_agent/eval", json={})
            assert resp.status_code == 200
            data = resp.json()
            assert data["test_case_count"] == 1
            assert data["avg_score"] == 4.0
            assert data["pass_count"] == 1
