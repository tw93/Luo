"""Measure local Luo refinement baselines.

Writes a compact JSON report comparing Luo v0.3, Luo v0.4.5, and the current
build against LXGW (and optionally a private kai reference set via
``LUO_PRIVATE_KAI_REF``), plus the homepage grouped-LXGW audit used for the
v0.4.8+ acceptance checks.

The private-reference column is silently skipped when ``LUO_PRIVATE_KAI_REF``
is unset or points to a missing file, mirroring the convention in
``compare_to.py`` and ``render_refinement_sheet.py``.

Output stays under ignored ``local/ref/metrics/``.

Run:
    python3 scripts/measure_refinement_baselines.py
    LUO_PRIVATE_KAI_REF=/path/to/private.ttf python3 scripts/measure_refinement_baselines.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from compare_to import DEFAULT_CHARS, SOURCE_FONT, compare_one_target  # noqa: E402
from measure_groups import DEFAULT_CHARS_FILE, load_chars, measure, summarise  # noqa: E402
from render_refinement_sheet import BASELINE_SPECS, CURRENT_LUO, PRIVATE_REF, _materialize_git_font  # noqa: E402


DEFAULT_OUTPUT = ROOT / "local" / "ref" / "metrics" / "v048_refinement_baselines.json"


def _relative_or_str(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _font_paths() -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    for label, (git_spec, out) in BASELINE_SPECS.items():
        try:
            paths.append((label, _materialize_git_font(git_spec, out)))
        except Exception as exc:  # local QA only; keep measuring what exists
            print(f"[baselines] skipped {label}: {exc}")
    paths.append(("Luo current", CURRENT_LUO))
    return [(label, path) for label, path in paths if path.exists()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raster-size", type=int, default=256)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    site_chars = load_chars(DEFAULT_CHARS_FILE)
    have_private = PRIVATE_REF is not None and PRIVATE_REF.exists()
    report = {
        "source": _relative_or_str(SOURCE_FONT),
        "private_ref": _relative_or_str(PRIVATE_REF) if have_private else None,
        "raster_size": args.raster_size,
        "baselines": [],
    }
    if not have_private:
        print("[baselines] LUO_PRIVATE_KAI_REF not set or missing; skipping private column")

    header = f"{'font':<13} {'lxgw30':>8}"
    if have_private:
        header += f" {'private30':>10}"
    header += f" {'site':>8} {'generic':>8}"
    print(header)
    print("-" * len(header))
    for label, path in _font_paths():
        luo_font = TTFont(str(path))
        lxgw = compare_one_target("lxgw", SOURCE_FONT, luo_font, DEFAULT_CHARS, args.raster_size, None)
        private = (
            compare_one_target("private", PRIVATE_REF, luo_font, DEFAULT_CHARS, args.raster_size, None)
            if have_private
            else None
        )
        grouped = summarise(measure(path, SOURCE_FONT, site_chars, args.raster_size)["rows"])

        row = {
            "label": label,
            "font": _relative_or_str(path),
            "lxgw_anchor_raw": lxgw["avg_raster_iou"] if lxgw else None,
            "lxgw_anchor_centered": lxgw["avg_bbox_centered_iou"] if lxgw else None,
            "private_anchor_raw": private["avg_raster_iou"] if private else None,
            "private_anchor_centered": private["avg_bbox_centered_iou"] if private else None,
            "site_lxgw_overall_raw": grouped["overall"]["avg_raw"],
            "site_lxgw_overall_centered": grouped["overall"]["avg_ctr"],
            "site_lxgw_generic_raw": grouped["per_bucket"]["generic"]["avg_raw"],
            "grouped_summary": grouped,
        }
        report["baselines"].append(row)
        line = f"{label:<13} {row['lxgw_anchor_raw']:>8.4f}"
        if have_private:
            line += f" {row['private_anchor_raw']:>10.4f}"
        line += (
            f" {row['site_lxgw_overall_raw']:>8.4f}"
            f" {row['site_lxgw_generic_raw']:>8.4f}"
        )
        print(line)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"[baselines] wrote {_relative_or_str(args.output)}")


if __name__ == "__main__":
    main()
