"""ASGI application entry point for the FireTrace API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from api.raster import FireTraceRasterService
from api.routes import router

CONTRACT_VERSION = "1.2.0"


def create_app(*, service: Any | None = None) -> FastAPI:
    """Create the API app and attach the configured data/raster service."""
    app = FastAPI(
        title="FireTrace Explorer API",
        version=CONTRACT_VERSION,
        description=(
            "Contract-defined API for case metadata, map layers, statistics, "
            "and evidence inspection."
        ),
    )
    app.state.firetrace_service = service if service is not None else FireTraceRasterService()
    app.include_router(router)
    return app


app = create_app()
