"""
biscotti._demo_source
~~~~~~~~~~~~~~~~~~~~~
Bundled demo app used by `biscotti dev`.
Three example agents with realistic prompts, test cases, and prompt versions.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from biscotti import Biscotti, biscotti


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
- Prioritize recipes that use ingredients the user already has on hand, but substitute freely if needed to meet dietary restrictions
- If critical ingredients are missing, suggest minimal, accessible substitutes and note them clearly
- If dietary restrictions conflict with available ingredients, prioritize dietary restrictions without exception
- Be specific about quantities and cooking times
- Explain flavor pairings in plain language
- Offer exactly one primary recommendation and one backup recommendation

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
    return (
        "[demo] For a dinner party with the ingredients you have, I'd recommend "
        "pan-seared salmon with lemon-herb butter -- the dill and capers will "
        "brighten the dish beautifully. Backup: mushroom risotto with parmesan "
        "and thyme. (Connect a real model to get live responses.)"
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
2. **Security** -- injection vulnerabilities, auth issues, data exposure, unsafe deserialization
3. **Performance** -- unnecessary allocations, N+1 queries, missing indexes, blocking I/O in async paths
4. **Readability** -- unclear naming, overly complex logic, missing or misleading comments
5. **Style** -- consistency with project conventions, idiomatic patterns

## Rules
- Only flag real issues. Do not nitpick formatting that a linter would catch.
- For each issue, explain *why* it matters, not just *what* to change.
- If the code is solid, say so briefly. Do not invent problems.
- Suggest concrete fixes with code snippets when possible.
- Group feedback by file, then by severity (critical > warning > suggestion).

## Output Format
For each file with issues:
```
### filename.ext
- [CRITICAL] Line X: description + fix
- [WARNING] Line Y: description + fix
- [SUGGESTION] Line Z: description + fix
```

End with a one-line summary verdict: APPROVE, REQUEST CHANGES, or NEEDS DISCUSSION.""",
    tags=["development", "quality"],
)
async def code_reviewer(user_message: str, system_prompt: str) -> str:
    return (
        "[demo] ### app.py\n"
        "- [WARNING] Line 42: `user_input` is passed directly to SQL query. "
        "Use parameterized queries to prevent SQL injection.\n"
        "- [SUGGESTION] Line 67: Consider extracting the retry logic into a "
        "decorator for reuse.\n\n"
        "Summary: REQUEST CHANGES -- the SQL injection risk should be fixed "
        "before merging. (Connect a real model to get live responses.)"
    )


@biscotti(
    name="support agent",
    description="Handles customer support inquiries with empathy and accuracy",
    default_system_prompt="""You are a customer support specialist for {{company_name}}, a {{product_type}}.

Your goal is to resolve customer issues quickly and empathetically while staying within policy.

## Inputs
- Customer tier: {{customer_tier}}
- Product: {{product_type}}

## Tone
- Warm but professional. Never condescending. No corporate jargon.
- Acknowledge the customer's frustration before jumping to solutions.
- Use the customer's name if provided.

## Resolution Process
1. Identify the core issue (ignore noise, focus on what the customer actually needs)
2. Check if it falls within standard policy
3. Provide a clear resolution or escalation path
4. Confirm the customer is satisfied before closing

## Boundaries
- Never share internal system details, pricing logic, or other customers' information
- Never promise features, timelines, or refunds you cannot guarantee
- If unsure, say so honestly and offer to escalate to a specialist
- For billing disputes over $100, always escalate to billing team

## Output Format
- Start with acknowledgment (1-2 sentences)
- Provide resolution steps (numbered list)
- End with a follow-up offer""",
    tags=["support", "customer-facing"],
)
async def support_agent(user_message: str, system_prompt: str) -> str:
    return (
        "[demo] I completely understand your frustration with the billing issue, "
        "and I want to get this sorted out for you right away.\n\n"
        "1. I've reviewed your account and can see the duplicate charge.\n"
        "2. I've initiated a refund that should appear in 3-5 business days.\n"
        "3. I've added a note to prevent this from happening again.\n\n"
        "Is there anything else I can help you with? "
        "(Connect a real model to get live responses.)"
    )


# ---------------------------------------------------------------------------
# Demo seeding: extra prompt versions + test cases + judge criteria
# ---------------------------------------------------------------------------

