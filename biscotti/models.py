"""
biscotti.models
~~~~~~~~~~~~~~~~
Pydantic models shared across the library.
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PromptStatus(str, Enum):
    draft = "draft"
    current = "current"
    archived = "archived"


class RunOutcome(str, Enum):
    success = "success"
    error = "error"


# ---------------------------------------------------------------------------
# Agent registration (in-memory, populated by @biscotti_agent decorator)
# ---------------------------------------------------------------------------

class AgentMeta(BaseModel):
    """Metadata registered for one agent via @biscotti_agent."""
    name: str
    description: str = ""
    variables: list[str] = Field(default_factory=list)
    default_system_prompt: str = ""
    tags: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt versioning
# ---------------------------------------------------------------------------

class PromptVersion(BaseModel):
    id: int | None = None
    agent_name: str
    version: int
    status: PromptStatus = PromptStatus.draft
    system_prompt: str
    variables: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = "unknown"

    @model_validator(mode="after")
    def _detect_variables(self) -> "PromptVersion":
        """Auto-detect {{var}} style variables from the prompt text."""
        found = re.findall(r"\{\{(\w+)\}\}", self.system_prompt)
        # Merge explicitly declared + detected, preserving order
        merged = list(dict.fromkeys(self.variables + found))
        self.variables = merged
        return self


class PromptVersionCreate(BaseModel):
    agent_name: str
    system_prompt: str
    variables: list[str] = Field(default_factory=list)
    notes: str = ""
    created_by: str = "unknown"


class PromptVersionUpdate(BaseModel):
    status: PromptStatus | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestCase(BaseModel):
    id: int | None = None
    agent_name: str
    name: str
    user_message: str
    variable_values: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TestCaseCreate(BaseModel):
    agent_name: str
    name: str
    user_message: str
    variable_values: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------

class RunLog(BaseModel):
    id: int | None = None
    agent_name: str
    prompt_version: int
    test_case_name: str | None = None
    user_message: str
    variable_values: dict[str, Any] = Field(default_factory=dict)
    system_prompt_rendered: str = ""
    output: str
    outcome: RunOutcome = RunOutcome.success
    error_message: str | None = None
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    score: float | None = None
    score_reasoning: str | None = None
    model_used: str = ""
    model_selected: str = ""
    temperature: float | None = None
    reasoning_effort: str | None = None
    estimated_cost: float | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RunRequest(BaseModel):
    agent_name: str
    prompt_version_id: int | None = None   # None → use current version
    user_message: str
    variable_values: dict[str, str] = Field(default_factory=dict)
    test_case_name: str | None = None
    run_eval: bool = True
    model: str | None = None               # e.g. "gpt-4o", "claude-sonnet-4-20250514"
    temperature: float | None = None       # 0.0–2.0
    reasoning_effort: str | None = None    # "low", "medium", "high"


class RunResponse(BaseModel):
    run_id: int
    output: str
    outcome: RunOutcome
    error_message: str | None = None
    latency_ms: int
    input_tokens: int
    output_tokens: int
    score: float | None = None
    score_reasoning: str | None = None
    model_used: str
    prompt_version: int
    estimated_cost: float | None = None


# ---------------------------------------------------------------------------
# Eval system
# ---------------------------------------------------------------------------

class Criterion(BaseModel):
    name: str
    description: str
    weight: float = 1.0


class JudgeCriteria(BaseModel):
    criteria: list[Criterion]


class CriterionResult(BaseModel):
    criterion: str
    passed: bool
    note: str


class EvalScore(BaseModel):
    score: float          # 1.0–5.0
    reasoning: str
    criteria_results: list[CriterionResult]


class AgentSettings(BaseModel):
    agent_name: str
    judge_criteria: str = ""
    judge_model: str = "anthropic:claude-sonnet-4-20250514"
    coach_enabled: bool = True


class EvalRun(BaseModel):
    id: int | None = None
    agent_name: str
    prompt_version: int
    judge_model: str
    test_case_count: int
    avg_score: float | None = None
    min_score: float | None = None
    max_score: float | None = None
    pass_count: int = 0
    fail_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
