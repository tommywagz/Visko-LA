"""FastAPI ASGI entrypoint for Visko-LA Synthetic Aerial World & Telemetry Platform."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import drive, health_auth, media, sessions, ws_stream
from app.services.session_manager import runtime


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    runtime.ensure_initialized()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Visko-LA Synthetic Aerial World & Telemetry Platform API",
        version="1.0.0",
        description=(
            "Server-side streaming, UAV forward/downward system prompt compilation, "
            "coupled ISA/Dryden physics telemetry, and dual-mode GCS + BigQuery dataset catalog."
        ),
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "Content-Disposition",
            "Content-Range",
            "Accept-Ranges",
            "Content-Length",
        ],
    )

    application.include_router(health_auth.router)
    application.include_router(media.router)
    application.include_router(sessions.router)
    application.include_router(ws_stream.router)
    application.include_router(drive.router)
    return application


app = create_app()
