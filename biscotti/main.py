"""
biscotti.main
~~~~~~~~~~~~~~
The Biscotti class — the single object users interact with.

Usage::

    from biscotti import Biscotti, biscotti

    @biscotti(name="recipe agent")
    async def recipe_agent(msg: str, prompt: str) -> str:
        ...

    bi = Biscotti()
    app.mount("/biscotti", bi.app)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI

from .registry import list_agents, register_agent
from .models import AgentMeta
from .router import build_router
from .store import PromptStore


class Biscotti:
    """
    Mount biscotti into a FastAPI application.

    Parameters
    ----------
    storage:
        SQLite connection string, e.g. ``"sqlite:///biscotti.db"`` or
        ``":memory:"`` for tests.  Defaults to ``"biscotti.db"`` in the
        current directory.
    title:
        Browser title for the UI.
    """

    def __init__(
        self,
        storage: str = "biscotti.db",
        title: str = "biscotti",    ) -> None:
        db_path = storage.replace("sqlite:///", "").replace("sqlite://", "")
        self._store = PromptStore(db_path=db_path)
        self._title = title
        self._router = None
        self._app = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def store(self) -> PromptStore:
        return self._store

    @property
    def router(self):
        """FastAPI router — use with app.include_router(bi.router, prefix='/biscotti')."""
        if self._router is None:
            self._router = build_router(self._store)
        return self._router

    @property
    def app(self) -> FastAPI:
        """
        Standalone FastAPI sub-application — use with app.mount('/biscotti', bi.app).
        Handles its own lifespan (DB connect/close).
        """
        if self._app is None:
            self._app = self._build_app()
        return self._app

    def mount(self, host_app: "FastAPI", path: str = "/biscotti") -> None:
        """
        Mount biscotti into a host FastAPI application.

        Usage::

            bi = Biscotti()
            bi.mount(app)           # mounts at /biscotti
            bi.mount(app, "/tools") # mounts at /tools

        This avoids the name-shadowing issue where ``app.mount(...)``
        resolves ``app`` to a package module instead of the FastAPI instance.
        """
        host_app.mount(path, self.app)

    # ------------------------------------------------------------------
    # Seed default prompts on startup
    # ------------------------------------------------------------------

    async def _seed_defaults(self) -> None:
        """
        For every registered agent that has a default_system_prompt but no
        versions yet in the store, create v1 and set it as current.
        """
        from .models import PromptStatus, PromptVersionCreate

        for meta in list_agents():
            if not meta.default_system_prompt:
                continue
            versions = await self._store.list_versions(meta.name)
            if versions:
                continue
            pv = await self._store.create_prompt_version(
                PromptVersionCreate(
                    agent_name=meta.name,
                    system_prompt=meta.default_system_prompt,
                    notes="Auto-seeded from default_system_prompt",
                )
            )
            await self._store.set_status(pv.id, PromptStatus.current)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_app(self) -> FastAPI:
        store = self._store
        seed = self._seed_defaults
        _initialized = False

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
            nonlocal _initialized
            await store.connect()
            await seed()
            _initialized = True
            yield
            await store.close()

        sub_app = FastAPI(
            title=self._title,
            lifespan=lifespan,
            docs_url="/openapi",
            redoc_url=None,
        )

        @sub_app.middleware("http")
        async def ensure_db(request, call_next):
            """Lazy-init fallback when the sub-app lifespan is not triggered."""
            nonlocal _initialized
            if not _initialized:
                await store.ensure_connected()
                await seed()
                _initialized = True
            return await call_next(request)

        sub_app.include_router(build_router(store))
        return sub_app

    # ------------------------------------------------------------------
    # Context manager for scripts / tests
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "Biscotti":
        await self._store.connect()
        await self._seed_defaults()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._store.close()
