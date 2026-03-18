# biscotti

The prompt eval studio for AI agents.

Iterate on system prompts with real test cases, track every version, and score quality with AI judges. Built for prompt engineers, not just developers.

---

## What it does

- **Browse & edit system prompts** in a clean browser UI — no terminal needed
- **Version control** every prompt change with diffs and notes
- **Test agents** with named test cases right from the browser
- **Run history** with latency, token counts, and version tracking
- **Promote to live** — agents pick up the active prompt at runtime without redeployment
- **Model agnostic** — works with PydanticAI, OpenAI SDK, Anthropic SDK, or any async callable
- **Zero config** — 3 lines to mount, one decorator to register

---

## Try it instantly

```bash
pip install biscotti
biscotti dev
```

Opens a demo playground at `http://localhost:8000/biscotti` with a sample agent.

---

## Quick start

```bash
pip install biscotti
```

### 1. Decorate your agents

```python
from biscotti import biscotti_agent

@biscotti_agent(
    name="recipe agent",
    description="Suggests recipes based on ingredients and occasion",
    default_system_prompt="""You are a creative chef.
Ingredients: {{ingredients}}
Occasion: {{occasion}}""",
)
async def recipe_agent(user_message: str, system_prompt: str) -> str:
    # your PydanticAI / OpenAI / Anthropic code here
    ...
```

The decorator:
- Registers the agent in biscotti
- Auto-detects `{{variable}}` placeholders
- Seeds the first version into the store on startup

### 2. Mount in FastAPI

```python
from fastapi import FastAPI
from biscotti import Biscotti

app = FastAPI()
docs = Biscotti(storage="sqlite:///biscotti.db")

# Bind the callable so biscotti can execute test runs
docs.bind("recipe agent", recipe_agent)

# Mount — that's it
app.mount("/biscotti", docs.app)
```

### 3. Open the UI

```
http://localhost:8000/biscotti
```

Share that URL with your prompt team. No login required for local/internal use.

---

## Connecting your agent callable

`docs.bind()` accepts any async function with this signature:

```python
async def my_callable(user_message: str, system_prompt: str) -> str:
    ...
```

### PydanticAI example

```python
from pydantic_ai import Agent

pydantic_agent = Agent(model="openai:gpt-4o")

async def run_agent(user_message: str, system_prompt: str) -> str:
    result = await pydantic_agent.run(
        user_message,
        system_prompt=system_prompt,
    )
    return result.output

docs.bind("recipe agent", run_agent)
```

### Anthropic SDK

```python
import anthropic
from biscotti import biscotti_agent

client = anthropic.AsyncAnthropic()

@biscotti_agent(name="chat agent", default_system_prompt="You are helpful.")
async def chat_agent(user_message: str, system_prompt: str) -> str:
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text
```

### OpenAI SDK example

```python
from openai import AsyncOpenAI

client = AsyncOpenAI()

async def run_agent(user_message: str, system_prompt: str) -> str:
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content
```

### Extended callable (model/temperature override)

Callables can accept an optional third `params` dict to receive UI-configured overrides:

```python
@biscotti_agent(name="my agent", default_system_prompt="...")
async def my_agent(user_message: str, system_prompt: str, params: dict) -> str:
    model = params.get("model", "claude-sonnet-4-6")
    temperature = params.get("temperature", 1.0)
    # Use model and temperature in your SDK call...
```

Available params: `model`, `temperature`, `reasoning_effort`, `variable_values`.

### Return a dict for richer telemetry

```python
async def run_agent(user_message: str, system_prompt: str) -> dict:
    # ... call your model ...
    return {
        "output": "the response text",
        "input_tokens": 150,
        "output_tokens": 80,
        "model": "gpt-4o",
    }
```

---

## Storage options

```python
# SQLite (default, great for local dev and small teams)
Biscotti(storage="sqlite:///biscotti.db")

# In-memory (useful for tests)
Biscotti(storage=":memory:")

# Absolute path
Biscotti(storage="sqlite:////var/data/biscotti.db")
```

---

## REST API

biscotti exposes a full REST API under `/biscotti/api/`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/agents` | List registered agents |
| GET | `/api/agents/{name}/versions` | List prompt versions |
| POST | `/api/agents/{name}/versions` | Create new version |
| POST | `/api/agents/{name}/versions/{id}/promote` | Promote to live |
| GET | `/api/agents/{name}/test-cases` | List test cases |
| POST | `/api/agents/{name}/test-cases` | Create test case |
| POST | `/api/run` | Execute a test run |
| GET | `/api/agents/{name}/runs` | Run history |
| GET | `/api/health` | Health check |

Full OpenAPI docs: `/biscotti/openapi`

---

## Eval system

biscotti includes an LLM-as-judge evaluation system:

1. **Generate criteria** — click "Generate from Prompt" to auto-create scoring rubrics from your system prompt
2. **Configure judge model** — pick any connected model (Anthropic, OpenAI)
3. **Run batch evals** — score all test cases against your criteria in one click
4. **Track history** — compare scores across prompt versions

### API keys

The eval system needs an API key for the judge model:

| Method | Scope | Example |
|--------|-------|---------|
| Environment variable | Process-wide | `export ANTHROPIC_API_KEY=sk-...` |
| UI settings panel | Session only | Evals tab → Provider Keys |

Resolution order: environment variable > in-memory UI key > None.

---

## How prompt versioning works

1. On first startup, biscotti seeds `v1` from `default_system_prompt` and promotes it to live
2. Prompt experts edit in the UI and save as `v2`, `v3`, etc. (always drafts)
3. Engineers or leads **promote** a draft to live — this archives the previous live version
4. Agents automatically use the live prompt version at runtime — no restart, no redeploy

---

## Development

```bash
git clone https://github.com/gabrielmongalo/biscotti
cd biscotti
pip install -e ".[dev]"
pytest
```

Run the example app:
```bash
uvicorn examples.demo_app:app --reload
# Open http://localhost:8000/biscotti
```

---

## Roadmap

- [x] Side-by-side version comparison
- [x] Export/import agent configurations (JSON)
- [ ] Streaming support for long-running models
- [ ] Simple auth (API key header)
- [ ] AI prompt coach (improvement suggestions from eval results)

---

## License

MIT
