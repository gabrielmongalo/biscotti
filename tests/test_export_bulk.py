import csv
import io
import pytest
from biscotti.models import RunLog, RunOutcome


def _make_run(**overrides) -> RunLog:
    defaults = dict(
        agent_name="test", prompt_version=1, user_message="hi", output="hello",
        outcome=RunOutcome.success, test_case_name="case1", model_used="gpt-4o",
        temperature=0.7, reasoning_effort=None, input_tokens=100, output_tokens=50,
        latency_ms=500, estimated_cost=0.001, score=None,
    )
    defaults.update(overrides)
    return RunLog(**defaults)


class TestGenerateExport:
    def test_csv_output(self):
        from biscotti.export import generate_export
        runs = [_make_run()]
        data = generate_export(runs, format="csv", include_score=False)
        text = data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        assert len(rows) == 2
        header = rows[0]
        assert "Test Case" in header
        assert "Model" in header
        assert "Score" not in header

    def test_csv_with_score(self):
        from biscotti.export import generate_export
        runs = [_make_run(score=4.5)]
        data = generate_export(runs, format="csv", include_score=True)
        text = data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        header = rows[0]
        assert "Score" in header

    def test_tsv_output(self):
        from biscotti.export import generate_export
        runs = [_make_run()]
        data = generate_export(runs, format="tsv", include_score=False)
        text = data.decode("utf-8")
        lines = text.strip().split("\n")
        assert len(lines) == 2
        assert "\t" in lines[0]

    def test_xlsx_output(self):
        from biscotti.export import generate_export
        runs = [_make_run()]
        data = generate_export(runs, format="xlsx", include_score=False)
        assert data[:2] == b"PK"

    def test_multiple_runs(self):
        from biscotti.export import generate_export
        runs = [
            _make_run(test_case_name="case1", model_used="gpt-4o", temperature=0.0),
            _make_run(test_case_name="case1", model_used="gpt-4o", temperature=1.0),
            _make_run(test_case_name="case2", model_used="claude-sonnet-4-6", temperature=0.7),
        ]
        data = generate_export(runs, format="csv", include_score=False)
        text = data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        assert len(rows) == 4
