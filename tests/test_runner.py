import pytest
import pytest_asyncio
from biscotti.runner import estimate_cost


class TestEstimateCost:
    def test_exact_match(self):
        """Known model returns correct cost."""
        cost = estimate_cost("gpt-4o", 1000, 500)
        expected = (1000 * 2.50 + 500 * 10.00) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_prefix_match(self):
        """Dated model variant matches base model pricing."""
        cost = estimate_cost("gpt-4o-2024-08-06", 1000, 500)
        assert cost is not None
        assert cost > 0

    def test_unknown_model(self):
        """Unknown model returns None."""
        cost = estimate_cost("unknown-model-xyz", 1000, 500)
        assert cost is None

    def test_zero_tokens(self):
        """Zero tokens returns zero cost."""
        cost = estimate_cost("gpt-4o", 0, 0)
        assert cost == 0.0

    def test_anthropic_model(self):
        """Anthropic model pricing works."""
        cost = estimate_cost("claude-sonnet-4-6", 1000, 500)
        expected = (1000 * 3.00 + 500 * 15.00) / 1_000_000
        assert cost == pytest.approx(expected)


class TestExecuteRun:
    @pytest_asyncio.fixture
    async def runner_store(self, tmp_path):
        from biscotti.store import PromptStore
        store = PromptStore(str(tmp_path / "test.db"))
        await store.connect()
        yield store
        await store.close()

    @pytest.mark.asyncio
    async def test_callable_exception_returns_error(self, runner_store):
        """When callable raises, outcome should be 'error'."""
        from biscotti.runner import execute_run, register_callable
        from biscotti.registry import register_agent
        from biscotti.models import AgentMeta, RunRequest

        register_agent(AgentMeta(
            name="fail_agent",
            description="fails",
            default_system_prompt="You are a test agent.",
        ))

        async def failing_fn(msg, prompt):
            return 1 / 0

        register_callable("fail_agent", failing_fn)

        req = RunRequest(
            agent_name="fail_agent",
            user_message="hi",
        )
        resp = await execute_run(req, runner_store)
        assert resp.outcome == "error"
        assert "division by zero" in resp.error_message

    @pytest.mark.asyncio
    async def test_dict_return_extracts_fields(self, runner_store):
        """Callable returning dict should populate tokens and cost."""
        from biscotti.runner import execute_run, register_callable
        from biscotti.registry import register_agent
        from biscotti.models import AgentMeta, RunRequest

        register_agent(AgentMeta(
            name="rich_agent",
            description="rich",
            default_system_prompt="You are a test agent.",
        ))

        async def rich_fn(msg, prompt):
            return {
                "output": "hello world",
                "input_tokens": 100,
                "output_tokens": 50,
                "model": "gpt-4o",
            }

        register_callable("rich_agent", rich_fn)

        req = RunRequest(
            agent_name="rich_agent",
            user_message="hi",
        )
        resp = await execute_run(req, runner_store)
        assert resp.output == "hello world"
        assert resp.input_tokens == 100
        assert resp.output_tokens == 50
        assert resp.estimated_cost is not None
        assert resp.estimated_cost > 0
