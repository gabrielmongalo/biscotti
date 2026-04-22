"""
biscotti
~~~~~~~~
Prompt playground for AI agents.
Edit, version, test, and ship prompts — without touching code.

Quick start::

    from biscotti import Biscotti, biscotti

    @biscotti(name="recipe agent")
    async def recipe_agent(user_message: str, system_prompt: str) -> str:
        \"\"\"You are a creative chef. Suggest recipes the user will love.
        Available ingredients: {{ingredients}}
        Occasion: {{occasion}}\"\"\"
        result = await agent.run(user_message, instructions=system_prompt)
        return result.output

    bi = Biscotti()
    bi.mount(app)  # mounts at /biscotti

Note: Define your LLM agent (e.g. PydanticAI Agent) at **module scope**,
not inside the decorated function, to avoid recreating it on every call.
"""

from .main import Biscotti
from .registry import biscotti, register_agent, list_agents, get_agent
from .models import (
    AgentMeta,
    PromptVersion,
    PromptStatus,
    TestCase,
    RunLog,
    RunRequest,
    RunResponse,
    EvalScore,
    JudgeCriteria,
    AgentSettings,
    EvalRun,
    Criterion,
    CriterionResult,
)

__all__ = [
    "Biscotti",
    "biscotti",
    "register_agent",
    "list_agents",
    "get_agent",
    "AgentMeta",
    "PromptVersion",
    "PromptStatus",
    "TestCase",
    "RunLog",
    "RunRequest",
    "RunResponse",
    "EvalScore",
    "JudgeCriteria",
    "AgentSettings",
    "EvalRun",
    "Criterion",
    "CriterionResult",
]

__version__ = "0.1.0"
