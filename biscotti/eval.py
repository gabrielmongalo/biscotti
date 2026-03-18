"""
biscotti.eval
~~~~~~~~~~~~~
Internal PydanticAI agents for evaluation: judge generator, judge, and prompt coach.
"""
from __future__ import annotations

from pydantic_ai import Agent

from .models import EvalScore, JudgeCriteria


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
# High-level helpers
# ---------------------------------------------------------------------------

async def generate_judge_criteria(
    system_prompt: str,
    variables: list[str],
    model: str = "anthropic:claude-sonnet-4-20250514",
) -> JudgeCriteria:
    """Generate judge criteria for a given system prompt."""
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
    agent = make_judge(model, criteria_text)
    user_msg = build_judge_user_prompt(user_message, system_prompt, agent_output)
    result = await agent.run(user_msg)
    return result.data
