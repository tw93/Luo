"""
Compare Luo against a reference font on a set of anchor glyphs.

For each anchor character we render the Luo glyph and the reference glyph at
the same em-box size and compute two intersection-over-union metrics:

  - raster_iou           : pixel overlap as-is (penalises whole-glyph shifts)
  - bbox_centered_iou    : pixel overlap after translating both glyphs so
                           their bounding boxes share a centroid (isolates
                           structural / shape divergence from translation)

Reference targets:

  --target source   compare to the LXGW WenKai source font (must stay LOW —
                    the v0.4 design pivot wants Luo to read as its own
                    typeface, not LXGW with extra weight).
  --target private  compare to a private typographic-kai reference font set
                    via LUO_PRIVATE_KAI_REF. The intent is "shares the
                    commercial print-kai gesture, but does not copy outlines",
                    so this number should sit in the 0.50-0.60 band.
  --target both     run source plus private when LUO_PRIVATE_KAI_REF is set.
                    Source reports stay in proof/; private reports stay in
                    ignored local/ref/ outputs. This is the default.

Contours are rasterised with the even-odd rule so counters in 国/回/日/目
read as actual holes, not over-filled solid blocks.

Public output JSON:
  proof/similarity_lxgw.json

Private reference JSON and PNG side-by-side products live under ignored
local/ref/ and are never needed for public CI or deploys.

By default the script writes the report and exits 0 even when the gate is not
met, so contributors can iterate without the build going red on every run.
Pass --strict (or set LUO_SIMILARITY_STRICT=1) to make a failing verdict
exit non-zero — wire that into CI once the surrounding v0.4 work brings the
means under target.

Run:
    python scripts/compare_to.py
    python scripts/compare_to.py --target source
    LUO_PRIVATE_KAI_REF=/path/to/private.ttf python scripts/compare_to.py --target private --raster-size 512
    python scripts/compare_to.py --chars 落文心国回 --no-images
    python scripts/compare_to.py --strict      # CI / release gate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FONT = ROOT / "source" / "LXGWWenKaiScreen-Regular.ttf"
LUO_FONT = ROOT / "dist" / "Luo-Regular.ttf"
PROOF_DIR = ROOT / "proof"
LOCAL_REF_DIR = ROOT / "local" / "ref"
PRIVATE_REPORT_DIR = LOCAL_REF_DIR / "metrics"
PRIVATE_IMAGE_DIR = LOCAL_REF_DIR / "renders"
DEFAULT_SOURCE_IMAGE_DIR = PROOF_DIR / "similarity_images"

PRIVATE_REF_FONT = (
    Path(value) if (value := os.environ.get("LUO_PRIVATE_KAI_REF")) else None
)

DEFAULT_CHARS = "落文字书心清骨风纸印国回月雨霜藏魔赢道远家亭序集章兰永天玄黄"

# v0.4 dual-gate targets. Both are aggregate (mean over the anchor set);
# per-glyph variance is normal.
LXGW_TARGET_MAX = 0.55          # Luo should drift OFF LXGW (v0.3 was 0.758)
PRIVATE_TARGET_MIN = 0.50       # not too far below means "shares gesture"
PRIVATE_TARGET_MAX = 0.60       # not too far above means "does not copy outlines"

# Per-glyph upper-bound gates kept for backwards compatibility (used in the
# `pass` field on each result entry).
TARGET_REGULAR = 0.60
TARGET_SIMPLE = 0.75
SIMPLE_CHARS = set("一二三十中木日大小上下口工人入八")

REPORT_PATHS = {
    "source":  PROOF_DIR / "similarity_lxgw.json",
    "private": PRIVATE_REPORT_DIR / "similarity_private.json",
    "both":    PRIVATE_REPORT_DIR / "similarity_private_dual.json",
}


@dataclass
class GlyphRender:
    mask: object  # PIL.Image (binary)
    bbox: tuple[int, int, int, int] | None  # in mask-pixel coords


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Luo to a reference font on anchor glyphs."
    )
    parser.add_argument(
        "--target",
        choices=("source", "private", "both"),
        default="both",
        help=(
            "Which reference font to compare against. 'source' = LXGW base, "
            "'private' = local private typographic-kai reference, "
            "'both' = source plus private when configured (default)."
        ),
    )
    parser.add_argument("--source", type=Path, default=SOURCE_FONT)
    parser.add_argument(
        "--private",
        type=Path,
        default=PRIVATE_REF_FONT,
        help=(
            "Private reference font path. Defaults to LUO_PRIVATE_KAI_REF; "
            "when unset, the private branch is skipped."
        ),
    )
    parser.add_argument("--luo", type=Path, default=LUO_FONT)
    parser.add_argument(
        "--chars",
        type=str,
        default=DEFAULT_CHARS,
        help="Characters to compare. Defaults to the core_anchors group.",
    )
    parser.add_argument(
        "--raster-size",
        type=int,
        default=256,
        help="Square raster size in pixels (default 256).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Override report output path. By default the script picks "
            "proof/similarity_lxgw.json for source and local/ref/metrics/ "
            "for private reports."
        ),
    )
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=DEFAULT_SOURCE_IMAGE_DIR,
        help="Where to save public source side-by-side PNGs. Pass --no-images to skip.",
    )
    parser.add_argument(
        "--private-image-dir",
        type=Path,
        default=PRIVATE_IMAGE_DIR,
        help="Where to save private reference PNGs; must stay under local/ref/.",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Skip saving per-glyph comparison PNGs.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=os.environ.get("LUO_SIMILARITY_STRICT") == "1",
        help=(
            "Exit non-zero if the verdict fails. The default is advisory "
            "(always exits 0); use --strict in CI / release gates."
        ),
    )
    return parser.parse_args()


def _flatten_quadratic(start, control, end, depth: int = 4) -> list[tuple[float, float]]:
    """Adaptive subdivision of a quadratic Bezier into a polyline."""
    if depth <= 0:
        return [end]
    mid_a = ((start[0] + control[0]) / 2.0, (start[1] + control[1]) / 2.0)
    mid_b = ((control[0] + end[0]) / 2.0, (control[1] + end[1]) / 2.0)
    mid_ab = ((mid_a[0] + mid_b[0]) / 2.0, (mid_a[1] + mid_b[1]) / 2.0)
    return (
        _flatten_quadratic(start, mid_a, mid_ab, depth - 1)
        + _flatten_quadratic(mid_ab, mid_b, end, depth - 1)
    )


def _flatten_cubic(start, c1, c2, end, depth: int = 4) -> list[tuple[float, float]]:
    if depth <= 0:
        return [end]
    m01 = ((start[0] + c1[0]) / 2.0, (start[1] + c1[1]) / 2.0)
    m12 = ((c1[0] + c2[0]) / 2.0, (c1[1] + c2[1]) / 2.0)
    m23 = ((c2[0] + end[0]) / 2.0, (c2[1] + end[1]) / 2.0)
    m012 = ((m01[0] + m12[0]) / 2.0, (m01[1] + m12[1]) / 2.0)
    m123 = ((m12[0] + m23[0]) / 2.0, (m12[1] + m23[1]) / 2.0)
    m = ((m012[0] + m123[0]) / 2.0, (m012[1] + m123[1]) / 2.0)
    return (
        _flatten_cubic(start, m01, m012, m, depth - 1)
        + _flatten_cubic(m, m123, m23, end, depth - 1)
    )


def _midpoint(a, b) -> tuple[float, float]:
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def glyph_polylines(font: TTFont, glyph_name: str) -> list[list[tuple[float, float]]]:
    """Return one closed polyline per contour for the named glyph."""
    glyph_set = font.getGlyphSet()
    pen = RecordingPen()
    glyph_set[glyph_name].draw(pen)

    polys: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    cursor: tuple[float, float] | None = None
    for op, args in pen.value:
        if op == "moveTo":
            if current:
                polys.append(current)
            current = [args[0]]
            cursor = args[0]
        elif op == "lineTo":
            current.append(args[0])
            cursor = args[0]
        elif op == "qCurveTo":
            if args and args[-1] is None:
                controls = list(args[:-1])
                if not controls:
                    continue
                start = current[0] if current else _midpoint(controls[-1], controls[0])
                if cursor is None:
                    current = [start]
                    cursor = start
                for i, ctrl in enumerate(controls):
                    if i + 1 < len(controls):
                        next_on = _midpoint(ctrl, controls[i + 1])
                    else:
                        next_on = start
                    current.extend(_flatten_quadratic(cursor, ctrl, next_on))
                    cursor = next_on
                continue
            controls = list(args[:-1])
            on_end = args[-1]
            for i, ctrl in enumerate(controls):
                if i + 1 < len(controls):
                    next_on = _midpoint(ctrl, controls[i + 1])
                else:
                    next_on = on_end
                current.extend(_flatten_quadratic(cursor, ctrl, next_on))
                cursor = next_on
        elif op == "curveTo":
            for i in range(0, len(args), 3):
                c1 = args[i]
                c2 = args[i + 1]
                end = args[i + 2]
                current.extend(_flatten_cubic(cursor, c1, c2, end))
                cursor = end
        elif op == "closePath":
            if current and current[0] != current[-1]:
                current.append(current[0])
            polys.append(current)
            current = []
            cursor = None
        elif op == "endPath":
            if current:
                polys.append(current)
                current = []
                cursor = None
    if current:
        polys.append(current)
    return polys


def render_glyph(
    font: TTFont, char: str, raster_size: int
) -> GlyphRender | None:
    from PIL import Image, ImageDraw, ImageChops

    cmap = font.getBestCmap() or {}
    gname = cmap.get(ord(char))
    if not gname:
        return None
    upm = font["head"].unitsPerEm
    polys = glyph_polylines(font, gname)
    if not polys:
        return None

    margin = 0.05
    drawable = raster_size * (1.0 - 2 * margin)
    scale = drawable / upm
    offset = raster_size * margin

    # Even-odd rule via XOR-fold: counters in 国/回/日/目 read as actual
    # holes. Simple polygon fill would over-credit similarity exactly where
    # Luo deliberately diverges from a reference's counter shape.
    accum = Image.new("1", (raster_size, raster_size), 0)
    for poly in polys:
        if len(poly) < 3:
            continue
        flipped = [
            (
                offset + p[0] * scale,
                raster_size - offset - p[1] * scale,
            )
            for p in poly
        ]
        layer = Image.new("1", (raster_size, raster_size), 0)
        ImageDraw.Draw(layer).polygon(flipped, fill=1)
        accum = ImageChops.logical_xor(accum, layer)
    img = accum.convert("L").point(lambda v: 255 if v else 0)
    bbox = img.getbbox()
    return GlyphRender(mask=img, bbox=bbox)


def iou(mask_a, mask_b) -> float:
    from PIL import ImageChops

    bin_a = mask_a.point(lambda v: 255 if v else 0, "1")
    bin_b = mask_b.point(lambda v: 255 if v else 0, "1")
    inter = ImageChops.logical_and(bin_a, bin_b)
    union = ImageChops.logical_or(bin_a, bin_b)
    inter_count = sum(inter.convert("L").tobytes())
    union_count = sum(union.convert("L").tobytes())
    if union_count == 0:
        return 0.0
    return inter_count / union_count


def center_mask(mask, bbox, raster_size: int):
    from PIL import Image

    if bbox is None:
        return mask
    bx0, by0, bx1, by1 = bbox
    target_x = (raster_size - (bx1 - bx0)) // 2
    target_y = (raster_size - (by1 - by0)) // 2
    canvas = Image.new("L", (raster_size, raster_size), 0)
    canvas.paste(mask.crop(bbox), (target_x, target_y))
    return canvas


def gate_for(char: str) -> float:
    return TARGET_SIMPLE if char in SIMPLE_CHARS else TARGET_REGULAR


def _relative_or_str(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _is_under(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def ensure_private_output(path: Path, kind: str) -> None:
    if not _is_under(path, LOCAL_REF_DIR):
        sys.exit(f"[compare] private {kind} must be written under local/ref/")


def compare_one_target(
    target_label: str,
    ref_path: Path | None,
    luo_font: TTFont,
    chars: str,
    raster_size: int,
    image_dir: Path | None,
) -> dict | None:
    """Run the IoU comparison against a single reference font.

    Returns the summary dict (same shape as the v0.3 single-target report) or
    None when the reference file is missing. Private reference fonts are local
    opt-ins, so missing private input degrades gracefully.
    """
    if ref_path is None:
        print("[compare] private reference not configured; skipping private branch")
        return None
    if not ref_path.exists():
        if target_label == "private":
            print(
                "[compare] private reference font missing; "
                "check LUO_PRIVATE_KAI_REF\n"
                "[compare] skipping private branch"
            )
        else:
            print(
                f"[compare] {target_label} reference font missing: {ref_path}\n"
                f"[compare] skipping {target_label} branch"
            )
        return None

    ref_font = TTFont(str(ref_path))

    results = []
    skipped = []
    for char in chars:
        ref = render_glyph(ref_font, char, raster_size)
        luo = render_glyph(luo_font, char, raster_size)
        if ref is None or luo is None:
            skipped.append(char)
            continue

        raw_iou = iou(ref.mask, luo.mask)
        ref_centered = center_mask(ref.mask, ref.bbox, raster_size)
        luo_centered = center_mask(luo.mask, luo.bbox, raster_size)
        centered_iou = iou(ref_centered, luo_centered)

        gate = gate_for(char)
        passes = raw_iou <= gate and centered_iou <= gate

        results.append(
            {
                "char": char,
                "codepoint": f"U+{ord(char):04X}",
                "raster_iou": round(raw_iou, 4),
                "bbox_centered_iou": round(centered_iou, 4),
                "gate": gate,
                "pass": passes,
            }
        )

        if image_dir is not None:
            from PIL import Image, ImageDraw

            side = Image.new(
                "RGB",
                (raster_size * 2 + 8, raster_size + 24),
                "white",
            )
            side.paste(ref.mask.convert("RGB"), (0, 24))
            side.paste(luo.mask.convert("RGB"), (raster_size + 8, 24))
            d = ImageDraw.Draw(side)
            d.text((4, 4), f"{char} {target_label}", fill="black")
            d.text(
                (raster_size + 12, 4),
                f"{char} luo  raw={raw_iou:.2f} ctr={centered_iou:.2f}",
                fill="black",
            )
            side.save(image_dir / f"{target_label}_{ord(char):04X}_{char}.png")

    if not results:
        return None

    avg_raw = sum(r["raster_iou"] for r in results) / len(results)
    avg_ctr = sum(r["bbox_centered_iou"] for r in results) / len(results)
    fails = [r["char"] for r in results if not r["pass"]]

    return {
        "target": target_label,
        "reference": "private" if target_label == "private" else _relative_or_str(ref_path),
        "private_reference_present": target_label == "private",
        "luo": "dist/Luo-Regular.ttf",
        "raster_size": raster_size,
        "char_count": len(results),
        "skipped": skipped,
        "avg_raster_iou": round(avg_raw, 4),
        "avg_bbox_centered_iou": round(avg_ctr, 4),
        "regular_gate": TARGET_REGULAR,
        "simple_gate": TARGET_SIMPLE,
        "above_gate": fails,
        "results": results,
    }


def write_report(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        sys.exit(
            "[compare] Pillow is required for raster IoU. Install with:\n"
            "    pip install Pillow"
        )

    if not args.luo.exists():
        sys.exit(
            f"[compare] Luo font missing: {args.luo}\n"
            "        Run: python scripts/build.py"
        )

    luo_font = TTFont(str(args.luo))

    source_image_dir = None if args.no_images else args.image_dir
    private_image_dir = None if args.no_images else args.private_image_dir
    if private_image_dir is not None:
        ensure_private_output(private_image_dir, "images")

    if args.target != "source" and args.report is not None:
        ensure_private_output(args.report, "report")

    targets = ("source", "private") if args.target == "both" else (args.target,)

    branch_summaries: dict[str, dict] = {}
    for tgt in targets:
        ref_path = args.source if tgt == "source" else args.private
        label = "lxgw" if tgt == "source" else "private"
        image_dir = source_image_dir if tgt == "source" else private_image_dir
        if image_dir is not None:
            image_dir.mkdir(parents=True, exist_ok=True)
        summary = compare_one_target(
            label, ref_path, luo_font, args.chars, args.raster_size, image_dir
        )
        if summary is None:
            continue
        branch_summaries[tgt] = summary
        single_path = args.report if (
            args.report and args.target == tgt
        ) else REPORT_PATHS[tgt]
        write_report(summary, single_path)
        print(
            f"[compare] {label}: {summary['char_count']} glyphs | "
            f"raw mean={summary['avg_raster_iou']:.3f} "
            f"centered mean={summary['avg_bbox_centered_iou']:.3f} | "
            f"above-gate={len(summary['above_gate'])} | "
            f"wrote {_relative_or_str(single_path)}"
        )

    if not branch_summaries and args.target == "private":
        print("[compare] private branch skipped; no report produced")
        return
    if not branch_summaries:
        sys.exit("[compare] no targets produced a report (missing fonts?)")

    fail_messages: list[str] = []

    if args.target == "both":
        lxgw = branch_summaries.get("source")
        private = branch_summaries.get("private")
        verdict = {
            "lxgw_below_max": (
                lxgw["avg_raster_iou"] <= LXGW_TARGET_MAX
                if lxgw else None
            ),
            "private_in_target_band": (
                PRIVATE_TARGET_MIN <= private["avg_raster_iou"] <= PRIVATE_TARGET_MAX
                if private else None
            ),
            "lxgw_target_max": LXGW_TARGET_MAX,
            "private_target_min": PRIVATE_TARGET_MIN,
            "private_target_max": PRIVATE_TARGET_MAX,
        }
        dual = {
            "luo_vs_lxgw": lxgw,
            "luo_vs_private": private,
            "verdict": verdict,
        }
        dual_path = args.report or REPORT_PATHS["both"]
        ensure_private_output(dual_path, "report")
        write_report(dual, dual_path)
        print(
            f"[compare] dual verdict: lxgw_below_{LXGW_TARGET_MAX}="
            f"{verdict['lxgw_below_max']} "
            f"private_in_[{PRIVATE_TARGET_MIN},{PRIVATE_TARGET_MAX}]="
            f"{verdict['private_in_target_band']} | "
            f"wrote {_relative_or_str(dual_path)}"
        )
        if verdict["lxgw_below_max"] is False:
            fail_messages.append(
                f"Luo↔LXGW {lxgw['avg_raster_iou']:.3f} > {LXGW_TARGET_MAX} (still too close to source)"
            )
        if verdict["private_in_target_band"] is False:
            fail_messages.append(
                f"Luo↔private reference {private['avg_raster_iou']:.3f} outside "
                f"[{PRIVATE_TARGET_MIN},{PRIVATE_TARGET_MAX}]"
            )
    else:
        # Single-target mode keeps v0.3 behaviour: any per-glyph failure is
        # advisory, but in --strict mode we exit non-zero on any fail so the
        # script remains usable as a tight gate without --target both.
        for tgt, summary in branch_summaries.items():
            if summary["above_gate"]:
                fail_messages.append(
                    f"{tgt}: {len(summary['above_gate'])}/{summary['char_count']} "
                    f"above gate ({''.join(summary['above_gate'])})"
                )

    if image_dir is not None:
        print(f"[compare] side-by-side images -> {_relative_or_str(image_dir)}/")

    if fail_messages:
        msg = "\n".join("[compare] " + m for m in fail_messages)
        if args.strict:
            print(msg, file=sys.stderr)
            sys.exit(1)
        print(msg)


if __name__ == "__main__":
    main()
