import asyncio
import pytest
import pytest_asyncio
from biscotti.store import PromptStore
from biscotti.registry import register_agent
from biscotti.runner import register_callable
from biscotti.models import AgentMeta, BulkRunRequest, TestCaseCreate


@pytest_asyncio.fixture
async def bulk_store(tmp_path):
    s = PromptStore(str(tmp_path / "test.db"))
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
def setup_agent(bulk_store):
    register_agent(AgentMeta(
        name="bulk_agent", description="test",
        default_system_prompt="You are a test agent.",
    ))

    async def mock_fn(msg, prompt, params=None):
        model = params.get("model", "unknown") if params else "unknown"
        return {"output": f"reply to: {msg}", "input_tokens": 10, "output_tokens": 5, "model": model}

    register_callable("bulk_agent", mock_fn)
    return "bulk_agent"


class TestGenerateRunPlan:
    def test_cartesian_product(self):
        from biscotti.bulk import generate_run_plan
        plan = generate_run_plan(test_case_names=["case1", "case2"], models=["gpt-4o", "claude-sonnet-4-6"], temperatures=[0.0, 1.0], reasoning_efforts=[])
        assert len(plan) == 8

    def test_with_reasoning_efforts(self):
        from biscotti.bulk import generate_run_plan
        plan = generate_run_plan(test_case_names=["case1"], models=["o3"], temperatures=[], reasoning_efforts=["low", "high"])
        assert len(plan) == 2

    def test_plan_entry_structure(self):
        from biscotti.bulk import generate_run_plan
        plan = generate_run_plan(test_case_names=["case1"], models=["gpt-4o"], temperatures=[0.7], reasoning_efforts=[])
        assert len(plan) == 1
        entry = plan[0]
        assert entry["test_case_name"] == "case1"
        assert entry["model"] == "gpt-4o"
        assert entry["temperature"] == 0.7
        assert entry["reasoning_effort"] is None

    def test_empty_temps_and_re_gives_single_config(self):
        from biscotti.bulk import generate_run_plan
        plan = generate_run_plan(test_case_names=["case1"], models=["gpt-4o"], temperatures=[], reasoning_efforts=[])
        assert len(plan) == 1
        assert plan[0]["temperature"] is None
        assert plan[0]["reasoning_effort"] is None


class TestExecuteBulkRun:
    @pytest.mark.asyncio
    async def test_basic_bulk_run(self, bulk_store, setup_agent):
        from biscotti.bulk import execute_bulk_run
        await bulk_store.upsert_test_case(TestCaseCreate(agent_name="bulk_agent", name="case1", user_message="hello"))
        from biscotti.models import PromptVersionCreate, PromptStatus
        pv = await bulk_store.create_prompt_version(PromptVersionCreate(agent_name="bulk_agent", system_prompt="You are a test agent."))
        await bulk_store.set_status(pv.id, PromptStatus.current)

        request = BulkRunRequest(agent_name="bulk_agent", models=["gpt-4o"], temperatures=[0.7], test_case_names=["case1"], concurrency=2)
        results = []
        async for event in execute_bulk_run(request, bulk_store):
            results.append(event)

        done_events = [e for e in results if e["event"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["data"]["status"] == "completed"
        run_events = [e for e in results if e["event"] == "run_complete"]
        assert len(run_events) == 1

    @pytest.mark.asyncio
    async def test_bulk_run_multiple_configs(self, bulk_store, setup_agent):
        from biscotti.bulk import execute_bulk_run
        await bulk_store.upsert_test_case(TestCaseCreate(agent_name="bulk_agent", name="case1", user_message="hello"))
        from biscotti.models import PromptVersionCreate, PromptStatus
        pv = await bulk_store.create_prompt_version(PromptVersionCreate(agent_name="bulk_agent", system_prompt="You are a test agent."))
        await bulk_store.set_status(pv.id, PromptStatus.current)

        request = BulkRunRequest(agent_name="bulk_agent", models=["gpt-4o", "claude-sonnet-4-6"], temperatures=[0.0, 1.0], test_case_names=["case1"], concurrency=2)
        run_events = []
        async for event in execute_bulk_run(request, bulk_store):
            if event["event"] == "run_complete":
                run_events.append(event)
        assert len(run_events) == 4

    @pytest.mark.asyncio
    async def test_bulk_run_persists_to_db(self, bulk_store, setup_agent):
        from biscotti.bulk import execute_bulk_run
        await bulk_store.upsert_test_case(TestCaseCreate(agent_name="bulk_agent", name="case1", user_message="hello"))
        from biscotti.models import PromptVersionCreate, PromptStatus
        pv = await bulk_store.create_prompt_version(PromptVersionCreate(agent_name="bulk_agent", system_prompt="You are a test agent."))
        await bulk_store.set_status(pv.id, PromptStatus.current)

        request = BulkRunRequest(agent_name="bulk_agent", models=["gpt-4o"], temperatures=[0.7], test_case_names=["case1"])
        bulk_run_id = None
        async for event in execute_bulk_run(request, bulk_store):
            if event["event"] == "done":
                bulk_run_id = event["data"]["id"]

        assert bulk_run_id is not None
        bulk = await bulk_store.get_bulk_run(bulk_run_id)
        assert bulk["status"] == "completed"
        assert bulk["completed_runs"] == 1
        runs = await bulk_store.get_bulk_run_runs(bulk_run_id)
        assert len(runs) == 1
        assert runs[0].bulk_run_id == bulk_run_id
