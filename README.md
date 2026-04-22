# biscotti

Prompt playground for AI agents. Edit system prompts, version them, run test cases, and score outputs with a judge LLM — all from a browser UI that mounts inside your existing FastAPI app.

---

## Install

```bash
pip install biscotti
```

Requires Python 3.10+.

---

## Try it

```bash
biscotti dev
```

Starts a local server at `http://localhost:8000/biscotti` with three pre-loaded demo agents, sample test cases, and a seeded eval run. No API key needed to explore the UI.

```bash
uvx biscotti dev          # without installing
biscotti dev --port 9000  # custom port
```

---

## Quick start

### 1. Decorate your agent

```python
from biscotti import Biscotti, biscotti

@biscotti(
    name="recipe agent",
    description="Suggests recipes based on ingredients and occasion",
    default_system_prompt="""You are a creative chef.
Ingredients: {{ingredients}}
Occasion: {{occasion}}""",
)
async def recipe_agent(user_message: str, system_prompt: str) -> str:
    # your model call here — see SDK examples below
    ...
```

The decorator registers the agent, detects `{{variable}}` placeholders, and seeds the first prompt version into the store on startup.

### 2. Mount in FastAPI

```python
from fastapi import FastAPI
from biscotti import Biscotti

app = FastAPI()
bi = Biscotti()
app.mount("/biscotti", bi.app)
```

### 3. Open the UI

```
http://localhost:8000/biscotti
```

---

## SDK examples

The `@biscotti` decorator wraps any async function with this signature:

```python
async def my_agent(user_message: str, system_prompt: str) -> str: ...
```

### PydanticAI

Two patterns, pick the one that matches how your agent is built.

**Pattern A — lightweight decorator** for any async callable:

```python
from pydantic_ai import Agent
from biscotti import biscotti

agent = Agent(model="anthropic:claude-sonnet-4-6")

@biscotti(name="recipe agent", default_system_prompt="You are a creative chef.")
async def recipe_agent(user_message: str, system_prompt: str) -> str:
    result = await agent.run(user_message, system_prompt=system_prompt)
    return result.output
```

**Pattern B — register a PydanticAI `Agent` directly** when your agent has
`@agent.system_prompt` functions, an `output_type`, tools, or uses Python
f-string builders to construct user prompts from DB data:

```python
from pydantic_ai import Agent
from biscotti.pydanticai import register

wine_body_agent = Agent(output_type=GlanceBody)

@wine_body_agent.system_prompt
def _wine_system_prompt() -> str:
    return WINE_INSTRUCTIONS

def _build_wine_prompt(wine_info: dict) -> str:
    name     = wine_info.get("wine", "Unknown")
    producer = wine_info.get("producer", "Unknown")
    return f"Wine: {name}\nProducer: {producer}"

# register() pulls out the system prompt, model, output schema, and tools
wine_body = register(wine_body_agent, name="wine body")

# Bind the builder — biscotti introspects its AST, extracts dict keys +
# defaults, and seeds a {{var}} user-message template for the UI
wine_body.user_prompt(_build_wine_prompt)
```

The prompt engineer opens the UI and sees `{{wine}}` and `{{producer}}`
as fillable variables, auto-extracted from the builder's `.get()` calls.
Prod keeps calling `_build_wine_prompt(wine_info)` exactly as before — the
decorator only seeds a starting template; it doesn't change runtime behavior.

For builders shared across multiple agents or builders with non-dict args
(e.g. `include_vintage_context=True`), stack decorators and pass `extras=`:

```python
wine_body.user_prompt(_build_wine_prompt)
wine_full_card.user_prompt(extras={"include_vintage_context": True})(_build_wine_prompt)
```

### Anthropic SDK

```python
import anthropic
from biscotti import biscotti

client = anthropic.AsyncAnthropic()

@biscotti(name="chat agent", default_system_prompt="You are helpful.")
async def chat_agent(user_message: str, system_prompt: str) -> str:
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text
```

### OpenAI SDK

```python
from openai import AsyncOpenAI
from biscotti import biscotti

client = AsyncOpenAI()

@biscotti(name="gpt agent", default_system_prompt="You are helpful.")
async def gpt_agent(user_message: str, system_prompt: str) -> str:
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content
```

### Return richer telemetry

Return a dict instead of a string to surface token counts and model name in the run history:

```python
@biscotti(name="my agent", default_system_prompt="...")
async def my_agent(user_message: str, system_prompt: str) -> dict:
    # ... call your model ...
    return {
        "output": "the response text",
        "input_tokens": 150,
        "output_tokens": 80,
        "model": "claude-sonnet-4-6",
    }
```

### Accept model/temperature overrides from the UI

Add an optional `params` argument to receive values set in the playground:

```python
@biscotti(name="my agent", default_system_prompt="...")
async def my_agent(user_message: str, system_prompt: str, params: dict) -> str:
    model = params.get("model", "claude-sonnet-4-6")
    temperature = params.get("temperature", 1.0)
    ...
```

Available params: `model`, `temperature`, `reasoning_effort`, `variable_values`.

---

## Features

**Playground** — Run any test case against any prompt version. Latency, token counts, and model are logged per run.

**Versions** — Every save creates a new draft version. Promote a version to live; agents pick it up immediately without a restart.

**Evals** — Score outputs with an LLM judge. Define weighted criteria, run them across all test cases in one click, and track scores across prompt versions.

**Coach** — After an eval run, get improvement suggestions from a coach LLM based on which criteria failed and why.

**Bulk Run** — Run a matrix of test cases × models × temperatures (× reasoning efforts) with streaming progress, optional auto-eval scoring, and CSV / TSV / XLSX export. Every run is saved to history with per-row delete.

**Variables** — System prompts support `{{variable}}` placeholders. Test cases carry variable values that are interpolated at run time.

