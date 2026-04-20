"""
biscotti.bulk
~~~~~~~~~~~~~
Bulk run orchestrator — executes a matrix of test cases x model configs
with concurrency control, yielding SSE-compatible events.
"""
from __future__ import annotations

import asyncio
import logging
from itertools import product
from typing import Any, AsyncGenerator

from .models import BulkRunRequest, BulkRunStatus, RunRequest
from .store import PromptStore

logger = logging.getLogger("biscotti.bulk")


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------

def generate_run_plan(
    *,
    test_case_names: list[str],
    models: list[str],
    temperatures: list[float],
    reasoning_efforts: list[str],
) -> list[dict[str, Any]]:
    """Build a flat list of run configs from the cartesian product.

    - If temperatures are provided, cross models x temperatures.
    - If reasoning_efforts are provided, cross models x reasoning_efforts.
    - If both are provided, they create *separate* entries (not crossed with
      each other) — temps are typically for standard models, RE for reasoning.
    - If neither, each model gets a single entry with no param override.

    Every entry is then crossed with every test case.
    """
    # Build model+param combos
    configs: list[dict[str, Any]] = []

    if temperatures and reasoning_efforts:
        for model in models:
            for temp in temperatures:
                configs.append({"model": model, "temperature": temp, "reasoning_effort": None})
            for re_val in reasoning_efforts:
                configs.append({"model": model, "temperature": None, "reasoning_effort": re_val})
    elif temperatures:
        for model, temp in product(models, temperatures):
            configs.append({"model": model, "temperature": temp, "reasoning_effort": None})
    elif reasoning_efforts:
        for model, re_val in product(models, reasoning_efforts):
            configs.append({"model": model, "temperature": None, "reasoning_effort": re_val})
    else:
        for model in models:
            configs.append({"model": model, "temperature": None, "reasoning_effort": None})

    # Cross with test cases
    plan = []
    for tc_name in test_case_names:
        for cfg in configs:
            plan.append({"test_case_name": tc_name, **cfg})

    return plan


# ---------------------------------------------------------------------------
# Bulk run execution
# ---------------------------------------------------------------------------

async def execute_bulk_run(
    request: BulkRunRequest,
    store: PromptStore,
) -> AsyncGenerator[dict[str, Any], None]:
    """Execute a bulk run, yielding SSE-style events.

    Events:
      - ``{"event": "started", "data": {"id": ..., "total": ...}}``
      - ``{"event": "run_complete", "data": {...run details...}}``
      - ``{"event": "progress", "data": {"completed": N, "total": M}}``
      - ``{"event": "done", "data": {"id": ..., "status": "completed"}}``
      - ``{"event": "error", "data": {"message": ...}}``
    """
    from .runner import execute_run  # deferred to avoid circular

    # Build the plan
    plan = generate_run_plan(
        test_case_names=request.test_case_names,
        models=request.models,
        temperatures=request.temperatures,
        reasoning_efforts=request.reasoning_efforts,
    )
    total = len(plan)

    # Resolve prompt version for the DB record
    if request.prompt_version_id is not None:
        pv = await store.get_prompt_version(request.prompt_version_id)
        prompt_version = pv.version if pv else 0
    else:
        pv = await store.get_current_version(request.agent_name)
        prompt_version = pv.version if pv else 0

    # Persist bulk run record
    config_matrix = {
        "models": request.models,
        "temperatures": request.temperatures,
        "reasoning_efforts": request.reasoning_efforts,
    }
    bulk_run_id = await store.save_bulk_run(
        agent_name=request.agent_name,
        prompt_version=prompt_version,
        config_matrix=config_matrix,
        test_cases=request.test_case_names,
        include_eval=request.include_eval,
        judge_model=request.judge_model,
        concurrency=request.concurrency,
        total_runs=total,
    )

    # Pre-fetch all test cases for this agent
    all_test_cases = await store.list_test_cases(request.agent_name)
    tc_map = {tc.name: tc for tc in all_test_cases}

    yield {"event": "started", "data": {"id": bulk_run_id, "total": total}}

    # Concurrency control
    semaphore = asyncio.Semaphore(request.concurrency)
    cancel_event = asyncio.Event()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    completed = 0

    async def _run_one(entry: dict[str, Any]) -> None:
        nonlocal completed
        if cancel_event.is_set():
            return
        async with semaphore:
            if cancel_event.is_set():
                return

            # Look up test case
            tc = tc_map.get(entry["test_case_name"])
            if tc is None:
                await queue.put({
                    "event": "run_error",
                    "data": {"test_case_name": entry["test_case_name"], "message": "Test case not found"},
                })
                return

            run_request = RunRequest(
                agent_name=request.agent_name,
                prompt_version_id=request.prompt_version_id,
                user_message=tc.user_message,
                variable_values=tc.variable_values,
                test_case_name=tc.name,
                run_eval=False,  # eval handled separately in bulk if needed
                model=entry["model"],
                temperature=entry["temperature"],
                reasoning_effort=entry["reasoning_effort"],
            )

            try:
                response = await execute_run(run_request, store)

                # Link the run_log to this bulk run
                await store.db.execute(
                    "UPDATE run_logs SET bulk_run_id = ? WHERE id = ?",
                    (bulk_run_id, response.run_id),
                )
                await store.db.commit()

                # Judge evaluation (if requested and run succeeded)
                score: float | None = None
                score_reasoning: str | None = None
                if request.include_eval and response.outcome.value == "success":
                    try:
                        from .eval import judge_output
                        settings = await store.get_agent_settings(request.agent_name)
                        if settings.judge_criteria:
                            pv_obj = await store.get_current_version(request.agent_name)
                            eval_result = await judge_output(
                                criteria_text=settings.judge_criteria,
                                user_message=tc.user_message,
                                system_prompt=pv_obj.system_prompt if pv_obj else "",
                                agent_output=response.output,
                                model=request.judge_model or settings.judge_model,
                            )
                            score = eval_result.score
                            score_reasoning = eval_result.reasoning
                            await store.update_run_score(response.run_id, score, score_reasoning)
                    except Exception as judge_exc:
                        logger.warning("Judge evaluation failed: %s", judge_exc)

                completed += 1
                await store.update_bulk_run(bulk_run_id, completed_runs=completed)

                await queue.put({
                    "event": "run_complete",
                    "data": {
                        "run_id": response.run_id,
                        "test_case_name": entry["test_case_name"],
                        "model_selected": entry["model"],
                        "model_used": response.model_used or entry["model"],
                        "temperature": entry["temperature"],
                        "reasoning_effort": entry["reasoning_effort"],
                        "output": response.output,
                        "outcome": response.outcome.value,
                        "latency_ms": response.latency_ms,
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                        "estimated_cost": response.estimated_cost,
                        "tool_calls": response.tool_calls,
                        "score": score,
                        "score_reasoning": score_reasoning,
                    },
                })
                await queue.put({
                    "event": "progress",
                    "data": {"completed": completed, "total": total},
                })
            except Exception as exc:
                logger.exception("Bulk run task failed: %s", exc)
                await queue.put({
                    "event": "run_error",
                    "data": {
                        "test_case_name": entry["test_case_name"],
                        "model": entry["model"],
                        "message": str(exc),
                    },
                })

    # Launch all tasks
    tasks = [asyncio.create_task(_run_one(entry)) for entry in plan]

    # Sentinel to signal all tasks are done
    async def _wait_all() -> None:
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.put(None)  # sentinel

    waiter = asyncio.create_task(_wait_all())

    # Drain the queue until sentinel
    while True:
        event = await queue.get()
        if event is None:
            break
        yield event

    # Finalize
    final_status = BulkRunStatus.completed.value
    await store.update_bulk_run(bulk_run_id, status=final_status, completed_runs=completed)

    yield {
        "event": "done",
        "data": {"id": bulk_run_id, "status": final_status, "completed": completed, "total": total},
    }


