"""
biscotti.router
~~~~~~~~~~~~~~~~
FastAPI router exposing the biscotti REST API.
Mounted by Biscotti.router inside the user's FastAPI app.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .models import (
    PromptStatus,
    PromptVersion,
    PromptVersionCreate,
    PromptVersionUpdate,
    RunLog,
    RunRequest,
    RunResponse,
    TestCase,
    TestCaseCreate,
)
from .registry import list_agents, get_agent
from .runner import execute_run, PRICING, get_callable, detect_model_from_callable
from .store import PromptStore

_UI_DIR = Path(__file__).parent / "ui" / "static"


def build_router(store: PromptStore) -> APIRouter:
    """Return a configured APIRouter wired to the given store."""

    router = APIRouter()

    # --- Dependency ---
    def get_store() -> PromptStore:
        return store

    # ==================================================================
    # Static UI
    # ==================================================================

    @router.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def ui_root() -> FileResponse:
        return FileResponse(_UI_DIR / "index.html")

    @router.get("/app.js", include_in_schema=False)
    async def ui_js() -> FileResponse:
        return FileResponse(_UI_DIR / "app.js", media_type="application/javascript")

    @router.get("/style.css", include_in_schema=False)
    async def ui_css() -> FileResponse:
        return FileResponse(_UI_DIR / "style.css", media_type="text/css")

    # ==================================================================
    # Agents
    # ==================================================================

    @router.get("/api/agents", tags=["agents"])
    async def list_agents_endpoint() -> list[dict]:
        agents = list_agents()
        result = []
        for agent in agents:
            live = await store.get_current_version(agent.name)
            versions = await store.list_versions(agent.name)
            runs = await store.list_runs(agent.name, limit=5)
            result.append({
                "name": agent.name,
                "description": agent.description,
                "variables": agent.variables,
                "tags": agent.tags,
                "current_version": live.version if live else None,
                "version_count": len(versions),
                "recent_run_count": len(runs),
            })
        return result

    @router.get("/api/agents/{agent_name}", tags=["agents"])
    async def get_agent_endpoint(agent_name: str) -> dict:
        meta = get_agent(agent_name)
        if meta is None:
            raise HTTPException(404, f"Agent '{agent_name}' not registered")
        live = await store.get_current_version(agent_name)
        return {
            "name": meta.name,
            "description": meta.description,
            "variables": meta.variables,
            "tags": meta.tags,
            "default_system_prompt": meta.default_system_prompt,
            "current_version": live.version if live else None,
            "current_prompt": live.system_prompt if live else meta.default_system_prompt,
        }

    # ==================================================================
    # Prompt versions
    # ==================================================================

    @router.get("/api/agents/{agent_name}/versions", tags=["prompts"])
    async def list_versions(agent_name: str) -> list[PromptVersion]:
        _require_agent(agent_name)
        return await store.list_versions(agent_name)

    @router.post("/api/agents/{agent_name}/versions", tags=["prompts"])
    async def create_version(
        agent_name: str, body: PromptVersionCreate
    ) -> PromptVersion:
        _require_agent(agent_name)
        body.agent_name = agent_name
        return await store.create_prompt_version(body)

    @router.get("/api/agents/{agent_name}/versions/{version_id}", tags=["prompts"])
    async def get_version(agent_name: str, version_id: int) -> PromptVersion:
        _require_agent(agent_name)
        pv = await store.get_prompt_version(version_id)
        if pv is None or pv.agent_name != agent_name:
            raise HTTPException(404, "Version not found")
        return pv

    @router.patch("/api/agents/{agent_name}/versions/{version_id}", tags=["prompts"])
    async def update_version(
        agent_name: str, version_id: int, body: PromptVersionUpdate
    ) -> PromptVersion:
        _require_agent(agent_name)
        pv = await store.get_prompt_version(version_id)
        if pv is None or pv.agent_name != agent_name:
            raise HTTPException(404, "Version not found")
        if body.status is not None:
            pv = await store.set_status(version_id, body.status)
        if body.notes is not None:
            await store.update_notes(version_id, body.notes)
            pv = await store.get_prompt_version(version_id)
        return pv

    @router.delete(
        "/api/agents/{agent_name}/versions/{version_id}",
        tags=["prompts"],
    )
    async def delete_version(agent_name: str, version_id: int) -> dict:
        _require_agent(agent_name)
        pv = await store.get_prompt_version(version_id)
        if pv is None or pv.agent_name != agent_name:
            raise HTTPException(404, "Version not found")
        if pv.status == PromptStatus.current:
            raise HTTPException(400, "Cannot delete the current version")
        await store.delete_version(version_id)
        return {"deleted": True}

    @router.post(
        "/api/agents/{agent_name}/versions/{version_id}/promote",
        tags=["prompts"],
    )
    async def promote_version(agent_name: str, version_id: int) -> PromptVersion:
        _require_agent(agent_name)
        pv = await store.set_status(version_id, PromptStatus.current)
        if pv is None:
            raise HTTPException(404, "Version not found")
        return pv

    # ==================================================================
    # Test cases
    # ==================================================================

    @router.get("/api/agents/{agent_name}/test-cases", tags=["test-cases"])
    async def list_test_cases(agent_name: str) -> list[TestCase]:
        _require_agent(agent_name)
        return await store.list_test_cases(agent_name)

    @router.post("/api/agents/{agent_name}/test-cases", tags=["test-cases"])
    async def create_test_case(agent_name: str, body: TestCaseCreate) -> TestCase:
        _require_agent(agent_name)
        body.agent_name = agent_name
        return await store.upsert_test_case(body)

    @router.delete(
        "/api/agents/{agent_name}/test-cases/{name}", tags=["test-cases"]
    )
    async def delete_test_case(agent_name: str, name: str) -> dict:
        _require_agent(agent_name)
        await store.delete_test_case(agent_name, name)
        return {"deleted": True}

    # ==================================================================
    # Runs
    # ==================================================================

    @router.post("/api/run", tags=["runs"])
    async def run_agent(body: RunRequest) -> RunResponse:
        _require_agent(body.agent_name)
        return await execute_run(body, store)

    @router.get("/api/agents/{agent_name}/runs", tags=["runs"])
    async def list_runs(
        agent_name: str, limit: int = 50, version: int | None = None
    ) -> list[RunLog]:
        _require_agent(agent_name)
        return await store.list_runs(agent_name, limit=limit, version=version)

    # ==================================================================
    # Models
    # ==================================================================

    @router.get("/api/agents/{agent_name}/models", tags=["models"])
    async def list_models(agent_name: str) -> dict:
        """Return available models for an agent.

        Combines: declared models from @biscotti_agent, pricing table
        models, and historically used models from run_logs.
        """
        _require_agent(agent_name)
        meta = get_agent(agent_name)

        declared = meta.models if meta else []
        pricing_models = list(PRICING.keys())
        historical = await store.distinct_models(agent_name)

        # Try to auto-detect model from callable source
        detected = None
        callable_fn = get_callable(agent_name)
        if callable_fn:
            detected = detect_model_from_callable(callable_fn)

        # Merge: detected first, then declared, then historical, then pricing defaults
        seen: set[str] = set()
        merged: list[str] = []
        for m in ([detected] if detected else []) + declared + historical + pricing_models:
            if m not in seen:
                seen.add(m)
                merged.append(m)

        return {
            "detected": detected,
            "historical": historical,
            "all": merged,
        }

    # ==================================================================
    # Agent Settings (eval config)
    # ==================================================================

    @router.get("/api/agents/{agent_name}/settings", tags=["eval"])
    async def get_settings(agent_name: str) -> dict:
        _require_agent(agent_name)
        s = await store.get_agent_settings(agent_name)
        return s.model_dump()

    @router.put("/api/agents/{agent_name}/settings", tags=["eval"])
    async def update_settings(agent_name: str, body: dict) -> dict:
        _require_agent(agent_name)
        await store.update_agent_settings(agent_name, **body)
        s = await store.get_agent_settings(agent_name)
        return s.model_dump()

    # ==================================================================
    # Eval: Generate Judge Criteria
    # ==================================================================

    @router.post("/api/agents/{agent_name}/generate-judge", tags=["eval"])
    async def generate_judge(agent_name: str) -> dict:
        _require_agent(agent_name)
        meta = get_agent(agent_name)
        settings = await store.get_agent_settings(agent_name)

        pv = await store.get_current_version(agent_name)
        prompt = pv.system_prompt if pv else meta.default_system_prompt
        variables = pv.variables if pv else meta.variables

        from .eval import generate_judge_criteria
        criteria = await generate_judge_criteria(prompt, variables, model=settings.judge_model)

        criteria_text = "\n".join(
            f"- {c.name} (weight {c.weight}): {c.description}"
            for c in criteria.criteria
        )
        await store.update_agent_settings(agent_name, judge_criteria=criteria_text)

        return {"criteria": criteria_text, "raw": criteria.model_dump()}

    # ==================================================================
    # Eval: Run Eval
    # ==================================================================

    @router.post("/api/agents/{agent_name}/eval", tags=["eval"])
    async def run_eval(agent_name: str, body: dict | None = None) -> dict:
        """Run all test cases against a version and judge each output."""
        _require_agent(agent_name)
        settings = await store.get_agent_settings(agent_name)
        if not settings.judge_criteria:
            raise HTTPException(400, "No judge criteria configured. Generate or set criteria first.")

        version_id = body.get("prompt_version_id") if body else None
        test_cases = await store.list_test_cases(agent_name)
        if not test_cases:
            raise HTTPException(400, "No test cases defined for this agent.")

        from .models import EvalRun
        from .eval import judge_output

        scores: list[float | None] = []
        for tc in test_cases:
            req = RunRequest(
                agent_name=agent_name,
                prompt_version_id=version_id,
                user_message=tc.user_message,
                variable_values=tc.variable_values,
                test_case_name=tc.name,
            )
            run_resp = await execute_run(req, store)

            if run_resp.outcome == "error":
                scores.append(None)
                continue

            pv = (await store.get_prompt_version(version_id)) if version_id else (await store.get_current_version(agent_name))
            eval_result = await judge_output(
                criteria_text=settings.judge_criteria,
                user_message=tc.user_message,
                system_prompt=pv.system_prompt if pv else "",
                agent_output=run_resp.output,
                model=settings.judge_model,
            )

            await store.update_run_score(run_resp.run_id, eval_result.score, eval_result.reasoning)
            scores.append(eval_result.score)

        valid = [s for s in scores if s is not None]
        avg = sum(valid) / len(valid) if valid else None
        pass_count = sum(1 for s in valid if s >= 3.5)

        pv = (await store.get_prompt_version(version_id)) if version_id else (await store.get_current_version(agent_name))

        eval_run = await store.save_eval_run(EvalRun(
            agent_name=agent_name,
            prompt_version=pv.version if pv else 0,
            judge_model=settings.judge_model,
            test_case_count=len(test_cases),
            avg_score=avg,
            min_score=min(valid) if valid else None,
            max_score=max(valid) if valid else None,
            pass_count=pass_count,
            fail_count=len(valid) - pass_count,
        ))

        return eval_run.model_dump(mode="json")

    @router.get("/api/agents/{agent_name}/evals", tags=["eval"])
    async def list_evals(agent_name: str) -> list[dict]:
        _require_agent(agent_name)
        runs = await store.list_eval_runs(agent_name)
        return [r.model_dump(mode="json") for r in runs]

    # ==================================================================
    # Settings: API key management
    # ==================================================================

    @router.get("/api/settings/status", tags=["settings"])
    async def api_key_status() -> dict:
        from .key_store import available_providers
        return available_providers()

    @router.post("/api/settings/api-key", tags=["settings"])
    async def set_api_key(body: dict) -> dict:
        from .key_store import set_key, available_providers
        provider = body.get("provider", "")
        key = body.get("key", "")
        if provider not in ("anthropic", "openai"):
            raise HTTPException(400, "Provider must be 'anthropic' or 'openai'")
        if not key:
            raise HTTPException(400, "Key cannot be empty")
        set_key(provider, key)
        return {"status": "ok", "providers": available_providers()}

    # ==================================================================
    # Health
    # ==================================================================

    @router.get("/api/health", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok", "agents": len(list_agents())}

    return router


def _require_agent(name: str) -> None:
    if get_agent(name) is None:
        raise HTTPException(404, f"Agent '{name}' not registered")
