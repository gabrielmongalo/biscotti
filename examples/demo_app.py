"""
examples/demo_app.py
~~~~~~~~~~~~~~~~~~~~
Full working example showing biscotti integrated with a FastAPI app.

Run with:
    pip install biscotti fastapi uvicorn
    uvicorn examples.demo_app:app --reload

Then open: http://localhost:8000/biscotti
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from biscotti import Biscotti, biscotti


# ---------------------------------------------------------------------------
# 1. Decorate your agents with @biscotti
# ---------------------------------------------------------------------------

@biscotti(
    name="recipe agent",
    description="Suggests recipes based on ingredients, dietary needs, and occasion",
    default_system_prompt="""You are a creative and knowledgeable chef.

Your goal is to suggest recipes the user will love, considering:
- Available ingredients: {{ingredients}}
- Dietary restrictions: {{dietary_restrictions}}
- Occasion: {{occasion}}

Guidelines:
- Prioritize recipes that use ingredients already on hand
- Be specific about quantities and cooking times
- Explain flavor pairings in plain language
- Offer one primary recommendation and one backup""",
    tags=["recommendations", "core"],
)
async def recipe_agent(user_message: str, system_prompt: str) -> str:
    """Call your actual PydanticAI / OpenAI / Anthropic agent here."""
    # In a real app, you'd do something like:
    #
    #   result = await pydantic_ai_agent.run(user_message, system_prompt=system_prompt)
    #   return result.data
    #
    # For this example we return a stub response.
    return (
        "Based on your ingredients and tonight's dinner party, I'd recommend a "
        "pan-seared salmon with lemon-herb butter sauce — the dill and capers "
        "you have on hand will brighten the dish beautifully. If you want "
        "something heartier, a mushroom risotto with parmesan and thyme "
        "is a crowd-pleaser that works great with your pantry staples."
    )


@biscotti(
    name="meal plan agent",
    description="Creates weekly meal plans based on preferences and goals",
    default_system_prompt="""You are a meal planning expert.

Given the user's preferences:
- Cuisine style: {{cuisine_style}}
- Servings per meal: {{servings}}
- Budget: {{budget}}

Create a balanced weekly meal plan with breakfast, lunch, and dinner.
For each meal, include a brief ingredient list and estimated prep time.""",
    tags=["planning"],
)
async def meal_plan_agent(user_message: str, system_prompt: str) -> str:
    return (
        "Here's your Monday lineup: Breakfast — Greek yogurt parfait with "
        "granola and berries (5 min). Lunch — Mediterranean quinoa bowl with "
        "roasted chickpeas and tahini dressing (20 min). Dinner — One-pot "
        "chicken and vegetable curry with jasmine rice (35 min)."
    )


# ---------------------------------------------------------------------------
# 2. Mount in FastAPI
# ---------------------------------------------------------------------------

bi = Biscotti(storage="sqlite:///biscotti_example.db")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # biscotti manages its own DB lifecycle inside bi.app
    yield

app = FastAPI(title="My App", lifespan=lifespan)

app.mount("/biscotti", bi.app)


# ---------------------------------------------------------------------------
# Your regular app routes continue here unchanged
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "message": "My App",
        "biscotti": "Visit /biscotti to manage and test your agents",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
