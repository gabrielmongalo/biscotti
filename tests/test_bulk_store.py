import pytest
import pytest_asyncio
from biscotti.store import PromptStore
from biscotti.models import BulkRunStatus, RunLog, RunOutcome


@pytest_asyncio.fixture
async def store(tmp_path):
    s = PromptStore(str(tmp_path / "test.db"))
    await s.connect()
    yield s
    await s.close()


class TestBulkRunStore:
    @pytest.mark.asyncio
    async def test_save_and_get_bulk_run(self, store):
        bulk_id = await store.save_bulk_run(
            agent_name="test",
            prompt_version=1,
            config_matrix={"models": ["gpt-4o"], "temperatures": [0.7], "reasoning_efforts": []},
            test_cases=["case1"],
            include_eval=False,
            judge_model=None,
            concurrency=3,
            total_runs=1,
        )
        assert bulk_id > 0

        bulk = await store.get_bulk_run(bulk_id)
        assert bulk is not None
        assert bulk["agent_name"] == "test"
        assert bulk["status"] == "running"
        assert bulk["total_runs"] == 1
        assert bulk["completed_runs"] == 0

    @pytest.mark.asyncio
    async def test_update_bulk_run_progress(self, store):
        bulk_id = await store.save_bulk_run(
            agent_name="test", prompt_version=1,
            config_matrix={"models": ["gpt-4o"], "temperatures": [0.7], "reasoning_efforts": []},
            test_cases=["case1"], include_eval=False, judge_model=None, concurrency=3, total_runs=3,
        )
        await store.update_bulk_run(bulk_id, completed_runs=2)
        bulk = await store.get_bulk_run(bulk_id)
        assert bulk["completed_runs"] == 2
        assert bulk["status"] == "running"

    @pytest.mark.asyncio
    async def test_update_bulk_run_status(self, store):
        bulk_id = await store.save_bulk_run(
            agent_name="test", prompt_version=1,
            config_matrix={"models": ["gpt-4o"], "temperatures": [0.7], "reasoning_efforts": []},
            test_cases=["case1"], include_eval=False, judge_model=None, concurrency=3, total_runs=1,
        )
        await store.update_bulk_run(bulk_id, status="completed", completed_runs=1)
        bulk = await store.get_bulk_run(bulk_id)
        assert bulk["status"] == "completed"

    @pytest.mark.asyncio
    async def test_list_bulk_runs(self, store):
        for i in range(3):
            await store.save_bulk_run(
                agent_name="test", prompt_version=1,
                config_matrix={"models": ["gpt-4o"], "temperatures": [0.7], "reasoning_efforts": []},
                test_cases=["case1"], include_eval=False, judge_model=None, concurrency=3, total_runs=1,
            )
        runs = await store.list_bulk_runs("test")
        assert len(runs) == 3
        assert runs[0]["id"] >= runs[1]["id"]

    @pytest.mark.asyncio
    async def test_list_bulk_runs_with_limit(self, store):
        for i in range(5):
            await store.save_bulk_run(
                agent_name="test", prompt_version=1,
                config_matrix={"models": ["gpt-4o"], "temperatures": [0.7], "reasoning_efforts": []},
                test_cases=["case1"], include_eval=False, judge_model=None, concurrency=3, total_runs=1,
            )
        runs = await store.list_bulk_runs("test", limit=2)
        assert len(runs) == 2

    @pytest.mark.asyncio
    async def test_save_run_with_bulk_run_id(self, store):
        bulk_id = await store.save_bulk_run(
            agent_name="test", prompt_version=1,
            config_matrix={"models": ["gpt-4o"], "temperatures": [0.7], "reasoning_efforts": []},
            test_cases=["case1"], include_eval=False, judge_model=None, concurrency=3, total_runs=1,
        )
        run = RunLog(
            agent_name="test", prompt_version=1, user_message="hi", output="hello",
            outcome=RunOutcome.success, bulk_run_id=bulk_id,
        )
        saved = await store.save_run(run)
        assert saved.bulk_run_id == bulk_id

    @pytest.mark.asyncio
    async def test_get_bulk_run_runs(self, store):
        bulk_id = await store.save_bulk_run(
            agent_name="test", prompt_version=1,
            config_matrix={"models": ["gpt-4o"], "temperatures": [0.7], "reasoning_efforts": []},
            test_cases=["case1"], include_eval=False, judge_model=None, concurrency=3, total_runs=2,
        )
        for i in range(2):
            run = RunLog(
                agent_name="test", prompt_version=1, user_message=f"msg{i}", output=f"out{i}",
                outcome=RunOutcome.success, bulk_run_id=bulk_id,
            )
            await store.save_run(run)
        runs = await store.get_bulk_run_runs(bulk_id)
        assert len(runs) == 2
