# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.20"]
# ///
"""Validate a FireTrace data directory against the contract schemas.

Usage (from the repo root):
    uv run contracts/tools/validate.py                         # fixtures (web + api)
    uv run contracts/tools/validate.py data/processed/web      # real pipeline output

Exit code 1 on any violation. Run it in CI for fixtures and in pipeline tests for real outputs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts" / "schemas"


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load(SCHEMAS / f"{name}.schema.json"), format_checker=Draft202012Validator.FORMAT_CHECKER)


def check(path: Path, schema: str, errors: list[str]) -> dict | None:
    if not path.exists():
        errors.append(f"missing: {path}")
        return None
    doc = load(path)
    for e in sorted(validator(schema).iter_errors(doc), key=lambda e: list(e.path)):
        loc = "/".join(map(str, e.path)) or "<root>"
        errors.append(f"{path.name}: {loc}: {e.message}")
    return doc


def check_web_dir(web: Path, errors: list[str]) -> None:
    case = check(web / "case.json", "case", errors)
    check(web / "stats.json", "stats", errors)
    layers = check(web / "layers.json", "layers", errors)
    statuses = {d.get("data_status") for d in (case, layers) if d}
    if len(statuses) > 1:
        errors.append(f"inconsistent data_status across files: {statuses}")
    for layer in (layers or {}).get("layers", []):
        url = layer.get("url")
        if url and not (web / url).exists():
            errors.append(f"layers.json: {layer['id']}: file not found: {url}")
    # Optional P1 product: validated whenever it is published.
    if (web / "review_zones.geojson").exists():
        zones = check(web / "review_zones.geojson", "review-zones", errors)
        if zones and case and zones.get("data_status") != case.get("data_status"):
            errors.append("review_zones.geojson: data_status differs from case.json")


def main() -> int:
    errors: list[str] = []
    if len(sys.argv) > 1:
        check_web_dir(Path(sys.argv[1]), errors)
    else:
        fixtures = ROOT / "contracts" / "fixtures"
        check_web_dir(fixtures / "web", errors)
        check(fixtures / "api" / "stats-with-highlight.json", "stats", errors)
        for p in sorted((fixtures / "api").glob("inspect-point-*.json")):
            check(p, "inspect-point", errors)
    for e in errors:
        print(f"ERROR {e}")
    print("OK: contract satisfied" if not errors else f"FAILED: {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
