"""
biscotti.store
~~~~~~~~~~~~~~~
Async SQLite-backed persistence for prompt versions, test cases, and run logs.
Uses aiosqlite directly — no ORM dependency.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite

from .models import (
    AgentSettings,
    EvalRun,
    PromptStatus,
    PromptVersion,
    PromptVersionCreate,
    RunLog,
    RunOutcome,
    TestCase,
    TestCaseCreate,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompt_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name      TEXT    NOT NULL,
    version         INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'draft',
    system_prompt   TEXT    NOT NULL,
    variables       TEXT    NOT NULL DEFAULT '[]',
    notes           TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL,
    created_by      TEXT    NOT NULL DEFAULT 'unknown',
    UNIQUE (agent_name, version)
);

CREATE TABLE IF NOT EXISTS test_cases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name      TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    user_message    TEXT    NOT NULL,
    variable_values TEXT    NOT NULL DEFAULT '{}',
    created_at      TEXT    NOT NULL,
    UNIQUE (agent_name, name)
);

CREATE TABLE IF NOT EXISTS run_logs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name              TEXT    NOT NULL,
    prompt_version          INTEGER NOT NULL,
    test_case_name          TEXT,
    user_message            TEXT    NOT NULL,
    variable_values         TEXT    NOT NULL DEFAULT '{}',
    system_prompt_rendered  TEXT    NOT NULL DEFAULT '',
    output                  TEXT    NOT NULL,
    outcome                 TEXT    NOT NULL DEFAULT 'success',
    error_message           TEXT,
    latency_ms              INTEGER NOT NULL DEFAULT 0,
    input_tokens            INTEGER NOT NULL DEFAULT 0,
    output_tokens           INTEGER NOT NULL DEFAULT 0,
    score                   REAL,
    score_reasoning         TEXT,
    model_used              TEXT    NOT NULL DEFAULT '',
    model_selected          TEXT    NOT NULL DEFAULT '',
    temperature             REAL,
    reasoning_effort        TEXT,
    estimated_cost          REAL,
    created_at              TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_settings (
    agent_name      TEXT PRIMARY KEY,
    judge_criteria  TEXT NOT NULL DEFAULT '',
    judge_model     TEXT NOT NULL DEFAULT '',
    coach_model     TEXT NOT NULL DEFAULT '',
    coach_enabled   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name      TEXT NOT NULL,
    prompt_version  INTEGER NOT NULL,
    judge_model     TEXT NOT NULL,
    test_case_count INTEGER NOT NULL,
    avg_score       REAL,
    min_score       REAL,
    max_score       REAL,
    pass_count      INTEGER NOT NULL DEFAULT 0,
    fail_count      INTEGER NOT NULL DEFAULT 0,
    case_details    TEXT,
    created_at      TEXT NOT NULL
);
"""


