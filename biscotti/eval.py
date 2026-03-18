"""
biscotti.eval
~~~~~~~~~~~~~
Internal PydanticAI agents for evaluation: judge generator, judge, and prompt coach.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from pydantic_ai import Agent

from .key_store import get_key
from .models import CoachResponse, EvalScore, JudgeCriteria, TestCase


# ---------------------------------------------------------------------------
# Judge Generator — creates eval criteria from a system prompt
# ---------------------------------------------------------------------------

_JUDGE_GEN_SYSTEM = """You are an expert at creating evaluation criteria for AI agents.

Given a system prompt and its variables, produce specific, measurable criteria
that an agent's output should be scored against.

Rules:
- Each criterion must be independently assessable from the output alone
- Criteria should cover: accuracy, completeness, format compliance, and instruction-following
- Be specific to THIS agent's purpose — no generic criteria
- Weight important criteria higher (default 1.0, max 3.0)
- Aim for 3-6 criteria (not too many, not too few)"""


def build_judge_generation_prompt(system_prompt: str, variables: list[str]) -> str:
    """Build the user message for the judge generator agent."""
    var_section = ""
    if variables:
        var_section = "\n\nTemplate variables used:\n" + "\n".join(f"- {{{{{v}}}}}" for v in variables)
    return f"System prompt to evaluate:\n\n{system_prompt}{var_section}"


def make_judge_generator(model: str = "anthropic:claude-sonnet-4-20250514") -> Agent:
    """Create a PydanticAI agent that generates judge criteria."""
    return Agent(
        model,
        result_type=JudgeCriteria,
        system_prompt=_JUDGE_GEN_SYSTEM,
    )


# ---------------------------------------------------------------------------
# Judge — scores agent output against criteria
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM_TEMPLATE = """You are an expert evaluator for AI agent outputs.

Score the agent output against these criteria:

{criteria}

For each criterion, determine if the output passes or fails it, and provide a brief note.
Then give an overall score from 1.0 to 5.0:
- 5.0: Exceptional — all criteria met, high quality
- 4.0: Good — most criteria met, minor issues
- 3.0: Acceptable — some criteria met, notable gaps
- 2.0: Poor — few criteria met, significant issues
- 1.0: Failing — criteria not met

Be rigorous but fair. Judge only what the criteria ask for."""


def build_judge_system_prompt(criteria_text: str) -> str:
    """Build the judge system prompt from criteria text."""
    return _JUDGE_SYSTEM_TEMPLATE.format(criteria=criteria_text)


def build_judge_user_prompt(
    user_message: str,
    system_prompt: str,
    agent_output: str,
) -> str:
    """Build the user message for the judge agent."""
    return f"""## Agent's System Prompt
{system_prompt}

## User Message
{user_message}

## Agent Output
{agent_output}

Evaluate the agent output against the criteria."""


def make_judge(model: str, criteria_text: str) -> Agent:
    """Create a PydanticAI agent that judges output against criteria."""
    return Agent(
        model,
        result_type=EvalScore,
        system_prompt=build_judge_system_prompt(criteria_text),
    )


# ---------------------------------------------------------------------------
# API key bridging
# ---------------------------------------------------------------------------

@contextmanager
def _ensure_api_keys():
    """Temporarily set API keys from key_store if not in env."""
    restored = {}
    for provider, env_var in [("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY")]:
        if not os.environ.get(env_var):
            key = get_key(provider)
            if key:
                os.environ[env_var] = key
                restored[env_var] = True
    try:
        yield
    finally:
        for env_var in restored:
            del os.environ[env_var]


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

async def generate_judge_criteria(
    system_prompt: str,
    variables: list[str],
    model: str = "anthropic:claude-sonnet-4-20250514",
) -> JudgeCriteria:
    """Generate judge criteria for a given system prompt."""
    with _ensure_api_keys():
        agent = make_judge_generator(model)
        user_msg = build_judge_generation_prompt(system_prompt, variables)
        result = await agent.run(user_msg)
        return result.data


async def judge_output(
    criteria_text: str,
    user_message: str,
    system_prompt: str,
    agent_output: str,
    model: str = "anthropic:claude-sonnet-4-20250514",
) -> EvalScore:
    """Score an agent output against criteria."""
    with _ensure_api_keys():
        agent = make_judge(model, criteria_text)
        user_msg = build_judge_user_prompt(user_message, system_prompt, agent_output)
        result = await agent.run(user_msg)
        return result.data


# ---------------------------------------------------------------------------
# Coach — analyzes eval results and suggests prompt improvements
# ---------------------------------------------------------------------------

_COACH_SYSTEM = """You are an expert prompt engineer. Your job is to review
an AI agent's system prompt and suggest specific, actionable improvements.