**User-message templates** — Separate `{{var}}` templates for the user message, versioned the same way as system prompts. Register them three ways: `default_message="..."` on the agent decorator, `default_message=` kwarg on `biscotti.pydanticai.register()`, or `@handle.user_prompt(builder_fn)` to auto-extract from a Python dict-based builder.

---

## Eval system

1. Write test cases with realistic inputs in the UI.
2. Write judge criteria, or click "Generate from Prompt" to auto-generate a rubric from your system prompt.
3. Select a judge model and run. Each test case is scored per criterion with a pass/fail and a reasoning note.
4. Compare aggregate scores across prompt versions to decide what to promote.

The judge model needs an API key. You can set it via environment variable or in the API Keys panel (session-only, never persisted to disk):

```bash
export ANTHROPIC_API_KEY=sk-...
export OPENAI_API_KEY=sk-...
```

Resolution order: environment variable > in-memory UI key.

### Azure Foundry

To use Azure-hosted models as your judge or coach, open the API Keys panel and select "Azure Foundry" from the provider dropdown. Enter your endpoint URL, API key, API version, and one or more deployment names. Connected deployments appear in model dropdowns as `azure:deployment-name`.

---

## Storage

```python
# SQLite at a custom path
Biscotti(storage="sqlite:///biscotti.db")

# In-memory (useful in tests)
Biscotti(storage=":memory:")
```

Default when no argument is passed: `biscotti.db` in the working directory. Accepts bare paths (`"./data/biscotti.db"`) or `sqlite:///` prefixed strings interchangeably.

---

## REST API

All endpoints are available under the mount path (e.g. `/biscotti/api/`):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/agents` | List registered agents |
| GET | `/api/agents/{name}` | Get agent details |
| GET | `/api/agents/{name}/versions` | List prompt versions |
| POST | `/api/agents/{name}/versions` | Create a draft version |
| PATCH | `/api/agents/{name}/versions/{id}` | Update version notes |
| DELETE | `/api/agents/{name}/versions/{id}` | Delete a version |
| POST | `/api/agents/{name}/versions/{id}/promote` | Promote to current |
| GET | `/api/agents/{name}/user-message-versions` | List user-message template versions |
| POST | `/api/agents/{name}/user-message-versions` | Create a draft user-message version |
| PATCH | `/api/agents/{name}/user-message-versions/{id}` | Update status or notes |
| DELETE | `/api/agents/{name}/user-message-versions/{id}` | Delete a non-current user-message version |
| POST | `/api/agents/{name}/user-message-versions/{id}/promote` | Promote user-message version to current |
| GET | `/api/agents/{name}/test-cases` | List test cases |
| POST | `/api/agents/{name}/test-cases` | Create / update a test case |
| DELETE | `/api/agents/{name}/test-cases/{name}` | Delete a test case |
| POST | `/api/run` | Execute a run |
| GET | `/api/agents/{name}/runs` | Run history |
| GET | `/api/agents/{name}/settings` | Get eval settings |
| PUT | `/api/agents/{name}/settings` | Update eval settings |
| POST | `/api/agents/{name}/generate-judge` | Auto-generate judge criteria |
| POST | `/api/agents/{name}/eval` | Run batch eval |
| GET | `/api/agents/{name}/evals` | List eval runs |
| GET | `/api/agents/{name}/evals/{id}` | Get eval run details |
| POST | `/api/agents/{name}/coach` | Get coaching suggestions |
| POST | `/api/agents/{name}/bulk-run` | Start a new bulk run |
| GET | `/api/agents/{name}/bulk-runs` | List bulk runs |
| GET | `/api/agents/{name}/bulk-runs/{id}` | Get bulk run detail (with run logs) |
| DELETE | `/api/agents/{name}/bulk-runs/{id}` | Delete bulk run and its run logs |
| GET | `/api/agents/{name}/bulk-runs/{id}/stream` | Stream progress (SSE) |
| GET | `/api/agents/{name}/bulk-runs/{id}/export` | Export results (csv/tsv/xlsx) |
| POST | `/api/agents/{name}/bulk-runs/{id}/cancel` | Cancel a running bulk run |
| GET | `/api/agents/{name}/export` | Export agent config as JSON |
| POST | `/api/agents/{name}/import` | Import agent config |
| GET | `/api/settings/status` | Provider auth status |
| POST | `/api/settings/api-key` | Set API key (session-only) |
| DELETE | `/api/settings/api-key/{provider}` | Remove API key |
| GET | `/api/settings/azure` | Get Azure Foundry config |
| POST | `/api/settings/azure` | Set Azure Foundry config |
| DELETE | `/api/settings/azure` | Remove Azure Foundry config |
| GET | `/api/health` | Health check |

Interactive docs: `/biscotti/openapi`

---

## How versioning works

Two parallel version tracks per agent — system prompts and user-message templates — both follow the same rules.

1. On first startup, biscotti seeds `v1` from `default_system_prompt` (system prompt track) and from `default_message` / `@handle.user_prompt`-decorated builders (user-message track). Each is promoted to current.
2. Edits in the UI create new draft versions (`v2`, `v3`, ...).
3. Promoting a draft sets it as current and archives the previous version.
4. Your agent callable always receives the current version's rendered prompt at runtime — no restart or redeploy needed. If `RunRequest.user_message` is empty, the runner falls back to the current user-message template for that agent.

---

## Development

```bash
git clone https://github.com/gabrielmongalo/biscotti
cd biscotti
pip install -e ".[dev]"
pytest
```

---

## LLM Context

A [`llms.txt`](llms.txt) file is included at the repo root for LLM-assisted development. It covers the callable signature, variable syntax, integration patterns, and eval system in a compact format suitable for context windows.

---

## License

MIT