async def execute_bulk_run_by_id(
    bulk_run_id: int,
    request: BulkRunRequest,
    store: PromptStore,
) -> None:
    """Variant for background tasks where the bulk_run DB record already exists.

    Consumes the generator internally — useful for FastAPI background tasks.
    """
    from .runner import execute_run

    plan = generate_run_plan(
        test_case_names=request.test_case_names,
        models=request.models,
        temperatures=request.temperatures,
        reasoning_efforts=request.reasoning_efforts,
    )
    total = len(plan)
    semaphore = asyncio.Semaphore(request.concurrency)
    completed = 0

    all_test_cases = await store.list_test_cases(request.agent_name)
    tc_map = {tc.name: tc for tc in all_test_cases}

    async def _run_one(entry: dict[str, Any]) -> None:
        nonlocal completed
        async with semaphore:
            tc = tc_map.get(entry["test_case_name"])
            if tc is None:
                return

            run_request = RunRequest(
                agent_name=request.agent_name,
                prompt_version_id=request.prompt_version_id,
                user_message=tc.user_message,
                variable_values=tc.variable_values,
                test_case_name=tc.name,
                run_eval=False,
                model=entry["model"],
                temperature=entry["temperature"],
                reasoning_effort=entry["reasoning_effort"],
            )

            try:
                response = await execute_run(run_request, store)
                await store.db.execute(
                    "UPDATE run_logs SET bulk_run_id = ? WHERE id = ?",
                    (bulk_run_id, response.run_id),
                )
                await store.db.commit()

                # Judge evaluation — must run before incrementing completed so
                # the SSE poller picks up the score in the same DB read.
                if request.include_eval and response.outcome.value == "success":
                    try:
                        from .eval import judge_output
                        settings = await store.get_agent_settings(request.agent_name)
                        if settings.judge_criteria:
                            pv_obj = await store.get_current_version(request.agent_name)
                            eval_result = await judge_output(
                                criteria_text=settings.judge_criteria,
                                user_message=tc.user_message,
                                system_prompt=pv_obj.system_prompt if pv_obj else "",
                                agent_output=response.output,
                                model=request.judge_model or settings.judge_model,
                            )
                            await store.update_run_score(
                                response.run_id, eval_result.score, eval_result.reasoning
                            )
                    except Exception as judge_exc:
                        logger.warning("Judge evaluation failed: %s", judge_exc)

                completed += 1
                await store.update_bulk_run(bulk_run_id, completed_runs=completed)
            except Exception as exc:
                logger.exception("Bulk run task failed: %s", exc)

    tasks = [asyncio.create_task(_run_one(entry)) for entry in plan]
    await asyncio.gather(*tasks, return_exceptions=True)

    await store.update_bulk_run(
        bulk_run_id,
        status=BulkRunStatus.completed.value,
        completed_runs=completed,
    )
