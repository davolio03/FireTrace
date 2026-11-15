"""Draw the XP-02 sensitivity curves as a static SVG for the docs (DL-02).

Reads the XP-02 ``sensitivity.csv`` and writes one SVG with two panels for the
XP-01 smoothing (window 3): IoU with the reference perimeter, and highlighted area
outside it, against the threshold, for the combined, HH and HV indices. The
chance baseline of the combined index is drawn dashed. Standard library only;
the output is deterministic for a given CSV.

Usage: python scripts/plot_sensitivity.py <sensitivity.csv> <output.svg>
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

WINDOW = "3"
XP01_THRESHOLD = 2.0
SERIES = (  # (index, label, light colour, dark colour)
    ("combined", "Combined", "#2a78d6", "#3987e5"),
    ("hh", "HH only", "#eb6834", "#d95926"),
    ("hv", "HV only", "#1baf7a", "#199e70"),
)

WIDTH, HEIGHT = 720, 640
LEFT, RIGHT = 64, 24
PANEL_H, PANEL_GAP, TOP = 190, 90, 90
X_MIN, X_MAX = 0.5, 5.0


def load(path: Path) -> dict[str, list[dict[str, float]]]:
    rows: dict[str, list[dict[str, float]]] = {name: [] for name, *_ in SERIES}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["window"] != WINDOW or row["index"] not in rows:
                continue
            rows[row["index"]].append(
                {
                    "threshold": float(row["threshold"]),
                    "iou": float(row["iou"]),
                    "chance": float(row["iou_chance"]),
                    "outside": float(row["outside_ha"]),
                }
            )
    for name, points in rows.items():
        if not points:
            raise SystemExit(f"no window-{WINDOW} rows for index {name!r}")
        points.sort(key=lambda p: p["threshold"])
    return rows


def sx(t: float) -> float:
    return LEFT + (t - X_MIN) / (X_MAX - X_MIN) * (WIDTH - LEFT - RIGHT)


def panel(out: list[str], rows, key: str, y_max: float, ticks, top: float, title: str, unit) -> None:
    def sy(v: float) -> float:
        return top + PANEL_H - v / y_max * PANEL_H

    out.append(f'<text class="title" x="{LEFT}" y="{top - 22}">{title}</text>')
    for v in ticks:
        y = sy(v)
        out.append(f'<line class="grid" x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">{unit(v)}</text>')
    for t in (0.5, 1, 2, 3, 4, 5):
        out.append(
            f'<text class="tick" x="{sx(t):.1f}" y="{top + PANEL_H + 18}" text-anchor="middle">{t:g}</text>'
        )
    x = sx(XP01_THRESHOLD)
    out.append(f'<line class="rule" x1="{x:.1f}" x2="{x:.1f}" y1="{top}" y2="{top + PANEL_H}"/>')
    out.append(f'<text class="note" x="{x + 6:.1f}" y="{top + 12}">XP-01 threshold 2.0</text>')
    if key == "iou":
        pts = " ".join(f"{sx(p['threshold']):.1f},{sy(p['chance']):.1f}" for p in rows["combined"])
        out.append(f'<polyline class="chance" points="{pts}"/>')
    for name, *_ in SERIES:
        pts = " ".join(f"{sx(p['threshold']):.1f},{sy(p[key]):.1f}" for p in rows[name])
        out.append(f'<polyline class="s-{name}" points="{pts}"/>')


def render(rows) -> str:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" '
        f'height="{HEIGHT}" role="img" aria-labelledby="t d">',
        "<title id=\"t\">XP-02 highlight sensitivity, Plaskett</title>",
        "<desc id=\"d\">IoU with the WFIGS perimeter and highlighted area outside it against the "
        "threshold, window 3, for the combined, HH-only and HV-only indices. Values are in "
        "docs/methods/sensitivity.md and sensitivity.csv.</desc>",
        "<style>",
        "svg{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e4e3df;"
        + "".join(f"--{n}:{light};" for n, _, light, _ in SERIES)
        + "}",
        "@media (prefers-color-scheme: dark){svg{--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#3a3936;"
        + "".join(f"--{n}:{dark};" for n, _, _, dark in SERIES)
        + "}}",
        "text{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;fill:var(--ink2);font-size:12px}",
        ".head{fill:var(--ink);font-size:16px;font-weight:600}.title{fill:var(--ink);font-size:13px;font-weight:600}",
        ".label{fill:var(--ink);font-size:12px}.note{font-size:11px}",
        ".grid{stroke:var(--grid);stroke-width:1}.rule{stroke:var(--ink2);stroke-width:1;stroke-dasharray:2 3}",
        ".chance{fill:none;stroke:var(--ink2);stroke-width:1.5;stroke-dasharray:5 4}",
        "".join(
            f".s-{n}{{fill:none;stroke:var(--{n});stroke-width:2;stroke-linejoin:round}}" for n, *_ in SERIES
        ),
        "</style>",
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="var(--surface)"/>',
        f'<text class="head" x="{LEFT}" y="28">Highlight sensitivity (XP-02, window 3)</text>',
        f'<text x="{LEFT}" y="46">Agreement with the dated WFIGS perimeter, not accuracy. '
        "Highlighted change is not burned area.</text>",
    ]
    x = LEFT
    for name, label, *_ in SERIES:  # legend
        out.append(f'<line class="s-{name}" x1="{x}" x2="{x + 18}" y1="64" y2="64"/>')
        out.append(f'<text class="label" x="{x + 24}" y="68">{label}</text>')
        x += 24 + 7 * len(label) + 24
    out.append(f'<line class="chance" x1="{x}" x2="{x + 18}" y1="64" y2="64"/>')
    out.append(f'<text class="label" x="{x + 24}" y="68">Chance baseline (combined)</text>')
    iou_max = 0.5
    panel(out, rows, "iou", iou_max, (0, 0.1, 0.2, 0.3, 0.4, 0.5), TOP + 20,
          "IoU with the perimeter", lambda v: f"{v:.1f}")
    outside_max = 1400.0
    panel(out, rows, "outside", outside_max, (0, 350, 700, 1050, 1400), TOP + 20 + PANEL_H + PANEL_GAP,
          "Highlighted area outside the perimeter (ha)", lambda v: f"{v:,.0f}")
    out.append(
        f'<text class="tick" x="{(LEFT + WIDTH - RIGHT) / 2:.1f}" y="{HEIGHT - 12}" text-anchor="middle">'
        "Threshold (robust z-score of the smoothed index)</text>"
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    rows = load(Path(argv[1]))
    for points in rows.values():
        if max(p["iou"] for p in points) > 0.5 or max(p["outside"] for p in points) > 1400:
            raise SystemExit("values exceed the fixed axes; widen them")
    Path(argv[2]).write_text(render(rows), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