_DEMO_SEED = {
    "recipe agent": {
        "versions": [
            # v2: tightened guidelines
            {
                "prompt": """You are a creative and knowledgeable chef.

Given the user's inputs, recommend one primary recipe and one backup.

## Inputs
- Available ingredients: {{ingredients}}
- Dietary restrictions: {{dietary_restrictions}}
- Occasion: {{occasion}}

## Guidelines
- Use ingredients the user has. Flag any they need to buy.
- Respect dietary restrictions absolutely -- no exceptions.
- Be specific: exact quantities, cooking times, temperatures.
- Explain why flavors work together in plain language.

## Format
**[Recipe Name]**
Ingredients: [list, flag missing items with *]
Time: [prep + cook]
Flavor: [2-3 sentences]
Why this works: [1-2 sentences]""",
                "notes": "Simplified format, stricter dietary rules",
            },
        ],
        "test_cases": [
            {
                "name": "weeknight dinner",
                "user_message": "I have chicken thighs, rice, garlic, soy sauce, and ginger. No allergies. It's a Tuesday night and I want something quick.",
                "variables": {"ingredients": "chicken thighs, rice, garlic, soy sauce, ginger", "dietary_restrictions": "none", "occasion": "weeknight dinner"},
            },
            {
                "name": "vegan date night",
                "user_message": "Planning a romantic dinner. I have mushrooms, pasta, olive oil, pine nuts, basil, and nutritional yeast. My partner is vegan.",
                "variables": {"ingredients": "mushrooms, pasta, olive oil, pine nuts, basil, nutritional yeast", "dietary_restrictions": "vegan", "occasion": "date night"},
            },
            {
                "name": "kid birthday party",
                "user_message": "My 8-year-old's birthday party is Saturday. I have flour, eggs, butter, chocolate chips, vanilla, and sprinkles. One kid has a nut allergy.",
                "variables": {"ingredients": "flour, eggs, butter, chocolate chips, vanilla, sprinkles", "dietary_restrictions": "nut-free", "occasion": "kid's birthday party"},
            },
        ],
        "judge_criteria": """- Ingredient Alignment (weight 2.5): Recipe primarily uses the listed available ingredients. Missing items are flagged clearly.
- Dietary Compliance (weight 3.0): Strictly respects stated dietary restrictions with zero violations.
- Occasion Fit (weight 2.0): The recipe style and complexity match the stated occasion.
- Specificity (weight 2.0): Includes exact quantities, temperatures, and cooking times -- not vague instructions.
- Format Compliance (weight 1.5): Follows the requested output structure with all required sections.
- Flavor Explanation (weight 1.5): Explains why flavors work together in accessible, plain language.""",
        "eval_run": {
            "judge_model": "anthropic:claude-sonnet-4-6",
            "avg_score": 3.8,
            "min_score": 3.0,
            "max_score": 4.5,
            "pass_count": 2,
            "fail_count": 1,
            "case_details": [
                {
                    "test_case": "weeknight dinner",
                    "score": 4.5,
                    "reasoning": "The response correctly used all available ingredients (chicken thighs, rice, garlic, soy sauce, ginger) and provided a quick stir-fry that fits a Tuesday night perfectly. Quantities and times were specific. Flavor pairing explanation was clear and helpful.",
                    "criteria_results": [
                        {"criterion": "Ingredient Alignment", "passed": True, "note": "All five listed ingredients used as the base of the recipe"},
                        {"criterion": "Dietary Compliance", "passed": True, "note": "No restrictions stated, none violated"},
                        {"criterion": "Occasion Fit", "passed": True, "note": "25-minute recipe is appropriate for a weeknight"},
                        {"criterion": "Specificity", "passed": True, "note": "Included exact measurements (2 tbsp soy sauce, 1 inch ginger) and timing (7 min sear, 15 min rice)"},
                        {"criterion": "Format Compliance", "passed": True, "note": "All required sections present with primary and backup recommendations"},
                        {"criterion": "Flavor Explanation", "passed": True, "note": "Explained how ginger and garlic build aromatic base while soy adds umami depth"},
                    ],
                },
                {
                    "test_case": "vegan date night",
                    "score": 3.0,
                    "reasoning": "The recipe respected vegan requirements and used available ingredients well, but lacked specificity in cooking times and the flavor explanation was generic. The occasion fit was good -- elevated enough for a date night.",
                    "criteria_results": [
                        {"criterion": "Ingredient Alignment", "passed": True, "note": "Used mushrooms, pasta, pine nuts, basil, and nutritional yeast"},
                        {"criterion": "Dietary Compliance", "passed": True, "note": "Fully vegan, no animal products suggested"},
                        {"criterion": "Occasion Fit", "passed": True, "note": "Mushroom pasta with pine nuts feels appropriately elevated for date night"},
                        {"criterion": "Specificity", "passed": False, "note": "Said 'cook until tender' without specifying time or temperature"},
                        {"criterion": "Format Compliance", "passed": False, "note": "Missing the 'Why this works' section in backup recommendation"},
                        {"criterion": "Flavor Explanation", "passed": False, "note": "Said flavors 'complement each other well' without explaining why"},
                    ],
                },
                {
                    "test_case": "kid birthday party",
                    "score": 3.8,
                    "reasoning": "Good recipe choice for a kid's party with nut-free compliance. Specific quantities provided. Format was complete. Slightly missed on occasion fit -- could have been more fun/kid-focused.",
                    "criteria_results": [
                        {"criterion": "Ingredient Alignment", "passed": True, "note": "Used flour, eggs, butter, chocolate chips, vanilla, and sprinkles"},
                        {"criterion": "Dietary Compliance", "passed": True, "note": "Completely nut-free, no cross-contamination risks mentioned"},
                        {"criterion": "Occasion Fit", "passed": False, "note": "Classic chocolate chip cookies are safe but not particularly exciting for a birthday party"},
                        {"criterion": "Specificity", "passed": True, "note": "350F for 10-12 minutes, specific cup measurements for all ingredients"},
                        {"criterion": "Format Compliance", "passed": True, "note": "All sections present including backup recommendation (brownies)"},
                        {"criterion": "Flavor Explanation", "passed": True, "note": "Explained how brown butter adds toffee notes that pair with chocolate"},
                    ],
                },
            ],
        },
    },
    "code reviewer": {
        "versions": [
            {
                "prompt": """You are a senior engineer doing code review. Be direct and specific.

## Inputs
- Language: {{language}}
- Project context: {{project_context}}

## What to check
1. Bugs and logic errors
2. Security vulnerabilities
3. Performance problems
4. Readability issues

## Rules
- Only flag real issues. If the code is fine, say so.
- Provide concrete fixes with code snippets.
- Group by file, then severity.
- End with: APPROVE, REQUEST CHANGES, or NEEDS DISCUSSION.""",
                "notes": "Condensed version, removed style category",
            },
        ],
        "test_cases": [
            {
                "name": "SQL injection risk",
                "user_message": "```python\ndef get_user(db, username):\n    query = f\"SELECT * FROM users WHERE name = '{username}'\"\n    return db.execute(query).fetchone()\n```",
                "variables": {"language": "Python", "project_context": "REST API with SQLite backend"},
            },
            {
                "name": "race condition in cache",
                "user_message": "```python\nclass Cache:\n    def __init__(self):\n        self._data = {}\n    \n    async def get_or_set(self, key, factory):\n        if key not in self._data:\n            self._data[key] = await factory()\n        return self._data[key]\n```",
                "variables": {"language": "Python", "project_context": "Async web server handling concurrent requests"},
            },
            {
                "name": "clean code review",
                "user_message": "```python\nfrom dataclasses import dataclass\nfrom typing import Optional\n\n@dataclass(frozen=True)\nclass Config:\n    host: str\n    port: int = 8080\n    debug: bool = False\n    max_retries: int = 3\n\n    def base_url(self) -> str:\n        scheme = \"http\" if self.debug else \"https\"\n        return f\"{scheme}://{self.host}:{self.port}\"\n```",
                "variables": {"language": "Python", "project_context": "Internal configuration module"},
            },
        ],
        "judge_criteria": """- Bug Detection (weight 3.0): Correctly identifies real bugs and logic errors in the code. Does not miss critical issues.
- False Positive Rate (weight 2.5): Does not flag non-issues or invent problems that don't exist.
- Fix Quality (weight 2.0): Suggested fixes are correct, concrete, and include code snippets.
- Severity Accuracy (weight 1.5): Issues are classified at the right severity level (critical vs warning vs suggestion).
- Explanation Quality (weight 1.5): Explains why each issue matters, not just what to change.
- Format Compliance (weight 1.0): Follows the requested output structure and ends with a clear verdict.""",
    },
    "support agent": {
        "versions": [
            {
                "prompt": """You are a customer support agent for {{company_name}} ({{product_type}}).

Resolve issues quickly and kindly. Customer tier: {{customer_tier}}.

## Approach
1. Acknowledge the issue with empathy
2. Identify what the customer actually needs
3. Provide a clear resolution or escalation path
4. Confirm satisfaction

## Rules
- Never share internal details or other customers' info
- Never promise things you can't guarantee
- Billing disputes over $100: escalate to billing team
- Be warm and direct. No jargon.""",
                "notes": "Shorter version, core rules only",
            },
        ],
        "test_cases": [
            {
                "name": "billing dispute",
                "user_message": "I was charged twice for my subscription this month. I want a refund immediately. This is the third time this has happened.",
                "variables": {"company_name": "Acme SaaS", "product_type": "project management tool", "customer_tier": "Pro"},
            },
            {
                "name": "feature confusion",
                "user_message": "How do I export my data to CSV? I've been clicking around for 20 minutes and can't find it anywhere. This is really frustrating.",
                "variables": {"company_name": "Acme SaaS", "product_type": "project management tool", "customer_tier": "Free"},
            },
            {
                "name": "angry escalation",
                "user_message": "I've been waiting 3 days for a response. Your product deleted my entire project and nobody seems to care. I need to talk to a manager RIGHT NOW.",
                "variables": {"company_name": "Acme SaaS", "product_type": "project management tool", "customer_tier": "Enterprise"},
            },
        ],
        "judge_criteria": """- Empathy (weight 2.5): Acknowledges the customer's frustration before jumping to solutions. Feels genuine, not scripted.
- Accuracy (weight 3.0): Provides correct information and does not make promises outside of policy boundaries.
- Resolution Quality (weight 2.5): Offers a clear, actionable resolution path. Does not leave the customer hanging.
- Tone (weight 2.0): Professional but warm. No condescension, jargon, or robotic language.
- Policy Compliance (weight 2.0): Stays within stated boundaries. Escalates when required.
- Format (weight 1.0): Follows the acknowledgment > steps > follow-up structure.""",
    },
}


