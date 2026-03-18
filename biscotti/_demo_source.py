"""
biscotti._demo_source
~~~~~~~~~~~~~~~~~~~~~
Bundled demo app used by `biscotti dev`.
Two stub agents, fully functional biscotti UI.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from biscotti import Biscotti, biscotti


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
    return (
        "[demo] For a dinner party with the ingredients you have, I'd recommend "
        "pan-seared salmon with lemon-herb butter — the dill and capers will "
        "brighten the dish beautifully. Backup: mushroom risotto with parmesan "
        "and thyme. (Connect a real model to get live responses.)"
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
        "[demo] Monday: Breakfast — Greek yogurt parfait (5 min). "
        "Lunch — Mediterranean quinoa bowl (20 min). "
        "Dinner — One-pot chicken curry with rice (35 min). "
        "(Connect a real model to get live responses.)"
    )


bi = Biscotti(storage=":memory:")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="biscotti demo", lifespan=lifespan)
app.mount("/biscotti", bi.app)

@app.get("/")
async def root():
    return {"message": "biscotti demo", "ui": "/biscotti"}