class PromptStore:
    """Async SQLite store for biscotti data."""

    def __init__(self, db_path: str | Path = "biscotti.db"):
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        # Migrate legacy 'live' status to 'current'
        await self._db.execute(
            "UPDATE prompt_versions SET status = 'current' WHERE status = 'live'"
        )
        # Migrate: add case_details column if missing (added in 0.1.1)
        try:
            await self._db.execute("SELECT case_details FROM eval_runs LIMIT 0")
        except Exception:
            await self._db.execute(
                "ALTER TABLE eval_runs ADD COLUMN case_details TEXT"
            )
        # Migrate: add coach_model column if missing
        try:
            await self._db.execute("SELECT coach_model FROM agent_settings LIMIT 0")
        except Exception:
            await self._db.execute(
                "ALTER TABLE agent_settings ADD COLUMN coach_model TEXT NOT NULL DEFAULT ''"
            )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store not connected — call await store.connect() first")
        return self._db

    @property
    def is_connected(self) -> bool:
        return self._db is not None

    async def ensure_connected(self) -> None:
        """Connect if not already connected. Safe to call multiple times."""
        if self._db is None:
            await self.connect()

    # ------------------------------------------------------------------
    # Prompt versions
    # ------------------------------------------------------------------

    async def next_version(self, agent_name: str) -> int:
        async with self.db.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_versions WHERE agent_name = ?",
            (agent_name,),
        ) as cur:
            row = await cur.fetchone()
            return row[0]

    async def create_prompt_version(self, data: PromptVersionCreate) -> PromptVersion:
        now = datetime.now(timezone.utc).isoformat()

        # Build a temporary PromptVersion to run validators (auto-detects variables)
        pv = PromptVersion(
            agent_name=data.agent_name,
            version=0,  # placeholder; actual version assigned atomically below
            status=PromptStatus.draft,
            system_prompt=data.system_prompt,
            variables=data.variables,
            notes=data.notes,
            created_at=datetime.now(timezone.utc),
            created_by=data.created_by,
        )

        # Atomic version assignment: SELECT MAX + 1 inside the INSERT to prevent races
        async with self.db.execute(
            """INSERT INTO prompt_versions
               (agent_name, version, status, system_prompt, variables, notes, created_at, created_by)
               VALUES (?, (SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_versions WHERE agent_name = ?),
                       ?, ?, ?, ?, ?, ?)""",
            (
                pv.agent_name,
                pv.agent_name,
                pv.status.value,
                pv.system_prompt,
                json.dumps(pv.variables),
                pv.notes,
                now,
                pv.created_by,
            ),
        ) as cur:
            pv.id = cur.lastrowid
        await self.db.commit()

        # Re-fetch to get the actual version number assigned by the subquery
        created = await self.get_prompt_version(pv.id)
        return created

    async def get_prompt_version(self, id: int) -> PromptVersion | None:
        async with self.db.execute(
            "SELECT * FROM prompt_versions WHERE id = ?", (id,)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_pv(row) if row else None

    async def get_current_version(self, agent_name: str) -> PromptVersion | None:
        async with self.db.execute(
            "SELECT * FROM prompt_versions WHERE agent_name = ? AND status = 'current' LIMIT 1",
            (agent_name,),
        ) as cur:
            row = await cur.fetchone()
        return _row_to_pv(row) if row else None

    async def list_versions(self, agent_name: str) -> list[PromptVersion]:
        async with self.db.execute(
            "SELECT * FROM prompt_versions WHERE agent_name = ? ORDER BY version DESC",
            (agent_name,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_pv(r) for r in rows]

    async def set_status(self, id: int, status: PromptStatus) -> PromptVersion | None:
        pv = await self.get_prompt_version(id)
        if pv is None:
            return None

        if status == PromptStatus.current:
            # Demote any existing current version for this agent
            await self.db.execute(
                "UPDATE prompt_versions SET status = 'archived' WHERE agent_name = ? AND status = 'current'",
                (pv.agent_name,),
            )

        await self.db.execute(
            "UPDATE prompt_versions SET status = ? WHERE id = ?",
            (status.value, id),
        )
        await self.db.commit()
        return await self.get_prompt_version(id)

    async def update_notes(self, id: int, notes: str) -> None:
        await self.db.execute(
            "UPDATE prompt_versions SET notes = ? WHERE id = ?", (notes, id)
        )
        await self.db.commit()

    async def delete_version(self, id: int) -> None:
        await self.db.execute("DELETE FROM prompt_versions WHERE id = ?", (id,))
        await self.db.commit()

    # ------------------------------------------------------------------
    # Test cases
    # ------------------------------------------------------------------

    async def upsert_test_case(self, data: TestCaseCreate) -> TestCase:
        now = datetime.now(timezone.utc).isoformat()
        async with self.db.execute(
            """INSERT INTO test_cases (agent_name, name, user_message, variable_values, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(agent_name, name) DO UPDATE SET
                   user_message = excluded.user_message,
                   variable_values = excluded.variable_values""",
            (
                data.agent_name,
                data.name,
                data.user_message,
                json.dumps(data.variable_values),
                now,
            ),
        ) as cur:
            tc_id = cur.lastrowid
        await self.db.commit()

        return TestCase(
            id=tc_id,
            agent_name=data.agent_name,
            name=data.name,
            user_message=data.user_message,
            variable_values=data.variable_values,
            created_at=datetime.fromisoformat(now),
        )

    async def count_test_cases(self, agent_name: str) -> int:
        async with self.db.execute(
            "SELECT COUNT(*) FROM test_cases WHERE agent_name = ?",
            (agent_name,),
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def list_test_cases(self, agent_name: str) -> list[TestCase]:
        async with self.db.execute(
            "SELECT * FROM test_cases WHERE agent_name = ? ORDER BY name",
            (agent_name,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_tc(r) for r in rows]

    async def delete_test_case(self, agent_name: str, name: str) -> None:
        await self.db.execute(
            "DELETE FROM test_cases WHERE agent_name = ? AND name = ?",
            (agent_name, name),
        )
        await self.db.commit()

    # ------------------------------------------------------------------
    # Run logs
    # ------------------------------------------------------------------

    async def save_run(self, run: RunLog) -> RunLog:
        now = datetime.now(timezone.utc).isoformat()
        async with self.db.execute(
            """INSERT INTO run_logs
               (agent_name, prompt_version, test_case_name, user_message,
                variable_values, system_prompt_rendered, output, outcome,
                error_message, latency_ms, input_tokens, output_tokens,
                score, score_reasoning, model_used, model_selected,
                temperature, reasoning_effort, estimated_cost, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run.agent_name,
                run.prompt_version,
                run.test_case_name,
                run.user_message,
                json.dumps(run.variable_values),
                run.system_prompt_rendered,
                run.output,
                run.outcome.value,
                run.error_message,
                run.latency_ms,
                run.input_tokens,
                run.output_tokens,
                run.score,
                run.score_reasoning,
                run.model_used,
                run.model_selected,
                run.temperature,
                run.reasoning_effort,
                run.estimated_cost,
                now,
            ),
        ) as cur:
            run.id = cur.lastrowid
        await self.db.commit()
        return run

    async def distinct_models(self, agent_name: str) -> list[str]:
        """Return distinct model names used in past runs for an agent."""
        async with self.db.execute(
            """SELECT DISTINCT model_used FROM run_logs
               WHERE agent_name = ? AND model_used != '' AND model_used != 'unknown'
               ORDER BY model_used""",
            (agent_name,),
        ) as cur:
            rows = await cur.fetchall()
        return [row[0] for row in rows]

    async def list_runs(
        self,
        agent_name: str,
        limit: int = 50,
        version: int | None = None,
    ) -> list[RunLog]:
        if version is not None:
            async with self.db.execute(
                """SELECT * FROM run_logs WHERE agent_name = ? AND prompt_version = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (agent_name, version, limit),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self.db.execute(
                "SELECT * FROM run_logs WHERE agent_name = ? ORDER BY created_at DESC LIMIT ?",
                (agent_name, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_run(r) for r in rows]

    # ------------------------------------------------------------------
    # Agent settings
    # ------------------------------------------------------------------

    async def get_agent_settings(self, agent_name: str) -> AgentSettings:
        async with self.db.execute(
            "SELECT * FROM agent_settings WHERE agent_name = ?", (agent_name,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            d = dict(row)
            d["coach_enabled"] = bool(d["coach_enabled"])
            return AgentSettings(**d)
        return AgentSettings(agent_name=agent_name)

    async def update_agent_settings(self, agent_name: str, **kwargs) -> None:
        current = await self.get_agent_settings(agent_name)
        merged = {
            "agent_name": agent_name,
            "judge_criteria": kwargs.get("judge_criteria", current.judge_criteria),
            "judge_model": kwargs.get("judge_model", current.judge_model),
            "coach_model": kwargs.get("coach_model", current.coach_model),
            "coach_enabled": 1 if kwargs.get("coach_enabled", current.coach_enabled) else 0,
        }
        await self.db.execute(
            """INSERT INTO agent_settings (agent_name, judge_criteria, judge_model, coach_model, coach_enabled)
               VALUES (:agent_name, :judge_criteria, :judge_model, :coach_model, :coach_enabled)
               ON CONFLICT(agent_name) DO UPDATE SET
                   judge_criteria = excluded.judge_criteria,
                   judge_model = excluded.judge_model,
                   coach_model = excluded.coach_model,
                   coach_enabled = excluded.coach_enabled""",
            merged,
        )
        await self.db.commit()

    # ------------------------------------------------------------------
    # Eval runs
    # ------------------------------------------------------------------

    async def save_eval_run(self, er: EvalRun) -> EvalRun:
        now = datetime.now(timezone.utc).isoformat()
        details_json = json.dumps(er.case_details) if er.case_details else None
        async with self.db.execute(
            """INSERT INTO eval_runs
               (agent_name, prompt_version, judge_model, test_case_count,
                avg_score, min_score, max_score, pass_count, fail_count,
                case_details, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (er.agent_name, er.prompt_version, er.judge_model,
             er.test_case_count, er.avg_score, er.min_score, er.max_score,
             er.pass_count, er.fail_count, details_json, now),
        ) as cur:
            er.id = cur.lastrowid
        await self.db.commit()
        return er

    async def list_eval_runs(self, agent_name: str, limit: int = 50) -> list[EvalRun]:
        async with self.db.execute(
            "SELECT * FROM eval_runs WHERE agent_name = ? ORDER BY created_at DESC LIMIT ?",
            (agent_name, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_eval_run(r) for r in rows]

    async def get_eval_run(self, agent_name: str, eval_id: int) -> dict | None:
        """Fetch a single eval run by ID and agent_name (O(1) instead of linear scan)."""
        async with self.db.execute(
            "SELECT * FROM eval_runs WHERE id = ? AND agent_name = ?",
            (eval_id, agent_name),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["created_at"] = datetime.fromisoformat(d["created_at"])
        if d.get("case_details") and isinstance(d["case_details"], str):
            d["case_details"] = json.loads(d["case_details"])
        else:
            d["case_details"] = []
        return d

    async def update_run_score(self, run_id: int, score: float, reasoning: str) -> None:
        await self.db.execute(
            "UPDATE run_logs SET score = ?, score_reasoning = ? WHERE id = ?",
            (score, reasoning, run_id),
        )
        await self.db.commit()


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------

def _row_to_pv(row: aiosqlite.Row) -> PromptVersion:
    d = dict(row)
    d["variables"] = json.loads(d["variables"])
    d["created_at"] = datetime.fromisoformat(d["created_at"])
    return PromptVersion(**d)


def _row_to_tc(row: aiosqlite.Row) -> TestCase:
    d = dict(row)
    d["variable_values"] = json.loads(d["variable_values"])
    d["created_at"] = datetime.fromisoformat(d["created_at"])
    return TestCase(**d)


def _row_to_run(row: aiosqlite.Row) -> RunLog:
    d = dict(row)
    d["variable_values"] = json.loads(d["variable_values"])
    d["created_at"] = datetime.fromisoformat(d["created_at"])
    return RunLog(**d)


def _row_to_eval_run(row: aiosqlite.Row) -> EvalRun:
    d = dict(row)
    d["created_at"] = datetime.fromisoformat(d["created_at"])
    if d.get("case_details") and isinstance(d["case_details"], str):
        d["case_details"] = json.loads(d["case_details"])
    return EvalRun(**d)
