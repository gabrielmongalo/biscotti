"""
tests/test_biscotti.py
~~~~~~~~~~~~~~~~~~~~~~~
Core unit tests for biscotti.
"""
import pytest
import pytest_asyncio

from biscotti import Biscotti, biscotti_agent, register_callable
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

def test_biscotti_agent_decorator():
    @biscotti_agent(
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
    assert s.judge_model == "anthropic:claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# Eval store tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_settings_crud(store: PromptStore):
    s = await store.get_agent_settings("recipe_agent")
    assert s.judge_criteria == ""
    assert s.judge_model == "anthropic:claude-sonnet-4-20250514"

    await store.update_agent_settings("recipe_agent", judge_criteria="Be accurate", judge_model="openai:gpt-4o")
    s = await store.get_agent_settings("recipe_agent")
    assert s.judge_criteria == "Be accurate"
    assert s.judge_model == "openai:gpt-4o"


@pytest.mark.asyncio
async def test_save_eval_run(store: PromptStore):
    er = await store.save_eval_run(EvalRun(
        agent_name="test_agent",
        prompt_version=1,
        judge_model="anthropic:claude-sonnet-4-20250514",
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
# Eval module tests
# ---------------------------------------------------------------------------

def test_build_judge_criteria_prompt():
    from biscotti.eval import build_judge_generation_prompt
    prompt = build_judge_generation_prompt(
        system_prompt="You are a chef. Ingredients: {{ingredients}}. Diet: {{dietary_restrictions}}.",
        variables=["ingredients", "dietary_restrictions"],
    )
    assert "ingredients" in prompt
    assert "dietary_restrictions" in prompt
    assert "chef" in prompt.lower()
