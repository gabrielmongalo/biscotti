"""
biscotti
~~~~~~~~
Prompt playground for AI agents.
Edit, version, test, and ship prompts — without touching code.

Quick start::

    from biscotti import biscotti, Biscotti
    from fastapi import FastAPI

    @biscotti(name="recipe agent")
    async def recipe_agent(user_message: str, system_prompt: str) -> str:
        \"\"\"You are a creative chef. Suggest recipes the user will love.
        Available ingredients: {{ingredients}}
        Occasion: {{occasion}}\"\"\"
        result = await agent.run(user_message, instructions=system_prompt)
        return result.output

    app = FastAPI()
    app.mount("/biscotti", Biscotti().app)
"""

from .main import Biscotti
from .registry import biscotti, biscotti_agent, register_agent, list_agents, get_agent
from .runner import register_callable
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
    "biscotti_agent",
    "register_agent",
    "register_callable",
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
