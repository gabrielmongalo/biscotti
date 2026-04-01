import pytest
from biscotti.models import (
    BulkRunStatus,
    BulkRunRequest,
    BulkRunSummary,
    BulkRunDetail,
    RunLog,
)


class TestBulkRunModels:
    def test_bulk_run_status_enum(self):
        assert BulkRunStatus.running == "running"
        assert BulkRunStatus.completed == "completed"
        assert BulkRunStatus.cancelled == "cancelled"
        assert BulkRunStatus.error == "error"

    def test_bulk_run_request_defaults(self):
        req = BulkRunRequest(
            agent_name="test",
            models=["gpt-4o"],
            temperatures=[0.7],
            test_case_names=["case1"],
        )
        assert req.concurrency == 3
        assert req.include_eval is False
        assert req.reasoning_efforts == []
        assert req.prompt_version_id is None
        assert req.judge_model is None

    def test_bulk_run_request_full(self):
        req = BulkRunRequest(
            agent_name="test",
            prompt_version_id=5,
            models=["gpt-4o", "claude-sonnet-4-6"],
            temperatures=[0.0, 0.7, 1.0],
            reasoning_efforts=["low", "high"],
            test_case_names=["case1", "case2"],
            include_eval=True,
            judge_model="gpt-4o",
            concurrency=5,
        )
        assert len(req.models) == 2
        assert req.concurrency == 5

    def test_bulk_run_summary(self):
        summary = BulkRunSummary(
            id=1,
            agent_name="test",
            config_matrix={"models": ["gpt-4o"], "temperatures": [0.7], "reasoning_efforts": []},
            test_cases=["case1"],
            include_eval=False,
            judge_model=None,
            concurrency=3,
            total_runs=3,
            completed_runs=0,
            status=BulkRunStatus.running,
        )
        assert summary.status == "running"

    def test_bulk_run_detail_extends_summary(self):
        detail = BulkRunDetail(
            id=1,
            agent_name="test",
            config_matrix={"models": ["gpt-4o"], "temperatures": [0.7], "reasoning_efforts": []},
            test_cases=["case1"],
            include_eval=False,
            judge_model=None,
            concurrency=3,
            total_runs=1,
            completed_runs=1,
            status=BulkRunStatus.completed,
            runs=[],
        )
        assert detail.runs == []

    def test_run_log_has_bulk_run_id(self):
        log = RunLog(
            agent_name="test",
            prompt_version=1,
            user_message="hi",
            output="hello",
            bulk_run_id=42,
        )
        assert log.bulk_run_id == 42

    def test_run_log_bulk_run_id_defaults_none(self):
        log = RunLog(
            agent_name="test",
            prompt_version=1,
            user_message="hi",
            output="hello",
        )
        assert log.bulk_run_id is None
