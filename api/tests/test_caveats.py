"""EV-02 deterministic caveat rules: boundaries, missing inputs and contract shape."""

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from api.caveats import (
    RAIN_WINDOW_DAYS,
    SLOPE_THRESHOLD_DEG,
    PixelContext,
    WeatherSummary,
    evaluate_caveats,
    weather_summary_from_json,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts" / "schemas"
FIXTURES = ROOT / "contracts" / "fixtures"

T2 = date(2026, 10, 3)


def _caveat_validator() -> Draft202012Validator:
    schema = json.loads((SCHEMAS / "inspect-point.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema["properties"]["caveats"])


def _pixel(**overrides: Any) -> PixelContext:
    values: dict[str, Any] = {
        "valid": True,
        "slope_deg": 10.0,
        "layover_shadow": 0,
        "near_perimeter_edge": False,
    }
    values.update(overrides)
    return PixelContext(**values)


def _by_id(caveats: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in caveats}


def _dry() -> WeatherSummary:
    return WeatherSummary(t2_date=T2, last_rain_before_t2=None, data_status="real")


# --- steep_slope -----------------------------------------------------------------


def test_slope_threshold_is_thirty_degrees() -> None:
    assert SLOPE_THRESHOLD_DEG == 30.0


@pytest.mark.parametrize(
    ("slope", "fires"),
    [(29.9, False), (30.0, False), (30.01, True), (34.2, True), (90.0, True)],
)
def test_steep_slope_fires_strictly_above_threshold(slope: float, fires: bool) -> None:
    caveats = _by_id(evaluate_caveats(_pixel(slope_deg=slope), _dry()))
    assert ("steep_slope" in caveats) is fires
    if fires:
        assert caveats["steep_slope"]["triggered"] is True


def test_steep_slope_reason_shows_value_and_threshold() -> None:
    caveats = _by_id(evaluate_caveats(_pixel(slope_deg=34.24), _dry()))
    reason = caveats["steep_slope"]["reason"]
    assert "slope 34.2° > 30°" in reason
    assert "30 m" in reason  # GLO-30 effective resolution caution


def test_slope_reason_never_shows_threshold_as_exceeding_itself() -> None:
    caveats = _by_id(evaluate_caveats(_pixel(slope_deg=30.01), _dry()))
    assert "slope 30.01° > 30°" in caveats["steep_slope"]["reason"]


def test_numpy_sampled_values_are_accepted() -> None:
    np = pytest.importorskip("numpy")
    pixel = _pixel(
        slope_deg=np.float32(35.0),
        layover_shadow=np.uint8(1),
        near_perimeter_edge=np.bool_(True),
    )
    caveats = evaluate_caveats(pixel, _dry())
    assert {"steep_slope", "radar_shadow_layover", "near_perimeter_edge"} <= set(_by_id(caveats))
    _caveat_validator().validate(json.loads(json.dumps(caveats)))


@pytest.mark.parametrize("slope", [None, math.nan])
def test_missing_slope_never_fires(slope: float | None) -> None:
    caveats = _by_id(evaluate_caveats(_pixel(slope_deg=slope), _dry()))
    assert "steep_slope" not in caveats


@pytest.mark.parametrize("slope", [-0.1, 90.1, math.inf])
def test_out_of_range_slope_is_rejected(slope: float) -> None:
    with pytest.raises(ValueError, match="slope"):
        evaluate_caveats(_pixel(slope_deg=slope), _dry())


# --- radar_shadow_layover ------------------------------------------------------


def test_no_layover_or_shadow_is_not_listed() -> None:
    caveats = _by_id(evaluate_caveats(_pixel(layover_shadow=0), _dry()))
    assert "radar_shadow_layover" not in caveats


@pytest.mark.parametrize(("code", "word"), [(1, "layover"), (2, "shadow")])
def test_layover_and_shadow_fire(code: int, word: str) -> None:
    item = _by_id(evaluate_caveats(_pixel(layover_shadow=code), _dry()))["radar_shadow_layover"]
    assert item["triggered"] is True
    assert word in item["reason"]
    assert "approximate" in item["reason"]


@pytest.mark.parametrize("code", [255, None])
def test_unknown_geometry_is_listed_but_not_triggered(code: int | None) -> None:
    item = _by_id(evaluate_caveats(_pixel(layover_shadow=code), _dry()))["radar_shadow_layover"]
    assert item["triggered"] is False
    assert "unknown" in item["reason"]


@pytest.mark.parametrize("code", [3, 254, -1])
def test_unexpected_geometry_code_is_rejected(code: int) -> None:
    with pytest.raises(ValueError, match="layover_shadow"):
        evaluate_caveats(_pixel(layover_shadow=code), _dry())


# --- near_perimeter_edge -------------------------------------------------------


def test_edge_band_fires() -> None:
    item = _by_id(evaluate_caveats(_pixel(near_perimeter_edge=True), _dry()))["near_perimeter_edge"]
    assert item["triggered"] is True
    assert "50 m" in item["reason"]


@pytest.mark.parametrize("edge", [False, None])
def test_outside_edge_band_or_unknown_is_not_listed(edge: bool | None) -> None:
    caveats = _by_id(evaluate_caveats(_pixel(near_perimeter_edge=edge), _dry()))
    assert "near_perimeter_edge" not in caveats


# --- soil_moisture_change ------------------------------------------------------


def test_rain_window_is_seven_days() -> None:
    assert RAIN_WINDOW_DAYS == 7


@pytest.mark.parametrize(("days_before", "fires"), [(1, True), (6, True), (7, True), (8, False)])
def test_recent_rain_fires_within_window(days_before: int, fires: bool) -> None:
    last = date.fromordinal(T2.toordinal() - days_before)
    weather = WeatherSummary(t2_date=T2, last_rain_before_t2=last, data_status="real")
    item = _by_id(evaluate_caveats(_pixel(), weather))["soil_moisture_change"]
    assert item["triggered"] is fires
    assert "AOI" in item["reason"]
    assert last.isoformat() in item["reason"]


def test_no_rain_day_keeps_generic_caution_with_data() -> None:
    item = _by_id(evaluate_caveats(_pixel(), _dry()))["soil_moisture_change"]
    assert item["triggered"] is False
    assert "AOI" in item["reason"]
    assert "no day > 1 mm" in item["reason"]


def test_missing_weather_keeps_exact_generic_fixture_caution() -> None:
    fixture = json.loads((FIXTURES / "api" / "inspect-point-inside.json").read_text("utf-8"))
    expected = _by_id(fixture["caveats"])["soil_moisture_change"]
    assert _by_id(evaluate_caveats(_pixel(), None))["soil_moisture_change"] == expected


def test_rain_on_or_after_t2_is_rejected() -> None:
    weather = WeatherSummary(t2_date=T2, last_rain_before_t2=T2, data_status="real")
    with pytest.raises(ValueError, match="before t2"):
        evaluate_caveats(_pixel(), weather)


def test_mock_weather_is_labelled_in_reason() -> None:
    weather = WeatherSummary(t2_date=T2, last_rain_before_t2=None, data_status="mock")
    item = _by_id(evaluate_caveats(_pixel(), weather))["soil_moisture_change"]
    assert "MOCK" in item["reason"]


# --- weather.json parsing ------------------------------------------------------


def test_weather_summary_from_contract_fixture() -> None:
    doc = json.loads((FIXTURES / "web" / "weather.json").read_text(encoding="utf-8"))
    summary = weather_summary_from_json(doc)
    assert summary is not None
    assert summary.t2_date == date.fromisoformat(doc["period"]["end"])
    assert summary.data_status == doc["data_status"]
    expected_last = doc.get("last_rain_before_t2")
    assert summary.last_rain_before_t2 == (
        date.fromisoformat(expected_last) if expected_last else None
    )


def test_weather_without_last_rain_field_is_unknown() -> None:
    doc = {"data_status": "real", "period": {"start": "2026-08-16", "end": "2026-10-03"}}
    assert weather_summary_from_json(doc) is None


def test_weather_with_explicit_null_last_rain_is_dry() -> None:
    doc = {
        "data_status": "real",
        "period": {"start": "2026-08-16", "end": "2026-10-03"},
        "last_rain_before_t2": None,
    }
    assert weather_summary_from_json(doc) == WeatherSummary(
        t2_date=T2, last_rain_before_t2=None, data_status="real"
    )


# --- vegetation_structure, invalid pixels, order and contract ---------------------


def test_vegetation_structure_matches_fixture_generic_caution() -> None:
    fixture = json.loads((FIXTURES / "api" / "inspect-point-inside.json").read_text("utf-8"))
    expected = _by_id(fixture["caveats"])["vegetation_structure"]
    assert _by_id(evaluate_caveats(_pixel(), _dry()))["vegetation_structure"] == expected


def test_invalid_pixel_has_no_caveats_like_fixture() -> None:
    fixture = json.loads((FIXTURES / "api" / "inspect-point-invalid.json").read_text("utf-8"))
    pixel = _pixel(valid=False, slope_deg=45.0, layover_shadow=1, near_perimeter_edge=True)
    assert evaluate_caveats(pixel, _dry()) == fixture["caveats"] == []


def test_benign_pixel_without_weather_equals_fixture_caveats() -> None:
    fixture = json.loads((FIXTURES / "api" / "inspect-point-inside.json").read_text("utf-8"))
    assert evaluate_caveats(_pixel(), None) == fixture["caveats"]


def test_all_rules_fire_in_contract_enum_order_and_validate() -> None:
    weather = WeatherSummary(t2_date=T2, last_rain_before_t2=date(2026, 9, 30), data_status="real")
    pixel = _pixel(slope_deg=45.0, layover_shadow=1, near_perimeter_edge=True)
    caveats = evaluate_caveats(pixel, weather)
    assert [item["id"] for item in caveats] == [
        "steep_slope",
        "radar_shadow_layover",
        "soil_moisture_change",
        "vegetation_structure",
        "near_perimeter_edge",
    ]
    _caveat_validator().validate(caveats)


@pytest.mark.parametrize("code", [0, 1, 2, 255, None])
@pytest.mark.parametrize("weather", [None, "dry"])
def test_outputs_always_validate_against_contract(code: int | None, weather: str | None) -> None:
    summary = _dry() if weather == "dry" else None
    caveats = evaluate_caveats(_pixel(layover_shadow=code, slope_deg=31.0), summary)
    _caveat_validator().validate(caveats)


def test_evaluation_is_deterministic() -> None:
    pixel = _pixel(slope_deg=40.0, layover_shadow=2, near_perimeter_edge=True)
    assert evaluate_caveats(pixel, _dry()) == evaluate_caveats(pixel, _dry())
