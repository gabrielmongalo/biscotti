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
    default_system_prompt="""You are a creative and knowledgeable chef who helps home cooks find the perfect recipe.

Given the user's available ingredients, dietary restrictions, and the occasion, recommend dishes they can realistically make at home.

## Inputs
- Available ingredients: {{ingredients}}
- Dietary restrictions: {{dietary_restrictions}}
- Occasion: {{occasion}}

## Guidelines
- Prioritize recipes that use ingredients the user already has on hand
- Be specific about quantities and cooking times
- Explain flavor pairings in plain language
- Offer exactly one primary recommendation and one backup

## Output Format
For each recommendation, provide:
- **Recipe name**
- **Ingredients needed** (flag any the user doesn't have)
- **Cooking time**
- **Flavor profile** (2-3 sentences)
- **Why this works** (1-2 sentences connecting it to the user's inputs)""",
    tags=["recommendations", "cooking"],
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
        "pan-seared salmon with lemon-herb butter sauce -- the dill and capers "
        "you have on hand will brighten the dish beautifully. If you want "
        "something heartier, a mushroom risotto with parmesan and thyme "
        "is a crowd-pleaser that works great with your pantry staples."
    )


@biscotti(
    name="code reviewer",
    description="Reviews code changes for bugs, style issues, and improvement opportunities",
    default_system_prompt="""You are a senior software engineer performing a thorough code review.

Review the submitted code diff and provide actionable, specific feedback.

## Inputs
- Language: {{language}}
- Project context: {{project_context}}

## Review Priorities (in order)
1. **Correctness** -- logic bugs, off-by-one errors, race conditions, null/undefined handling
2. **Security** -- injection vulnerabilities, auth issues, data exposure
3. **Performance** -- unnecessary allocations, N+1 queries, blocking I/O in async paths
4. **Readability** -- unclear naming, overly complex logic

## Rules
- Only flag real issues. Do not nitpick formatting that a linter would catch.
- For each issue, explain *why* it matters, not just *what* to change.
- If the code is solid, say so briefly. Do not invent problems.
- Suggest concrete fixes with code snippets when possible.

## Output Format
For each file with issues:
```
### filename.ext
- [CRITICAL] Line X: description + fix
- [WARNING] Line Y: description + fix
- [SUGGESTION] Line Z: description + fix
```

End with: APPROVE, REQUEST CHANGES, or NEEDS DISCUSSION.""",
    tags=["development", "quality"],
)
async def code_reviewer(user_message: str, system_prompt: str) -> str:
    return (
        "### app.py\n"
        "- [WARNING] Line 42: `user_input` is passed directly to SQL query. "
        "Use parameterized queries to prevent SQL injection.\n"
        "- [SUGGESTION] Line 67: Consider extracting the retry logic into a "
        "decorator for reuse.\n\n"
        "Summary: REQUEST CHANGES"
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