You may receive:
- The current system prompt (always provided)
- Evaluation criteria and results (if available from a prior eval run)

Your suggestions must be:
- Specific: include the exact text to add, replace, or remove
- Actionable: each suggestion should be independently implementable
- Prioritized: list the highest-impact change first
- Practical: focus on clarity, structure, constraint specificity, and output formatting

When eval results are provided, ground suggestions in the specific failures.
When reviewing a prompt without eval results, focus on best practices:
  - Clear role definition
  - Explicit output format instructions
  - Well-defined constraints and edge cases
  - Effective use of examples (few-shot)
  - Variable placeholder usage

Do not rewrite the prompt's core purpose or domain.
Always provide a complete revised_prompt with all suggestions applied."""


def build_coach_user_prompt(
    system_prompt: str,
    criteria_text: str,
    case_details: list[dict],
    test_cases: list[TestCase],
) -> str:
    """Build the user message for the coach agent."""
    parts = [
        "## Current System Prompt",
        system_prompt,
        "",
        "## Evaluation Criteria",
        criteria_text,
        "",
        "## Eval Results",
    ]
    for cd in case_details:
        tc_msg = next(
            (tc.user_message for tc in test_cases if tc.name == cd["test_case"]),
            "(unknown)",
        )
        parts.append(f"### Test Case: {cd['test_case']}")
        parts.append(f"User message: {tc_msg}")
        parts.append(f"Score: {cd.get('score', 'N/A')}")
        for cr in cd.get("criteria_results", []):
            status = "PASS" if cr["passed"] else "FAIL"
            parts.append(f"  - [{status}] {cr['criterion']}: {cr['note']}")
        parts.append(f"Judge reasoning: {cd.get('reasoning', '')}")
        parts.append("")

    parts.append("Analyze these results and suggest specific improvements to the system prompt.")
    return "\n".join(parts)


def make_coach(model: str) -> Agent:
    """Create a PydanticAI agent that coaches on prompt improvements."""
    return Agent(
        model,
        output_type=CoachResponse,
        system_prompt=_COACH_SYSTEM,
    )


async def generate_coaching(
    system_prompt: str,
    criteria_text: str,
    case_details: list[dict],
    test_cases: list[TestCase],
    model: str = "anthropic:claude-sonnet-4-6",
) -> CoachResponse:
    """Analyze eval results and suggest prompt improvements."""
    with _ensure_api_keys():
        agent = make_coach(model)
        user_msg = build_coach_user_prompt(system_prompt, criteria_text, case_details, test_cases)
        result = await agent.run(user_msg)
        return result.output


async def coach_prompt(
    system_prompt: str,
    model: str = "anthropic:claude-sonnet-4-6",
) -> CoachResponse:
    """Review a prompt directly and suggest improvements (no eval needed)."""
    with _ensure_api_keys():
        agent = make_coach(model)
        user_msg = f"## Current System Prompt\n{system_prompt}\n\nReview this prompt and suggest specific improvements."
        result = await agent.run(user_msg)
        return result.output
