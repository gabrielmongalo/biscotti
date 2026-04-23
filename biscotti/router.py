"""
biscotti.router
~~~~~~~~~~~~~~~~
FastAPI router exposing the biscotti REST API.
Mounted by Biscotti.router inside the user's FastAPI app.
"""
from __future__ import annotations

from pathlib import Path

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .models import (
    BulkRunRequest,
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


# Provider inference for bare model names (no colon prefix). Order matters —
# longest prefix wins. Used by list_models() to filter out models whose
# backing provider isn't connected.
# Keep in sync with the client classifier in biscotti/ui/static/app.js
# (_BARE_PREFIX_PROVIDER / _BARE_EXACT_PROVIDER). If the two diverge, the
# server may filter out a model as unreachable while the UI still groups
# it under a known provider — or vice versa.
_BARE_PREFIX_PROVIDER: list[tuple[str, str]] = [
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("claude-", "anthropic"),
    ("gemini-", "gemini"),
    ("mixtral-", "mistral"),
    ("mistral-", "mistral"),
    ("command-", "cohere"),
    ("deepseek-", "deepseek"),
    ("grok-", "xai"),
]

_BARE_MODEL_PROVIDER: dict[str, str] = {
    "chatgpt-4o-latest": "openai",
    "deepseek-chat": "deepseek",
    "deepseek-reasoner": "deepseek",
}


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
        return FileResponse(_UI_DIR / "app.html")

    @router.get("/home", include_in_schema=False)
    async def ui_home():
        from starlette.responses import RedirectResponse
        return RedirectResponse(url=".")

    @router.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    async def ui_docs() -> FileResponse:
        return FileResponse(_UI_DIR / "docs.html")

    @router.get("/static/{filename:path}", include_in_schema=False)
    async def ui_static(filename: str) -> FileResponse:
        return FileResponse(_UI_DIR / filename)

    @router.get("/app.js", include_in_schema=False)
    async def ui_js() -> FileResponse:
        return FileResponse(_UI_DIR / "app.js", media_type="application/javascript")

    @router.get("/components.js", include_in_schema=False)
    async def ui_components() -> FileResponse:
        return FileResponse(_UI_DIR / "components.js", media_type="application/javascript")

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
            test_case_count = await store.count_test_cases(agent.name)
            result.append({
                "name": agent.name,
                "description": agent.description,
                "variables": agent.variables,
                "tags": agent.tags,
                "current_version": live.version if live else None,
                "version_count": len(versions),
                "test_case_count": test_case_count,
                "recent_run_count": len(runs),
                "tool_count": len(getattr(agent, '_pydanticai_tools', [])),
                "output_type": getattr(agent, '_pydanticai_output', {"type": "str"}).get("type", "str"),
            })
        return result

    @router.get("/api/agents/{agent_name}", tags=["agents"])
    async def get_agent_endpoint(agent_name: str) -> dict:
        meta = get_agent(agent_name)
        if meta is None:
            raise HTTPException(404, f"Agent '{agent_name}' not registered")
        live = await store.get_current_version(agent_name)
        tools = getattr(meta, '_pydanticai_tools', [])
        output_info = getattr(meta, '_pydanticai_output', {"type": "str", "schema": None})
        return {
            "name": meta.name,
            "description": meta.description,
            "variables": meta.variables,
            "default_message": meta.default_message,
            "tags": meta.tags,
            "default_system_prompt": meta.default_system_prompt,
            "current_version": live.version if live else None,
            "current_prompt": live.system_prompt if live else meta.default_system_prompt,
            "tools": tools,
            "output_type": output_info,
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
        pv = await store.get_prompt_version(version_id)
        if pv is None or pv.agent_name != agent_name:
            raise HTTPException(404, "Version not found")
        pv = await store.set_status(version_id, PromptStatus.current)
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

        Combines: declared models from @biscotti, pricing table
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

        # Include Azure Foundry deployments (multi-connection)
        from .key_store import iter_azure_models, available_providers
        azure_models = iter_azure_models()

        # Merge: detected first, then declared, then historical, then azure, then pricing defaults.
        # Normalize + dedupe: strip the provider prefix when the bare model name is a known
        # entry in PRICING (PydanticAI accepts both forms). "anthropic:claude-haiku-4-5" and
        # "claude-haiku-4-5" collapse to a single bare "claude-haiku-4-5". azure:<conn>:<dep>
        # stays as-is so the user sees which Foundry connection serves it.
        def _canonical(m: str) -> str:
            if m.startswith("azure:"):
                return m
            if ":" in m:
                _, rest = m.split(":", 1)
                if rest in PRICING:
                    return rest
            return m

        # Hide models whose backing provider isn't configured. Unknown-provider
        # strings (custom model names) stay visible so historical runs remain
        # selectable even when the provider was disconnected.
        connected = {p for p, ok in available_providers().items() if ok}

        def _provider_of(m: str) -> str | None:
            if m.startswith("azure:"):
                return "azure_foundry"
            if ":" in m:
                return m.split(":", 1)[0]
            # Bare model name — derive provider from prefix. PRICING doesn't
            # tag provider, so we can't rely on it here.
            if m in _BARE_MODEL_PROVIDER:
                return _BARE_MODEL_PROVIDER[m]
            for prefix, prov in _BARE_PREFIX_PROVIDER:
                if m.startswith(prefix):
                    return prov
            return None  # keep unknown-provider entries visible

        def _is_reachable(m: str) -> bool:
            prov = _provider_of(m)
            if prov is None:
                return True  # keep unknowns visible
            return prov in connected

        seen: set[str] = set()
        merged: list[str] = []
        for m in ([detected] if detected else []) + declared + historical + azure_models + pricing_models:
            canon = _canonical(m)
            if canon in seen:
                continue
            if not _is_reachable(canon):
                continue
            seen.add(canon)
            merged.append(canon)

        # Dedupe historical too so downstream code doesn't see both forms
        hist_seen: set[str] = set()
        hist_canon: list[str] = []
        for h in historical:
            ch = _canonical(h)
            if ch in hist_seen or not _is_reachable(ch):
                continue
            hist_seen.add(ch)
            hist_canon.append(ch)

        hint = None
        if not connected:
            hint = "Connect a provider in API Keys to enable model overrides."

        return {
            "detected": _canonical(detected) if detected else None,
            "historical": hist_canon,
            "all": merged,
            "hint": hint,
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
        model = (body.get("model") or None) if body else None
        # Fallback: if no model sent from UI, try to detect from the agent callable
        if not model:
            from .runner import get_callable, detect_model_from_callable
            callable_fn = get_callable(agent_name)
            if callable_fn:
                model = detect_model_from_callable(callable_fn) or None
        test_cases = await store.list_test_cases(agent_name)
        if not test_cases:
            raise HTTPException(400, "No test cases defined for this agent.")

        from .models import EvalRun
        from .eval import judge_output

        scores: list[float | None] = []
        case_details: list[dict] = []
        for tc in test_cases:
            req = RunRequest(
                agent_name=agent_name,
                prompt_version_id=version_id,
                user_message=tc.user_message,
                variable_values=tc.variable_values,
                test_case_name=tc.name,
                model=model,
            )
            run_resp = await execute_run(req, store)

            if run_resp.outcome == "error":
                scores.append(None)
                case_details.append({
                    "test_case": tc.name,
                    "error": run_resp.error_message or "Run failed",
                    "score": None,
                    "criteria_results": [],
                    "reasoning": "",
                })
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
            case_details.append({
                "test_case": tc.name,
                "score": eval_result.score,
                "reasoning": eval_result.reasoning,
                "criteria_results": [cr.model_dump() for cr in eval_result.criteria_results],
            })

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
            case_details=case_details,
        ))

        return eval_run.model_dump(mode="json")

    @router.get("/api/agents/{agent_name}/evals", tags=["eval"])
    async def list_evals(agent_name: str) -> list[dict]:
        _require_agent(agent_name)
        runs = await store.list_eval_runs(agent_name)
        # Exclude case_details from list to keep it lightweight
        return [
            {k: v for k, v in r.model_dump(mode="json").items() if k != "case_details"}
            for r in runs
        ]

    @router.post("/api/agents/{agent_name}/coach", tags=["eval"])
    async def run_coach(agent_name: str, body: dict | None = None) -> dict:
        """Get AI coaching suggestions. Works with or without eval results."""
        _require_agent(agent_name)
        settings = await store.get_agent_settings(agent_name)

        coach_model = (body or {}).get("coach_model") or settings.coach_model
        if not coach_model:
            raise HTTPException(400, "No coach model configured. Select a model in the Coach panel.")

        eval_id = (body or {}).get("eval_id")
        prompt_text = (body or {}).get("prompt")
        custom_system_prompt = (body or {}).get("coach_system_prompt")

        # Get the prompt to coach on (explicit or current version)
        if prompt_text:
            system_prompt = prompt_text
        else:
            pv = await store.get_current_version(agent_name)
            if pv is None:
                raise HTTPException(400, "No prompt version found")
            system_prompt = pv.system_prompt

        # If eval_id provided, use eval results for richer coaching
        if eval_id:
            eval_run = await store.get_eval_run(agent_name, eval_id)
            case_details = eval_run.get("case_details", []) if eval_run else []
            test_cases = await store.list_test_cases(agent_name)

            from .eval import generate_coaching
            coach_result = await generate_coaching(
                system_prompt=system_prompt,
                criteria_text=settings.judge_criteria,
                case_details=case_details,
                test_cases=test_cases,
                model=coach_model,
                custom_system_prompt=custom_system_prompt,
            )
        else:
            # Prompt-only coaching (no eval needed)
            from .eval import coach_prompt
            coach_result = await coach_prompt(
                system_prompt=system_prompt,
                model=coach_model,
                custom_system_prompt=custom_system_prompt,
            )

        return coach_result.model_dump()

    @router.get("/api/agents/{agent_name}/evals/{eval_id}", tags=["eval"])
    async def get_eval(agent_name: str, eval_id: int) -> dict:
        """Get a specific eval run with full case details."""
        _require_agent(agent_name)
        result = await store.get_eval_run(agent_name, eval_id)
        if result is None:
            raise HTTPException(404, "Eval run not found")
        return result

    # ==================================================================
    # Export / Import
    # ==================================================================

    @router.get("/api/agents/{agent_name}/export", tags=["export-import"])
    async def export_agent(agent_name: str) -> JSONResponse:
        """Export agent config (versions, test cases, settings) as a downloadable JSON bundle."""
        _require_agent(agent_name)

        versions = await store.list_versions(agent_name)
        test_cases = await store.list_test_cases(agent_name)
        settings = await store.get_agent_settings(agent_name)

        bundle = {
            "agent_name": agent_name,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "versions": [v.model_dump(mode="json") for v in versions],
            "test_cases": [tc.model_dump(mode="json") for tc in test_cases],
            "settings": settings.model_dump(mode="json"),
        }

        return JSONResponse(
            content=bundle,
            headers={
                "Content-Disposition": f'attachment; filename="{agent_name}-export.json"',
            },
        )

    @router.post("/api/agents/{agent_name}/import", tags=["export-import"])
    async def import_agent(agent_name: str, body: dict) -> dict:
        """Import versions, test cases, and settings from a JSON bundle."""
        _require_agent(agent_name)

        versions_imported = 0
        test_cases_imported = 0

        for v in body.get("versions", []):
            await store.create_prompt_version(PromptVersionCreate(
                agent_name=agent_name,
                system_prompt=v["system_prompt"],
                variables=v.get("variables", []),
                notes=v.get("notes", ""),
                created_by=v.get("created_by", "import"),
            ))
            versions_imported += 1

        for tc in body.get("test_cases", []):
            await store.upsert_test_case(TestCaseCreate(
                agent_name=agent_name,
                name=tc["name"],
                user_message=tc["user_message"],
                variable_values=tc.get("variable_values", {}),
            ))
            test_cases_imported += 1

        if "settings" in body:
            s = body["settings"]
            await store.update_agent_settings(
                agent_name,
                judge_criteria=s.get("judge_criteria", ""),
                judge_model=s.get("judge_model", ""),
                coach_enabled=s.get("coach_enabled", True),
            )

        return {
            "status": "ok",
            "versions_imported": versions_imported,
            "test_cases_imported": test_cases_imported,
        }

    # ==================================================================
    # Settings: API key management
    # ==================================================================

    @router.get("/api/settings/status", tags=["settings"])
    async def api_key_status() -> dict:
        from .key_store import available_providers
        return available_providers()

    @router.post("/api/settings/api-key", tags=["settings"])
    async def set_api_key(body: dict) -> dict:
        from .key_store import set_key, available_providers, KNOWN_PROVIDERS
        provider = body.get("provider", "")
        key = body.get("key", "")
        if provider not in KNOWN_PROVIDERS:
            raise HTTPException(400, f"Unknown provider '{provider}'. Known providers: {', '.join(KNOWN_PROVIDERS)}")
        if not key:
            raise HTTPException(400, "Key cannot be empty")
        set_key(provider, key)
        return {"status": "ok", "providers": available_providers()}

    @router.delete("/api/settings/api-key/{provider}", tags=["settings"])
    async def remove_api_key(provider: str) -> dict:
        from .key_store import remove_key, available_providers, KNOWN_PROVIDERS
        if provider not in KNOWN_PROVIDERS:
            raise HTTPException(400, f"Unknown provider '{provider}'. Known providers: {', '.join(KNOWN_PROVIDERS)}")
        remove_key(provider)
        return {"status": "ok", "providers": available_providers()}

    # ==================================================================
    # Settings: Azure Foundry (multi-connection)
    # ==================================================================

    def _render_connection(name: str, conn: dict) -> dict:
        """Public-safe view of a connection (no key exposed)."""
        return {
            "name": name,
            "endpoint": conn["endpoint"],
            "auth": conn.get("auth", "key"),
            "api_version": conn["api_version"],
            "deployments": [
                {
                    "name": d["name"],
                    "endpoint": d.get("endpoint"),
                    "model": d.get("model"),
                    "wire": d.get("wire", "openai"),
                    "version": d.get("version"),
                }
                for d in conn.get("deployments", [])
            ],
            "discovered_at": conn.get("discovered_at"),
            "discovery_error": conn.get("discovery_error"),
        }

    @router.get("/api/settings/azure/connections", tags=["settings"])
    async def list_azure() -> dict:
        from .key_store import list_azure_connections
        conns = list_azure_connections()
        return {
            "connections": [_render_connection(n, c) for n, c in conns.items()],
        }

    @router.post("/api/settings/azure/connections", tags=["settings"])
    async def create_azure_connection(body: dict) -> dict:
        from .key_store import (
            add_azure_connection,
            get_azure_connection,
            remove_azure_connection,
            set_azure_deployments,
            available_providers,
        )
        from .azure_discovery import discover_deployments, DiscoveryError
        import time

        from .azure_discovery import _normalize_endpoint
        name = (body.get("name") or "").strip()
        raw_endpoint = (body.get("endpoint") or "").strip()
        endpoint = _normalize_endpoint(raw_endpoint) if raw_endpoint else ""
        auth = (body.get("auth") or "key").strip()
        key = (body.get("key") or "").strip() or None
        api_version = (body.get("api_version") or "2024-10-21").strip()

        if not name:
            raise HTTPException(400, "Connection name is required")
        if not endpoint:
            raise HTTPException(400, "Endpoint is required")
        if auth not in ("key", "aad"):
            raise HTTPException(400, f"auth must be 'key' or 'aad', got {auth!r}")
        if auth == "key" and not key:
            raise HTTPException(400, "Key auth requires a non-empty 'key'")
        if get_azure_connection(name) is not None:
            raise HTTPException(409, f"Connection {name!r} already exists. Disconnect first to recreate.")

        try:
            conn = add_azure_connection(
                name,
                endpoint=endpoint,
                auth=auth,
                key=key,
                api_version=api_version,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        # We used to auto-run discovery here, but on most Foundry resources
        # the data-plane listing endpoints are not exposed (404s across the
        # board). Save the connection and let the user add deployments
        # manually. Refresh remains available if they want to try listing.
        return {
            "status": "ok",
            "connection": _render_connection(name, conn),
            "providers": available_providers(),
        }

    @router.post("/api/settings/azure/connections/{name}/refresh", tags=["settings"])
    async def refresh_azure_connection(name: str) -> dict:
        from .key_store import get_azure_connection, set_azure_deployments
        from .azure_discovery import discover_deployments, DiscoveryError
        import time

        conn = get_azure_connection(name)
        if conn is None:
            raise HTTPException(404, f"Connection {name!r} not found")
        try:
            deployments = await discover_deployments(
                conn["endpoint"],
                auth=conn.get("auth", "key"),
                key=conn.get("key"),
                api_version=conn["api_version"],
            )
            set_azure_deployments(name, deployments, discovered_at=time.time())
        except DiscoveryError as exc:
            set_azure_deployments(name, conn.get("deployments", []), discovery_error=str(exc))
            raise HTTPException(502, str(exc))
        return {"status": "ok", "connection": _render_connection(name, conn)}

    @router.delete("/api/settings/azure/connections/{name}", tags=["settings"])
    async def delete_azure_connection(name: str) -> dict:
        from .key_store import remove_azure_connection, available_providers
        remove_azure_connection(name)
        return {"status": "ok", "providers": available_providers()}

    @router.post("/api/settings/azure/connections/{name}/deployments", tags=["settings"])
    async def add_azure_deployment_manual(name: str, body: dict) -> dict:
        """Manually append a deployment to a connection.

        The connection's base endpoint + the underlying model name together
        determine where requests go — we infer wire from the model
        (``claude*`` → anthropic, else openai) and derive the URL from there.
        Per-deployment endpoint overrides and explicit wires remain supported
        as escape hatches via the ``endpoint`` / ``wire`` body fields."""
        from .key_store import get_azure_connection, set_azure_deployments
        from .eval import infer_azure_wire

        conn = get_azure_connection(name)
        if conn is None:
            raise HTTPException(404, f"Connection {name!r} not found")

        dep_name = (body.get("name") or "").strip()
        model = (body.get("model") or "").strip() or None
        # These two are optional overrides for edge cases.
        endpoint = (body.get("endpoint") or "").strip() or None
        explicit_wire = (body.get("wire") or "").strip() or None
        version = (body.get("version") or "").strip() or None

        if not dep_name:
            raise HTTPException(400, "Deployment name is required")

        wire = explicit_wire or infer_azure_wire(endpoint=endpoint or "",
                                                 model=model)
        if wire not in ("openai", "anthropic"):
            raise HTTPException(400, f"wire must be 'openai' or 'anthropic', got {wire!r}")

        existing = list(conn.get("deployments", []))
        if any(d["name"] == dep_name for d in existing):
            raise HTTPException(409, f"Deployment {dep_name!r} already exists on {name!r}")
        existing.append({
            "name": dep_name,
            "endpoint": endpoint,
            "model": model,
            "wire": wire,
            "version": version,
        })
        set_azure_deployments(
            name, existing,
            discovered_at=conn.get("discovered_at"),
            discovery_error=conn.get("discovery_error"),
        )
        return {"status": "ok", "connection": _render_connection(name, conn)}

    @router.delete("/api/settings/azure/connections/{name}/deployments/{dep_name}", tags=["settings"])
    async def remove_azure_deployment_manual(name: str, dep_name: str) -> dict:
        from .key_store import get_azure_connection, set_azure_deployments

        conn = get_azure_connection(name)
        if conn is None:
            raise HTTPException(404, f"Connection {name!r} not found")
        existing = [d for d in conn.get("deployments", []) if d["name"] != dep_name]
        set_azure_deployments(
            name, existing,
            discovered_at=conn.get("discovered_at"),
            discovery_error=conn.get("discovery_error"),
        )
        return {"status": "ok", "connection": _render_connection(name, conn)}

    # ==================================================================
    # Bulk Runs
    # ==================================================================

    @router.post("/api/agents/{agent_name}/bulk-run", tags=["bulk-runs"])
    async def start_bulk_run(agent_name: str, body: BulkRunRequest) -> dict:
        """Start a bulk run (matrix of test cases x model configs)."""
        import asyncio
        _require_agent(agent_name)
        body.agent_name = agent_name

        # Resolve prompt version
        if body.prompt_version_id is not None:
            pv = await store.get_prompt_version(body.prompt_version_id)
            prompt_version = pv.version if pv else 0
        else:
            pv = await store.get_current_version(agent_name)
            prompt_version = pv.version if pv else 0

        # Compute total runs from the plan
        from .bulk import generate_run_plan
        plan = generate_run_plan(
            test_case_names=body.test_case_names,
            models=body.models,
            temperatures=body.temperatures,
            reasoning_efforts=body.reasoning_efforts,
        )
        total_runs = len(plan)

        # Persist bulk run record
        config_matrix = {
            "models": body.models,
            "temperatures": body.temperatures,
            "reasoning_efforts": body.reasoning_efforts,
        }
        bulk_run_id = await store.save_bulk_run(
            agent_name=agent_name,
            prompt_version=prompt_version,
            config_matrix=config_matrix,
            test_cases=body.test_case_names,
            include_eval=body.include_eval,
            judge_model=body.judge_model,
            concurrency=body.concurrency,
            total_runs=total_runs,
        )

        # Launch background execution
        from .bulk import execute_bulk_run_by_id
        asyncio.create_task(execute_bulk_run_by_id(bulk_run_id, body, store))

        bulk_run = await store.get_bulk_run(bulk_run_id)
        return bulk_run

    @router.get("/api/agents/{agent_name}/bulk-runs", tags=["bulk-runs"])
    async def list_bulk_runs(agent_name: str, limit: int = 50) -> list[dict]:
        _require_agent(agent_name)
        return await store.list_bulk_runs(agent_name, limit=limit)

    @router.get("/api/agents/{agent_name}/bulk-runs/{bulk_run_id}", tags=["bulk-runs"])
    async def get_bulk_run_detail(agent_name: str, bulk_run_id: int) -> dict:
        _require_agent(agent_name)
        bulk_run = await store.get_bulk_run(bulk_run_id)
        if bulk_run is None or bulk_run["agent_name"] != agent_name:
            raise HTTPException(404, "Bulk run not found")
        runs = await store.get_bulk_run_runs(bulk_run_id)
        bulk_run["runs"] = [r.model_dump(mode="json") for r in runs]
        return bulk_run

    @router.delete(
        "/api/agents/{agent_name}/bulk-runs/{bulk_run_id}",
        tags=["bulk-runs"],
    )
    async def delete_bulk_run(agent_name: str, bulk_run_id: int) -> dict:
        """Delete a bulk run and its associated run_logs."""
        _require_agent(agent_name)
        bulk_run = await store.get_bulk_run(bulk_run_id)
        if bulk_run is None or bulk_run["agent_name"] != agent_name:
            raise HTTPException(404, "Bulk run not found")
        await store.delete_bulk_run(bulk_run_id)
        return {"deleted": True}

    @router.get("/api/agents/{agent_name}/bulk-runs/{bulk_run_id}/stream", tags=["bulk-runs"])
    async def stream_bulk_run(agent_name: str, bulk_run_id: int):
        """SSE stream that polls bulk run progress."""
        import asyncio
        import json
        from starlette.responses import StreamingResponse

        _require_agent(agent_name)
        bulk_run = await store.get_bulk_run(bulk_run_id)
        if bulk_run is None or bulk_run["agent_name"] != agent_name:
            raise HTTPException(404, "Bulk run not found")

        emitted_ids: set[int] = set()
        last_completed = -1

        def _is_fully_done(run, include_eval: bool) -> bool:
            """A run is 'done' only once the judge (if enabled) has also finished.

            - If include_eval is False → the run is done as soon as the LLM call
              returns (any outcome).
            - If the outcome wasn't success, the judge is skipped, so the run is
              done regardless of score.
            - Otherwise (eval enabled + success) we require a score to be set.
            """
            if not include_eval:
                return True
            if run.outcome != "success":
                return True
            return run.score is not None

        async def event_stream():
            nonlocal last_completed
            while True:
                br = await store.get_bulk_run(bulk_run_id)
                if br is None:
                    break

                current_completed = br["completed_runs"]
                include_eval = bool(br.get("include_eval"))

                # Emit run_complete only for runs that are fully done (including
                # the judge evaluation when enabled). This keeps the UI from
                # flashing score-less rows that then need to be re-rendered.
                runs = await store.get_bulk_run_runs(bulk_run_id)
                new_runs = [
                    r for r in runs
                    if r.id not in emitted_ids and _is_fully_done(r, include_eval)
                ]
                for run in new_runs:
                    yield f"event: run_complete\ndata: {json.dumps(run.model_dump(mode='json'))}\n\n"
                    emitted_ids.add(run.id)

                # Emit a progress event any time the completed counter advances,
                # not just when new rows appear. Handles the case where a late
                # judge result bumps completed_runs after its row was already sent.
                if current_completed != last_completed:
                    yield f"event: progress\ndata: {json.dumps({'completed': current_completed, 'total': br['total_runs']})}\n\n"
                    last_completed = current_completed

                if br["status"] in ("completed", "cancelled", "error"):
                    yield f"event: done\ndata: {json.dumps({'id': bulk_run_id, 'status': br['status'], 'completed': br['completed_runs'], 'total': br['total_runs']})}\n\n"
                    break

                await asyncio.sleep(0.3)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.get("/api/agents/{agent_name}/bulk-runs/{bulk_run_id}/export", tags=["bulk-runs"])
    async def export_bulk_run(
        agent_name: str,
        bulk_run_id: int,
        format: str = "csv",
    ):
        from starlette.responses import Response
        from .export import generate_export

        _require_agent(agent_name)
        bulk_run = await store.get_bulk_run(bulk_run_id)
        if bulk_run is None or bulk_run["agent_name"] != agent_name:
            raise HTTPException(404, "Bulk run not found")

        runs = await store.get_bulk_run_runs(bulk_run_id)
        include_score = bulk_run.get("include_eval", False)
        data = generate_export(runs, format=format, include_score=include_score)

        content_types = {
            "csv": "text/csv",
            "tsv": "text/tab-separated-values",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        ext = format if format in content_types else "csv"
        return Response(
            content=data,
            media_type=content_types.get(ext, "text/csv"),
            headers={"Content-Disposition": f'attachment; filename="bulk-run-{bulk_run_id}.{ext}"'},
        )

    @router.post("/api/agents/{agent_name}/bulk-runs/{bulk_run_id}/cancel", tags=["bulk-runs"])
    async def cancel_bulk_run(agent_name: str, bulk_run_id: int) -> dict:
        _require_agent(agent_name)
        bulk_run = await store.get_bulk_run(bulk_run_id)
        if bulk_run is None or bulk_run["agent_name"] != agent_name:
            raise HTTPException(404, "Bulk run not found")
        await store.update_bulk_run(bulk_run_id, status="cancelled")
        return {"id": bulk_run_id, "status": "cancelled"}

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
