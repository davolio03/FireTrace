from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from api.main import create_app
from api.routes import (
    ProfileRequest,
    case,
    health,
    inspect_point,
    inspect_profile,
    layers,
    router,
    stats,
)


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def health(self) -> dict[str, str]:
        self.calls.append(("health", ()))
        return {"status": "ok", "data_status": "mock"}

    def get_case(self) -> dict[str, str]:
        self.calls.append(("case", ()))
        return {"case": "plaskett"}

    def get_stats(self) -> dict[str, str]:
        self.calls.append(("stats", ()))
        return {"stats": "fixture"}

    def get_layers(self) -> dict[str, str]:
        self.calls.append(("layers", ()))
        return {"layers": "fixture"}

    def inspect_point(self, lon: float, lat: float) -> dict[str, Any]:
        self.calls.append(("inspect_point", (lon, lat)))
        return {"query": {"lon": lon, "lat": lat}}

    def inspect_profile(self, line: Any, spacing_m: float) -> dict[str, Any]:
        self.calls.append(("inspect_profile", (line, spacing_m)))
        return {"line": line, "spacing_m": spacing_m}


def test_contract_routes_are_registered() -> None:
    registered = {
        (route.path, method)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }
    assert {
        ("/api/health", "GET"),
        ("/api/case", "GET"),
        ("/api/stats", "GET"),
        ("/api/layers", "GET"),
        ("/api/inspect/point", "GET"),
        ("/api/inspect/profile", "POST"),
    } <= registered


def test_fastapi_app_exposes_contract_routes_and_coordinate_limits() -> None:
    openapi = create_app(service=FakeService()).openapi()

    assert {
        "/api/health",
        "/api/case",
        "/api/stats",
        "/api/layers",
        "/api/inspect/point",
        "/api/inspect/profile",
    } <= set(openapi["paths"])
    point_parameters = openapi["paths"]["/api/inspect/point"]["get"]["parameters"]
    assert {parameter["name"]: parameter["schema"] for parameter in point_parameters} == {
        "lon": {"type": "number", "maximum": 180.0, "minimum": -180.0, "title": "Lon"},
        "lat": {"type": "number", "maximum": 90.0, "minimum": -90.0, "title": "Lat"},
    }


def test_metadata_routes_delegate_to_the_service() -> None:
    service = FakeService()

    assert health(service=service) == {"status": "ok", "data_status": "mock"}
    assert case(service=service) == {"case": "plaskett"}
    assert stats(service=service) == {"stats": "fixture"}
    assert layers(service=service) == {"layers": "fixture"}
    assert service.calls == [
        ("health", ()),
        ("case", ()),
        ("stats", ()),
        ("layers", ()),
    ]


def test_point_route_forwards_coordinates() -> None:
    service = FakeService()

    result = inspect_point(lon=-121.4, lat=35.9, service=service)

    assert result == {"query": {"lon": -121.4, "lat": 35.9}}
    assert service.calls == [("inspect_point", (-121.4, 35.9))]


def test_profile_route_forwards_the_validated_body() -> None:
    service = FakeService()
    body = ProfileRequest(line=[[-121.4, 35.9], [-121.3, 35.8]])

    result = inspect_profile(body=body, service=service)

    assert result == {"line": body.line, "spacing_m": 10.0}
    assert service.calls == [("inspect_profile", (body.line, 10.0))]


@pytest.mark.parametrize(
    "payload",
    [
        {"line": [[-121.4, 35.9]]},
        {"line": [[-121.4, 35.9, 0.0], [-121.3, 35.8]]},
        {"line": [[-181.0, 35.9], [-121.3, 35.8]]},
        {"line": [[-121.4, 95.0], [-121.3, 35.8]]},
        {"line": [[-121.4, float("nan")], [-121.3, 35.8]]},
        {"line": [[-121.4, 35.9], [-121.3, 35.8]], "spacing_m": 0},
        {"line": [[-121.4, 35.9], [-121.3, 35.8]], "spacing_m": -5},
        {"line": [[-121.4, 35.9], [-121.3, 35.8]], "spacing_m": float("inf")},
        {"line": [[-121.4, 35.9], [-121.3, 35.8]], "spacing_m": float("nan")},
    ],
)
def test_profile_request_rejects_invalid_bodies(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ProfileRequest(**payload)
