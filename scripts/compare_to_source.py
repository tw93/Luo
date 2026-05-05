"""
Compare Luo against the LXGW WenKai source font on a set of anchor glyphs.

For each anchor character we render the Luo glyph and the source glyph at the
same em-box size and compute two intersection-over-union metrics:

  - raster_iou           : pixel overlap as-is (penalises whole-glyph shifts)
  - bbox_centered_iou    : pixel overlap after translating both glyphs so
                           their bounding boxes share a centroid (isolates
                           structural / shape divergence from translation)

Contours are rasterised with the even-odd rule so counters in 国/回/日/目
read as actual holes, not over-filled solid blocks. Without that rule the
metric would over-credit similarity exactly where Luo deliberately diverges.

The default character set is the `core_anchors` priority group from
scripts/build.py (kept in sync with STYLE.md). Output is a small JSON
report at proof/similarity_report.json that is safe to commit; PNG / HTML
side-by-side products live in proof/similarity_images/ and are gitignored.

By default the script writes the report and exits 0 even when glyphs are
above the gate, so contributors can iterate without the build going red on
every run. Pass --strict (or set LUO_SIMILARITY_STRICT=1) to make any glyph
above its IoU gate exit non-zero — wire that into CI once the surrounding
v0.4 work brings the means under target.

Run:
    python scripts/compare_to_source.py
    python scripts/compare_to_source.py --chars 落文心国回
    python scripts/compare_to_source.py --raster-size 512 --no-images
    python scripts/compare_to_source.py --strict      # CI / release gate
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
DEFAULT_REPORT = PROOF_DIR / "similarity_report.json"
DEFAULT_IMAGE_DIR = PROOF_DIR / "similarity_images"

DEFAULT_CHARS = "落文字书心清骨风纸印国回月雨霜藏魔赢道远家亭序集章兰永天玄黄"

# IoU gates from STYLE.md / HANDOFF.md: upper bounds, lower similarity is better
TARGET_REGULAR = 0.60
TARGET_SIMPLE = 0.75
SIMPLE_CHARS = set("一二三十中木日大小上下口工人入八")


@dataclass
class GlyphRender:
    mask: object  # PIL.Image (binary)
    bbox: tuple[int, int, int, int] | None  # in mask-pixel coords


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Luo to its source font on anchor glyphs."
    )
    parser.add_argument("--source", type=Path, default=SOURCE_FONT)
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
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=DEFAULT_IMAGE_DIR,
        help="Where to save side-by-side PNGs. Pass --no-images to skip.",
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
            "Exit non-zero if any glyph is above its IoU gate. The default is "
            "advisory (always exits 0); use --strict in CI / release gates."
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
            # Draw chained off-curve points as a series of quadratics through
            # implicit on-curve midpoints, with the final on-curve as args[-1].
            controls = list(args[:-1])
            on_end = args[-1]
            for i, ctrl in enumerate(controls):
                if i + 1 < len(controls):
                    next_on = (
                        (ctrl[0] + controls[i + 1][0]) / 2.0,
                        (ctrl[1] + controls[i + 1][1]) / 2.0,
                    )
                else:
                    next_on = on_end
                current.extend(_flatten_quadratic(cursor, ctrl, next_on))
                cursor = next_on
        elif op == "curveTo":
            # Cubic chain: triples of (c1, c2, on)
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

    margin = 0.05  # 5% breathing room
    drawable = raster_size * (1.0 - 2 * margin)
    scale = drawable / upm
    offset = raster_size * margin

    # Even-odd rule: each contour toggles inside/outside. Drawing every
    # contour into its own 1-bit mask and XOR-folding them together makes
    # counters in 国/回/日/目 read as actual holes. Required for an honest
    # IoU because Luo deliberately changes counter shape vs the source —
    # over-filling them would silently hide that difference.
    accum = Image.new("1", (raster_size, raster_size), 0)
    for poly in polys:
        if len(poly) < 3:
            continue
        flipped = [
            (
                offset + p[0] * scale,
                # Flip Y so glyph baseline is near bottom of the image.
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


def main() -> None:
    args = parse_args()

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        sys.exit(
            "[compare] Pillow is required for raster IoU. Install with:\n"
            "    pip install Pillow"
        )

    if not args.source.exists():
        sys.exit(
            f"[compare] source font missing: {args.source}\n"
            "        Run: python scripts/fetch_base_font.py"
        )
    if not args.luo.exists():
        sys.exit(
            f"[compare] Luo font missing: {args.luo}\n"
            "        Run: python scripts/build.py"
        )

    source_font = TTFont(str(args.source))
    luo_font = TTFont(str(args.luo))

    image_dir = None if args.no_images else args.image_dir
    if image_dir is not None:
        image_dir.mkdir(parents=True, exist_ok=True)

    results = []
    skipped = []
    for char in args.chars:
        src = render_glyph(source_font, char, args.raster_size)
        luo = render_glyph(luo_font, char, args.raster_size)
        if src is None or luo is None:
            skipped.append(char)
            continue

        raw_iou = iou(src.mask, luo.mask)
        src_centered = center_mask(src.mask, src.bbox, args.raster_size)
        luo_centered = center_mask(luo.mask, luo.bbox, args.raster_size)
        centered_iou = iou(src_centered, luo_centered)

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
            from PIL import ImageFont  # noqa: F401

            side = Image.new(
                "RGB",
                (args.raster_size * 2 + 8, args.raster_size + 24),
                "white",
            )
            side.paste(src.mask.convert("RGB"), (0, 24))
            side.paste(luo.mask.convert("RGB"), (args.raster_size + 8, 24))
            d = ImageDraw.Draw(side)
            d.text((4, 4), f"{char} src", fill="black")
            d.text((args.raster_size + 12, 4),
                   f"{char} luo  raw={raw_iou:.2f} ctr={centered_iou:.2f}",
                   fill="black")
            side.save(image_dir / f"{ord(char):04X}_{char}.png")

    if not results:
        sys.exit("[compare] no glyphs compared (none of the chars had outlines)")

    avg_raw = sum(r["raster_iou"] for r in results) / len(results)
    avg_ctr = sum(r["bbox_centered_iou"] for r in results) / len(results)
    fails = [r["char"] for r in results if not r["pass"]]

    summary = {
        "source": str(args.source.relative_to(ROOT)),
        "luo": str(args.luo.relative_to(ROOT)),
        "raster_size": args.raster_size,
        "char_count": len(results),
        "skipped": skipped,
        "avg_raster_iou": round(avg_raw, 4),
        "avg_bbox_centered_iou": round(avg_ctr, 4),
        "regular_gate": TARGET_REGULAR,
        "simple_gate": TARGET_SIMPLE,
        "above_gate": fails,
        "results": results,
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[compare] {len(results)} glyphs | "
        f"raw mean={avg_raw:.3f} centered mean={avg_ctr:.3f} | "
        f"above-gate={len(fails)} | wrote {args.report.relative_to(ROOT)}"
    )
    if image_dir is not None:
        print(f"[compare] side-by-side images -> {image_dir.relative_to(ROOT)}/")
    if fails:
        msg = (
            f"[compare] still too close to source ({len(fails)}/{len(results)}): "
            f"{''.join(fails)}"
        )
        if args.strict:
            print(msg, file=sys.stderr)
            sys.exit(1)
        print(msg)


if __name__ == "__main__":
    main()
