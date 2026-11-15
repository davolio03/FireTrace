"""HTTP routes for the FireTrace API.

The routes delegate data access and raster sampling to an application service attached by
``api.main`` as ``app.state.firetrace_service``. Keeping HTTP concerns here lets the service
own manifest validation and numerical raster reads.

"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, FiniteFloat, field_validator


class ProfileRequest(BaseModel):
    """Validated WGS84 transect request body from ``openapi.yaml``."""

    line: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=2)
    spacing_m: FiniteFloat = Field(default=10.0, gt=0)

    @field_validator("line")
    @classmethod
    def _coordinates_are_wgs84(cls, line: list[tuple[float, float]]) -> list[tuple[float, float]]:
        for lon, lat in line:
            if not -180.0 <= lon <= 180.0 or not -90.0 <= lat <= 90.0:
                raise ValueError("line coordinates must be WGS84 lon/lat within range")
        return line


class FireTraceService(Protocol):
    """Operations required by the contract-facing HTTP routes."""

    def health(self) -> dict[str, Any]: ...

    def get_case(self) -> dict[str, Any]: ...

    def get_stats(self) -> dict[str, Any]: ...

    def get_layers(self) -> dict[str, Any]: ...

    def inspect_point(self, lon: float, lat: float) -> dict[str, Any]: ...

    def inspect_profile(
        self, line: Sequence[Sequence[float]], spacing_m: float
    ) -> dict[str, Any]: ...


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


@router.post("/api/inspect/profile", operation_id="inspectProfile")
def inspect_profile(
    body: ProfileRequest,
    service: Annotated[FireTraceService, Depends(get_service)],
) -> dict[str, Any]:
    """Sample radar evidence along a WGS84 transect on the analysis grid."""
    return service.inspect_profile(line=body.line, spacing_m=body.spacing_m)