async def _seed_demo_data(bi: Biscotti) -> None:
    """Seed extra versions, test cases, judge criteria, and a sample eval run."""
    from .models import EvalRun, PromptVersionCreate, PromptStatus, TestCaseCreate

    store = bi._store
    for agent_name, data in _DEMO_SEED.items():
        # Seed extra prompt versions
        for v in data.get("versions", []):
            versions = await store.list_versions(agent_name)
            if len(versions) > 1:
                break
            pv = await store.create_prompt_version(
                PromptVersionCreate(
                    agent_name=agent_name,
                    system_prompt=v["prompt"],
                    notes=v["notes"],
                )
            )

        # Seed test cases
        existing_tcs = await store.list_test_cases(agent_name)
        if not existing_tcs:
            for tc in data.get("test_cases", []):
                await store.upsert_test_case(
                    TestCaseCreate(
                        agent_name=agent_name,
                        name=tc["name"],
                        user_message=tc["user_message"],
                        variable_values=tc.get("variables", {}),
                    )
                )

        # Seed judge criteria
        settings = await store.get_agent_settings(agent_name)
        if not settings.judge_criteria and data.get("judge_criteria"):
            await store.update_agent_settings(
                agent_name,
                judge_criteria=data["judge_criteria"],
            )

        # Seed a sample eval run
        if data.get("eval_run"):
            existing_evals = await store.list_eval_runs(agent_name)
            if not existing_evals:
                er = data["eval_run"]
                await store.save_eval_run(EvalRun(
                    agent_name=agent_name,
                    prompt_version=1,
                    judge_model=er["judge_model"],
                    test_case_count=len(er["case_details"]),
                    avg_score=er["avg_score"],
                    min_score=er["min_score"],
                    max_score=er["max_score"],
                    pass_count=er["pass_count"],
                    fail_count=er["fail_count"],
                    case_details=er["case_details"],
                ))


bi = Biscotti(storage=":memory:")

_demo_seeded = False

app = FastAPI(title="biscotti demo")
app.mount("/biscotti", bi.app)


@app.middleware("http")
async def seed_demo_middleware(request, call_next):
    global _demo_seeded
    response = await call_next(request)
    if not _demo_seeded and bi._store.is_connected:
        _demo_seeded = True
        await _seed_demo_data(bi)
    return response


@app.get("/")
async def root():
    return {"message": "biscotti demo", "ui": "/biscotti"}
