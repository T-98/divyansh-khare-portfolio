"""FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import sessions, transcribe
from .config import get_settings
from .logging_setup import configure_logging
from .models.api import HealthResponse
from .persistence.sqlite import SQLiteSessionStore
from .services.orchestrator import Orchestrator


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    store = SQLiteSessionStore(settings.sqlite_path)
    await store.init()
    app.state.store = store
    app.state.orchestrator = Orchestrator(store)
    try:
        yield
    finally:
        await store.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Interview Copilot", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(sessions.router)
    app.include_router(transcribe.router)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            openai_key_configured=bool(settings.openai_api_key),
            models={
                "router": settings.router_model,
                "specialist": settings.specialist_model,
                "editor": settings.editor_model,
                "deep": settings.deep_model,
                "transcribe": settings.transcribe_model,
                "fallback": settings.fallback_model,
            },
            persistence=settings.sqlite_path,
        )

    return app


app = create_app()
