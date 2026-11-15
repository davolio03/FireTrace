"""HTTP routes for the FireTrace API.

The routes delegate data access and raster sampling to an application service attached by
``api.main`` as ``app.state.firetrace_service``. Keeping HTTP concerns here lets the service
own manifest validation and numerical raster reads.

"""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request


class FireTraceService(Protocol):
    """Operations required by the contract-facing HTTP routes."""

    def health(self) -> dict[str, Any]: ...

    def get_case(self) -> dict[str, Any]: ...

    def get_stats(self) -> dict[str, Any]: ...

    def get_layers(self) -> dict[str, Any]: ...

    def inspect_point(self, lon: float, lat: float) -> dict[str, Any]: ...


def get_service(request: Request) -> FireTraceService:
    """Return the service configured by the application factory."""
    service = getattr(request.app.state, "firetrace_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="FireTrace data service is not configured",
        )
    return service


router = APIRouter()


@router.get("/api/health", operation_id="getHealth")
def health(service: Annotated[FireTraceService, Depends(get_service)]) -> dict[str, Any]:
    """Report API readiness and whether the configured case data is mock or real."""
    return service.health()


@router.get("/api/case", operation_id="getCase")
def case(service: Annotated[FireTraceService, Depends(get_service)]) -> dict[str, Any]:
    """Return the case metadata document defined by ``case.schema.json``."""
    return service.get_case()


@router.get("/api/stats", operation_id="getStats")
def stats(service: Annotated[FireTraceService, Depends(get_service)]) -> dict[str, Any]:
    """Return descriptive statistics over the valid analysis pixels."""
    return service.get_stats()


@router.get("/api/layers", operation_id="getLayers")
def layers(service: Annotated[FireTraceService, Depends(get_service)]) -> dict[str, Any]:
    """Return the map layer manifest defined by ``layers.schema.json``."""
    return service.get_layers()


@router.get("/api/inspect/point", operation_id="inspectPoint")
def inspect_point(
    lon: Annotated[float, Query(ge=-180, le=180)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    service: Annotated[FireTraceService, Depends(get_service)],
) -> dict[str, Any]:
    """Return computed radar evidence for the analysis-grid pixel under WGS84 lon/lat."""
    return service.inspect_point(lon=lon, lat=lat)
