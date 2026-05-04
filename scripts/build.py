"""
Luo font builder.

Pipeline:
  1. Load the source TTF.
  2. Subset to starter/site/seed or explicit GB2312 expansion characters.
  3. Graduated stroke thickening (横细竖重, contour-scaled).
  4. Endpoint softening (硬切 -> 软切).
  5. Complexity-aware horizontal narrowing + vertical scaling.
  6. Component-aware refinement (7 categories).
  7. Heart-character reshape (心字底/旁).
  8. Dot contour direction (xiaokai dot rotation + compression).
  9. Targeted turn refinement (priority frames/endpoints/multi-horiz).
 10. Dense dot-cluster protection (墨).
 11. Hook refinement on whitelist (refine_hooks_final).
 12. Walk-radical final containment (透/道/遇/述/远).
 13. CJK punctuation + space + spacing.
 14. Rewrite name table -> Luo.
 15. Write Luo-Regular.otf/.ttf/.woff2 into dist/.

Target glyph parameters:
  字宽: regular 94-98%, complex 92-95%, simple 96-100%
  字面率: +4% to +7%
  笔画: Regular~Medium, 横略细竖略重
  中宫: 微紧, complex不挤 simple不散
  横画: 上扬1-2°, 收笔略重
  竖画: 基本垂直, 起收有轻微重量
  转折: 外圆内锐, 转折处略加重
  端点: 软切角, 起笔顿挫收笔稳

Run:
    python scripts/build.py
"""

from __future__ import annotations

import math
import os
import re
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "source"
DIST_DIR = ROOT / "dist"
PROOF_DIR = ROOT / "proof"

BASE_FONT = Path(
    os.environ.get(
        "LUO_BASE_FONT",
        str(SOURCE_DIR / "LXGWWenKaiScreen-Regular.ttf"),
    )
)

# --- Narrowing ---
# Complexity-aware: complex chars narrower, simple chars wider.
# Complexity is estimated by contour count as a proxy for stroke count.
NARROW_SIMPLE = float(os.environ.get("LUO_NARROW_SIMPLE", "1.000"))   # 简字不收，大方舒展
NARROW_REGULAR = float(os.environ.get("LUO_NARROW_REGULAR", "0.975")) # 常规字轻收，保持端正
NARROW_COMPLEX = float(os.environ.get("LUO_NARROW_COMPLEX", "0.950")) # 复杂字适度收，不挤不糊
# Legacy single-value override; if set, disables complexity split.
NARROW_X = os.environ.get("LUO_NARROW_X")

# Contour thresholds for classifying CJK glyph complexity.
COMPLEXITY_SIMPLE_MAX = int(os.environ.get("LUO_COMPLEXITY_SIMPLE", "3"))
COMPLEXITY_COMPLEX_MIN = int(os.environ.get("LUO_COMPLEXITY_COMPLEX", "8"))

# --- Vertical scaling ---
SCALE_Y = float(os.environ.get("LUO_SCALE_Y", "1.00"))

# --- Punctuation ---
# Contemporary print-style proportional CJK punctuation: keep the marks compact
# instead of leaving fullwidth punctuation gaps in running text.
PUNCT_WIDTH_RATIO = float(os.environ.get("LUO_PUNCT_WIDTH", "0.75"))

# --- Boldening ---
# Direction-aware: horizontal strokes get less delta, vertical strokes more,
# producing the 横细竖重 feel without uniform fattening.
BOLDEN_H = float(os.environ.get("LUO_BOLDEN_H", "6"))   # 横画恢复分量，多骨
BOLDEN_V = float(os.environ.get("LUO_BOLDEN_V", "14"))  # 竖画稳重，主笔有分量
# Diagonal bonus: linear interpolation gives 撇/捺 about 10.5 at 45° — visually
# too thin next to 15-unit verticals. Add a parabolic bonus that peaks at
# horiz_ratio=0.5 so 撇/捺 carry more weight without disturbing pure
# horizontals/verticals.
BOLDEN_DIAG_BONUS = float(os.environ.get("LUO_BOLDEN_DIAG", "9.0"))
# Legacy single-value override.
BOLDEN_DELTA = os.environ.get("LUO_BOLDEN")
# Graduated boldening: reduce delta as contour count rises.
BOLDEN_GRAD_STEP = float(os.environ.get("LUO_BOLDEN_GRAD_STEP", "0.06"))
BOLDEN_GRAD_FLOOR = float(os.environ.get("LUO_BOLDEN_GRAD_FLOOR", "0.85"))
BOLDEN_GRAD_ONSET = int(os.environ.get("LUO_BOLDEN_GRAD_ONSET", "3"))

# Endpoint softening (软切角): round sharp corners after boldening.
SOFTEN_ANGLE = float(os.environ.get("LUO_SOFTEN_ANGLE", "120"))
SOFTEN_BLEND = float(os.environ.get("LUO_SOFTEN_BLEND", "0.05"))
SOFTEN_SEG_MAX = float(os.environ.get("LUO_SOFTEN_SEG_MAX", "80"))
# Endpoint subtypes keep one Luo temperament without stamping every terminal
# with the same soft-cut geometry.
ENDPOINT_H_BLEND = float(os.environ.get("LUO_ENDPOINT_H_BLEND", "0.040"))
ENDPOINT_V_BOTTOM_BLEND = float(os.environ.get("LUO_ENDPOINT_V_BOTTOM_BLEND", "0.045"))
ENDPOINT_DIAG_BLEND = float(os.environ.get("LUO_ENDPOINT_DIAG_BLEND", "0.030"))

# Space width: half-width space for tighter CJK typesetting.
SPACE_WIDTH_RATIO = float(os.environ.get("LUO_SPACE_WIDTH", "0.50"))

# Hook refinement (钩画): thinner root, shorter body, lighter tip.
HOOK_ROOT_THIN = float(os.environ.get("LUO_HOOK_ROOT_THIN", "0.09"))
HOOK_SHORTEN = float(os.environ.get("LUO_HOOK_SHORTEN", "0.14"))
# Negative = end point extends outward. v0.1 used -0.02 because refine_hooks
# also fires on stroke ends (撇尾/捺尾) that geometrically look like hooks;
# extending outward keeps those ends natural. Positive values create a
# "bird-beak" curl on every 撇尾/捺尾.
HOOK_TIP_TAPER = float(os.environ.get("LUO_HOOK_TIP_TAPER", "-0.02"))

# CJK spacing: keep 1em advances by default for predictable reading text.
SPACING_BASE = float(os.environ.get("LUO_SPACING_BASE", "1.00"))
SPACING_STEP = float(os.environ.get("LUO_SPACING_STEP", "0.000"))
SPACING_ONSET = int(os.environ.get("LUO_SPACING_ONSET", "3"))
SPACING_CAP = float(os.environ.get("LUO_SPACING_CAP", "1.00"))

# --- Dot contour refinement (Pass A) ---
DOT_AREA_PCT = float(os.environ.get("LUO_DOT_AREA_PCT", "5.0"))
DOT_MAX_POINTS = int(os.environ.get("LUO_DOT_MAX_POINTS", "20"))
# Directional shaping: less compression along the long axis (keep length),
# more compression along the short axis (carve out width). Together with the
# rotation, this gives xiaokai dots a wedge feel rather than a round droplet.
DOT_LONG_AXIS = float(os.environ.get("LUO_DOT_LONG_AXIS", "0.92"))
DOT_LONG_AXIS_SOFT = float(os.environ.get("LUO_DOT_LONG_AXIS_SOFT", "1.00"))
DOT_SHORT_AXIS = float(os.environ.get("LUO_DOT_SHORT_AXIS", "0.55"))
DOT_ROTATE_DEG = float(os.environ.get("LUO_DOT_ROTATE_DEG", "14.0"))
# Adaptive carve: as source aspect rises toward the gate, lerp short-axis factor
# toward 1.0 so elongated dots (岭/信/令 style) are not over-carved into slashes.
DOT_RELAX_PIVOT = float(os.environ.get("LUO_DOT_RELAX_PIVOT", "1.0"))
DOT_RELAX_GATE  = float(os.environ.get("LUO_DOT_RELAX_GATE",  "1.8"))
# Dot-aware bolden cap: stop small dot-like contours from gaining very
# different horizontal expansion in dense vs open glyph contexts.
DOT_BOLDEN_X_CAP_FACTOR = float(os.environ.get("LUO_DOT_BOLDEN_X_CAP_FACTOR", "1.15"))
DOT_BOLDEN_ASPECT_GATE = 2.2

# --- Second hook pass (Pass B) ---
HOOK_FINAL_SHORTEN = float(os.environ.get("LUO_HOOK_FINAL_SHORTEN", "0.14"))
HOOK_FINAL_TIP_SHARPEN = float(os.environ.get("LUO_HOOK_FINAL_TIP_SHARPEN", "0.18"))
HOOK_FINAL_TAIL_CONTAIN = float(os.environ.get("LUO_HOOK_FINAL_TAIL_CONTAIN", "0.06"))

# --- Targeted turn refinement (Pass C, whitelist only) ---
TURN_FINAL_ANGLE_MAX = 105.0
TURN_FINAL_DISPLACE = float(os.environ.get("LUO_TURN_FINAL_DISPLACE", "1.2"))
TURN_FINAL_INNER = float(os.environ.get("LUO_TURN_FINAL_INNER", "0.96"))
TURN_FINAL_SEG_MIN = 15.0
TURN_FINAL_SEG_MAX = 90.0
TURN_FINAL_FRAME_DISPLACE = float(os.environ.get("LUO_TURN_FINAL_FRAME_DISPLACE", "1.6"))
TURN_FINAL_FRAME_INNER = float(os.environ.get("LUO_TURN_FINAL_FRAME_INNER", "0.955"))
TURN_FINAL_FRAME_SEG_MAX = float(os.environ.get("LUO_TURN_FINAL_FRAME_SEG_MAX", "140"))

# --- Bone turn refinement (Pass C) ---
BONE_TURN_ANGLE_MAX = float(os.environ.get("LUO_BONE_TURN_ANGLE_MAX", "120"))
BONE_TURN_SEG_MIN = float(os.environ.get("LUO_BONE_TURN_SEG_MIN", "15"))
BONE_TURN_SEG_MAX = float(os.environ.get("LUO_BONE_TURN_SEG_MAX", "80"))
BONE_TURN_DISPLACE = float(os.environ.get("LUO_BONE_TURN_DISPLACE", "2.6"))
BONE_TURN_INNER_REDUCE = float(os.environ.get("LUO_BONE_TURN_INNER_REDUCE", "0.90"))

# --- Stroke taper refinement (Pass D) ---
TAPER_ARC_PCT = float(os.environ.get("LUO_TAPER_ARC_PCT", "0.15"))
TAPER_INWARD = float(os.environ.get("LUO_TAPER_INWARD", "0.055"))
TAPER_MIN_CONTOUR_PTS = int(os.environ.get("LUO_TAPER_MIN_CONTOUR_PTS", "24"))

# --- Heart character refinement (Pass E) ---
# LXGW 心 strokes already have direction (-35°/-57°/+62° for the four dots);
# Contemporary kaishu-inspired print fonts keep a similar directional logic.
# Don't re-shape these dots with aggressive long/short axis warping — that
# flattens c2 (299->150) and turns c3 into a needle (175->86). Use gentle
# uniform shrink + small tilt instead.
HEART_DOT_LONG_AXIS = float(os.environ.get("LUO_HEART_DOT_LONG_AXIS", "0.95"))
HEART_DOT_SHORT_AXIS = float(os.environ.get("LUO_HEART_DOT_SHORT_AXIS", "0.85"))
HEART_DOT_ANGLE = float(os.environ.get("LUO_HEART_DOT_ANGLE", "5.0"))
HEART_HOOK_SHORTEN = float(os.environ.get("LUO_HEART_HOOK_SHORTEN", "0.10"))
HEART_DOT_SPACING = float(os.environ.get("LUO_HEART_DOT_SPACING", "1.06"))
HEART_STANDALONE_DOT_LONG_AXIS = float(os.environ.get("LUO_HEART_STANDALONE_DOT_LONG_AXIS", "0.88"))
HEART_STANDALONE_DOT_SHORT_AXIS = float(os.environ.get("LUO_HEART_STANDALONE_DOT_SHORT_AXIS", "0.90"))
HEART_STANDALONE_DOT_SPACING = float(os.environ.get("LUO_HEART_STANDALONE_DOT_SPACING", "1.02"))
HEART_STANDALONE_HOOK_SHORTEN = float(os.environ.get("LUO_HEART_STANDALONE_HOOK_SHORTEN", "0.14"))
HEART_STANDALONE_HOOK_TAIL_CONTAIN = float(os.environ.get("LUO_HEART_STANDALONE_HOOK_TAIL_CONTAIN", "0.05"))
HEART_STANDALONE_RAISE_EM = float(os.environ.get("LUO_HEART_STANDALONE_RAISE_EM", "0.040"))
HEART_STANDALONE_LEFT_DOT_OUTSET = float(os.environ.get("LUO_HEART_STANDALONE_LEFT_DOT_OUTSET", "0.035"))
HEART_STANDALONE_RIGHT_DOT_INSET = float(os.environ.get("LUO_HEART_STANDALONE_RIGHT_DOT_INSET", "0.030"))
HEART_STANDALONE_RIGHT_DOT_LONG_SCALE = float(os.environ.get("LUO_HEART_STANDALONE_RIGHT_DOT_LONG_SCALE", "0.920"))
HEART_STANDALONE_RIGHT_DOT_RAISE_EM = float(os.environ.get("LUO_HEART_STANDALONE_RIGHT_DOT_RAISE_EM", "0.020"))
HEART_STANDALONE_HOOK_SHIFT_X_EM = float(os.environ.get("LUO_HEART_STANDALONE_HOOK_SHIFT_X_EM", "-0.020"))
HEART_STANDALONE_HOOK_STEM_THICKEN = float(os.environ.get("LUO_HEART_STANDALONE_HOOK_STEM_THICKEN", "0.035"))

# Final display-anchor refinements. These are deliberately tiny, character-
# specific touches for the homepage display words; they should not become
# another global style pass.
ANCHOR_LUO_TOP_EXPAND = float(os.environ.get("LUO_ANCHOR_LUO_TOP_EXPAND", "1.025"))
ANCHOR_LUO_BOTTOM_CONTRACT = float(os.environ.get("LUO_ANCHOR_LUO_BOTTOM_CONTRACT", "0.955"))
ANCHOR_BI_TOP_SCALE_X = float(os.environ.get("LUO_ANCHOR_BI_TOP_SCALE_X", "0.940"))
ANCHOR_BI_TOP_SCALE_Y = float(os.environ.get("LUO_ANCHOR_BI_TOP_SCALE_Y", "0.975"))
ANCHOR_JIAN_BOTTOM_RAISE_EM = float(os.environ.get("LUO_ANCHOR_JIAN_BOTTOM_RAISE_EM", "0.035"))
ANCHOR_JIAN_BOTTOM_CONTAIN = float(os.environ.get("LUO_ANCHOR_JIAN_BOTTOM_CONTAIN", "0.018"))
ANCHOR_JIAN_RIGHT_TAIL_CONTAIN = float(os.environ.get("LUO_ANCHOR_JIAN_RIGHT_TAIL_CONTAIN", "0.035"))

BUILD_CHARS = os.environ.get("LUO_BUILD_CHARS", "starter")
BUILD_CHAR_MODES = (
    "seed",
    "site",
    "starter",
    "full",
    "gb2312-level1",
    "gb2312-full",
)

FAMILY = os.environ.get("LUO_FAMILY", "Luo")
SUBFAMILY = os.environ.get("LUO_SUBFAMILY", "Regular")
OUTPUT_PREFIX = os.environ.get("LUO_OUTPUT_PREFIX", "Luo-Regular")
VERSION = "0.3.0"

COPYRIGHT = (
    "Luo, a CJK typeface for paper and reading. "
    "Portions copyright Lxgw. SIL OFL 1.1."
)
LICENSE_TEXT = (
    "This Font Software is licensed under the SIL Open Font License, "
    "Version 1.1. See https://scripts.sil.org/OFL"
)
LICENSE_URL = "https://scripts.sil.org/OFL"


def load_font(path: Path) -> TTFont:
    if not path.exists():
        sys.exit(
            f"[luo] base font not found at: {path}\n"
            f"       Run: python scripts/fetch_base_font.py"
        )
    print(f"[luo] loading base font: {path}")
    return TTFont(str(path))


def _is_cjk_glyph(name: str, cmap: dict[int, str]) -> bool:
    """Check if a glyph name maps to a CJK codepoint or CJK punctuation."""
    for cp, gn in cmap.items():
        if gn != name:
            continue
        if 0x3400 <= cp <= 0x9FFF:
            return True
        # CJK punctuation & symbols, fullwidth forms, vertical forms
        if (0x3000 <= cp <= 0x303F
                or 0xFF01 <= cp <= 0xFF60
                or 0xFE10 <= cp <= 0xFE4F):
            return True
    return False


def _is_cjk_punctuation_cp(cp: int) -> bool:
    return (
        0x3000 <= cp <= 0x303F
        or 0xFF01 <= cp <= 0xFF60
        or 0xFE10 <= cp <= 0xFE4F
    )


def _is_cjk_punctuation_glyph(name: str, cmap: dict[int, str]) -> bool:
    for cp, gn in cmap.items():
        if gn == name and _is_cjk_punctuation_cp(cp):
            return True
    return False


def _contour_bounds(coords, start: int, end: int) -> tuple[int, int, int, int, int]:
    xs = [coords[i][0] for i in range(start, end + 1)]
    ys = [coords[i][1] for i in range(start, end + 1)]
    return min(xs), min(ys), max(xs), max(ys), end - start + 1


def _is_dot_like_contour(coords, start: int, end: int, total_area: float) -> bool:
    if total_area <= 0:
        return False
    x_min, y_min, x_max, y_max, n_pts = _contour_bounds(coords, start, end)
    if n_pts < 12 or n_pts > DOT_MAX_POINTS:
        return False
    c_w = x_max - x_min
    c_h = y_max - y_min
    if c_w <= 0 or c_h <= 0:
        return False
    aspect = max(c_w, c_h) / min(c_w, c_h)
    if aspect > DOT_BOLDEN_ASPECT_GATE:
        return False
    pct = c_w * c_h / total_area * 100
    return pct < DOT_AREA_PCT


def bolden_glyphs(font: TTFont, bolden_h: float, bolden_v: float) -> None:
    """
    Direction-aware stroke thickening with graduated complexity scaling.

    Each CJK glyph's boldening delta is scaled by _bolden_scale(glyph),
    which reduces weight as contour count rises. This prevents complex
    chars from becoming too dark while keeping simple chars full-weight.
    """
    if bolden_h <= 0 and bolden_v <= 0:
        print("[luo] skipped boldening (delta=0)")
        return
    glyf = font["glyf"]

    cmap = {}
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                cmap.update(table.cmap)

    scale_hist: dict[str, int] = {}
    count = 0
    dot_bolden_contours = 0
    dot_bolden_points = 0
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue

        is_cjk = _is_cjk_glyph(name, cmap)
        if is_cjk:
            scale = _bolden_scale(glyph)
        else:
            scale = 1.0

        key = f"{scale:.2f}"
        scale_hist[key] = scale_hist.get(key, 0) + 1

        local_h = bolden_h * scale
        local_v = bolden_v * scale

        coords = glyph.coordinates
        ends = glyph.endPtsOfContours

        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        old_cx = sum(xs) / len(xs)
        old_cy = sum(ys) / len(ys)
        total_area = (max(xs) - min(xs)) * (max(ys) - min(ys))

        new_coords = list(coords)
        start = 0
        for end in ends:
            n = end - start + 1
            dot_like = is_cjk and _is_dot_like_contour(coords, start, end, total_area)
            if dot_like:
                dot_bolden_contours += 1
            for j in range(n):
                idx = start + j
                px, py = coords[start + (j - 1) % n]
                nx_pt, ny_pt = coords[start + (j + 1) % n]
                x, y = coords[idx]
                tx, ty = nx_pt - px, ny_pt - py
                length = math.hypot(tx, ty)
                if length < 1e-6:
                    continue
                norm_x = -ty / length
                norm_y = tx / length
                horiz_ratio = abs(tx) / length
                base = local_h * horiz_ratio + local_v * (1.0 - horiz_ratio)
                # Diagonal lift: sqrt-broadened parabola so shallow 撇
                # (horiz_ratio≈0.85-0.95, e.g. the bottom 撇 of 斤/新) still
                # gets a meaningful bonus. Pure h/v (r=1 or 0) → 0.
                diag_lift = math.sqrt(4.0 * horiz_ratio * (1.0 - horiz_ratio))
                # Corner gating: at 横折/竖折 corners, the prev→next secant
                # accidentally looks like a 45° diagonal, so naive bonus
                # bulges the joint outward (visible: 仰 卬 右上角, 骰 殳 右上角
                # too thick). Suppress bonus at sharp corners by scaling with
                # cos(angle between incoming and outgoing edges).
                v_in_len = math.hypot(x - px, y - py)
                v_out_len = math.hypot(nx_pt - x, ny_pt - y)
                smoothness = 1.0
                if v_in_len > 1e-6 and v_out_len > 1e-6:
                    cos_corner = ((x - px) * (nx_pt - x) + (y - py) * (ny_pt - y)) / (v_in_len * v_out_len)
                    smoothness = max(0.0, cos_corner)
                delta = base + BOLDEN_DIAG_BONUS * diag_lift * smoothness
                move_x = delta * norm_x
                move_y = delta * norm_y
                if dot_like:
                    x_cap = local_h * DOT_BOLDEN_X_CAP_FACTOR
                    if abs(move_x) > x_cap and abs(move_x) > 1e-6:
                        move_x = math.copysign(x_cap, move_x)
                        dot_bolden_points += 1
                new_coords[idx] = (
                    int(round(x + move_x)),
                    int(round(y + move_y)),
                )
            start = end + 1

        new_xs = [c[0] for c in new_coords]
        new_ys = [c[1] for c in new_coords]
        drift_x = int(round(sum(new_xs) / len(new_xs) - old_cx))
        drift_y = int(round(sum(new_ys) / len(new_ys) - old_cy))
        if drift_x != 0 or drift_y != 0:
            for i in range(len(new_coords)):
                nx, ny = new_coords[i]
                new_coords[i] = (nx - drift_x, ny - drift_y)

        for i, c in enumerate(new_coords):
            coords[i] = c
        glyph.recalcBounds(glyf)
        count += 1

    dist = " | ".join(f"×{k}: {v}" for k, v in sorted(scale_hist.items(), reverse=True))
    print(f"[luo] boldened {count} glyphs (h={bolden_h}, v={bolden_v}, graduated)")
    print(f"[luo]   scale distribution: {dist}")
    print(
        f"[luo]   dot-aware bolden cap: {dot_bolden_contours} contours, "
        f"{dot_bolden_points} points (x_cap={DOT_BOLDEN_X_CAP_FACTOR}×h)"
    )


def _glyph_complexity(glyph) -> str:
    """Classify glyph as simple/regular/complex by contour count."""
    n = glyph.numberOfContours
    if n <= COMPLEXITY_SIMPLE_MAX:
        return "simple"
    if n >= COMPLEXITY_COMPLEX_MIN:
        return "complex"
    return "regular"


def _spacing_factor(glyph) -> float:
    """Graduated spacing: more advance width as contour count rises."""
    n = glyph.numberOfContours
    if n <= SPACING_ONSET:
        return SPACING_BASE
    return min(SPACING_CAP, SPACING_BASE + (n - SPACING_ONSET) * SPACING_STEP)


def _bolden_scale(glyph) -> float:
    """Graduated boldening: less weight as contour count rises."""
    n = glyph.numberOfContours
    if n <= BOLDEN_GRAD_ONSET:
        return 1.0
    return max(BOLDEN_GRAD_FLOOR, 1.0 - (n - BOLDEN_GRAD_ONSET) * BOLDEN_GRAD_STEP)


def soften_endpoints(font: TTFont) -> None:
    """
    Soften sharp stroke endpoints on CJK glyphs (硬切 -> 软切).

    Targets on-curve points that form sharp angles with SHORT adjacent
    segments (stroke terminals). Long-segment corners like 口/日 structural
    edges are filtered out by SOFTEN_SEG_MAX.
    """
    glyf = font["glyf"]

    cmap = {}
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                cmap.update(table.cmap)

    threshold_rad = math.radians(SOFTEN_ANGLE)
    softened_points = 0
    softened_glyphs = 0
    subtype_counts = {"h": 0, "v_bottom": 0, "diag": 0, "default": 0}

    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue
        if not _is_cjk_glyph(name, cmap):
            continue

        coords = glyph.coordinates
        flags = glyph.flags
        ends = glyph.endPtsOfContours
        new_coords = list(coords)
        glyph_touched = False

        all_xs = [c[0] for c in coords]
        all_ys = [c[1] for c in coords]
        glyph_area = (max(all_xs) - min(all_xs)) * (max(all_ys) - min(all_ys)) if coords else 0

        start = 0
        for end in ends:
            n = end - start + 1

            # Skip dot-like small contours: keep their original sharpness so
            # Pass A / heart can shape them directionally. Without this skip,
            # soften+taper turn xiaokai dots into round droplets.
            if n < 20 and glyph_area > 0:
                c_xs = [coords[i][0] for i in range(start, end + 1)]
                c_ys = [coords[i][1] for i in range(start, end + 1)]
                c_area = (max(c_xs) - min(c_xs)) * (max(c_ys) - min(c_ys))
                if c_area / glyph_area < 0.05:
                    start = end + 1
                    continue

            for j in range(n):
                idx = start + j
                if not (flags[idx] & 1):
                    continue

                prev_idx = start + (j - 1) % n
                next_idx = start + (j + 1) % n

                cx, cy = coords[idx]
                px, py = coords[prev_idx]
                nx_pt, ny_pt = coords[next_idx]

                len_in = math.hypot(px - cx, py - cy)
                len_out = math.hypot(nx_pt - cx, ny_pt - cy)

                if len_in > SOFTEN_SEG_MAX or len_out > SOFTEN_SEG_MAX:
                    continue
                if len_in < 1e-6 or len_out < 1e-6:
                    continue

                v_in_x = (px - cx) / len_in
                v_in_y = (py - cy) / len_in
                v_out_x = (nx_pt - cx) / len_out
                v_out_y = (ny_pt - cy) / len_out
                dot = max(-1.0, min(1.0, v_in_x * v_out_x + v_in_y * v_out_y))
                angle = math.acos(dot)

                if angle >= threshold_rad:
                    continue

                mid_x = (px + nx_pt) / 2.0
                mid_y = (py + ny_pt) / 2.0
                tip_x = cx - mid_x
                tip_y = cy - mid_y

                subtype = "default"
                subtype_blend = SOFTEN_BLEND
                if abs(tip_x) > abs(tip_y) * 1.35:
                    subtype = "h"
                    subtype_blend = ENDPOINT_H_BLEND
                elif tip_y < 0 and abs(tip_y) > abs(tip_x) * 1.20:
                    subtype = "v_bottom"
                    subtype_blend = ENDPOINT_V_BOTTOM_BLEND
                elif abs(tip_x) > 1e-6 and abs(tip_y) > 1e-6:
                    subtype = "diag"
                    subtype_blend = ENDPOINT_DIAG_BLEND

                sharpness = 1.0 - angle / threshold_rad
                blend = subtype_blend * sharpness
                new_x = cx + blend * (mid_x - cx)
                new_y = cy + blend * (mid_y - cy)
                new_coords[idx] = (int(round(new_x)), int(round(new_y)))
                softened_points += 1
                subtype_counts[subtype] += 1
                glyph_touched = True

            start = end + 1

        if glyph_touched:
            for i, c in enumerate(new_coords):
                coords[i] = c
            glyph.recalcBounds(glyf)
            softened_glyphs += 1

    print(
        f"[luo] softened {softened_points} endpoints across "
        f"{softened_glyphs} glyphs (angle<{SOFTEN_ANGLE}°, "
        f"blend={SOFTEN_BLEND}, h={ENDPOINT_H_BLEND}, "
        f"v_bottom={ENDPOINT_V_BOTTOM_BLEND}, diag={ENDPOINT_DIAG_BLEND}, "
        f"seg_max={SOFTEN_SEG_MAX}, subtypes={subtype_counts})"
    )


def refine_hooks(font: TTFont) -> None:
    """
    Refine CJK hook strokes: thinner root, shorter body, lighter tip.

    Detects hook-like direction changes where a long incoming segment
    meets a sharp turn into a shorter outgoing segment, then applies:
      1. Root thinning: reduce the outward bulge at the junction
      2. Body shortening: compress hook body toward the root
      3. Tip tapering: lighten hook endpoint for speed feel
    """
    glyf = font["glyf"]

    cmap = {}
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                cmap.update(table.cmap)

    hook_count = 0
    glyph_count = 0

    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue
        if not _is_cjk_glyph(name, cmap):
            continue

        coords = glyph.coordinates
        ends = glyph.endPtsOfContours
        new_coords = list(coords)
        touched = False

        start = 0
        for end in ends:
            n = end - start + 1
            # Skip low-point-count contours: they're rectangles or simple
            # stroke structures (small frames, internal short strokes), not
            # hooks. Real hooks live inside main contours (n=60+) which
            # still get processed.
            if n < 12:
                start = end + 1
                continue

            for j in range(n):
                idx = start + j
                i_prev = start + (j - 1) % n
                i_next = start + (j + 1) % n
                i_next2 = start + (j + 2) % n

                p0 = coords[i_prev]
                p1 = coords[idx]
                p2 = coords[i_next]

                d_in = (p1[0] - p0[0], p1[1] - p0[1])
                d_out = (p2[0] - p1[0], p2[1] - p1[1])

                len_in = math.hypot(*d_in)
                len_out = math.hypot(*d_out)
                if len_in < 8 or len_out < 5:
                    continue

                cos_a = (d_in[0] * d_out[0] + d_in[1] * d_out[1]) / (len_in * len_out)
                cos_a = max(-1.0, min(1.0, cos_a))
                angle = math.degrees(math.acos(cos_a))

                if angle < 60 or angle > 130:
                    continue
                if len_out > 90 or len_in < len_out * 1.5:
                    continue

                mid_x = (p0[0] + p2[0]) / 2.0
                mid_y = (p0[1] + p2[1]) / 2.0
                new_coords[idx] = (
                    int(round(p1[0] + HOOK_ROOT_THIN * (mid_x - p1[0]))),
                    int(round(p1[1] + HOOK_ROOT_THIN * (mid_y - p1[1]))),
                )

                new_coords[i_next] = (
                    int(round(p2[0] + HOOK_SHORTEN * (p1[0] - p2[0]))),
                    int(round(p2[1] + HOOK_SHORTEN * (p1[1] - p2[1]))),
                )

                new_coords[i_next2] = (
                    int(round(p3[0] + HOOK_TIP_TAPER * (p2[0] - p3[0]))),
                    int(round(p3[1] + HOOK_TIP_TAPER * (p2[1] - p3[1]))),
                )

                hook_count += 1
                touched = True

            start = end + 1

        if touched:
            for i, c in enumerate(new_coords):
                coords[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] refined {hook_count} hooks across {glyph_count} glyphs "
        f"(root={HOOK_ROOT_THIN}, shorten={HOOK_SHORTEN}, taper={HOOK_TIP_TAPER})"
    )


def narrow_and_scale(
    font: TTFont,
    narrow_simple: float,
    narrow_regular: float,
    narrow_complex: float,
    scale_y: float,
) -> None:
    """
    Per-glyph transform with complexity-aware horizontal narrowing:
      - Simple chars (few contours): wider, preserve openness
      - Regular chars: standard narrowing for upright presence
      - Complex chars (many contours): narrower, avoid sprawl
    Non-CJK glyphs use narrow_regular as default.
    """
    glyf = font["glyf"]
    hmtx = font["hmtx"]

    cmap = {}
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                cmap.update(table.cmap)

    stats = {"simple": 0, "regular": 0, "complex": 0}
    count = 0

    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue

        is_cjk = _is_cjk_glyph(name, cmap)
        if is_cjk:
            complexity = _glyph_complexity(glyph)
            stats[complexity] += 1
            if complexity == "simple":
                nx = narrow_simple
            elif complexity == "complex":
                nx = narrow_complex
            else:
                nx = narrow_regular
        else:
            nx = narrow_regular

        adv, lsb = hmtx[name]
        cx = adv / 2.0

        coords = glyph.coordinates
        for i in range(len(coords)):
            x, y = coords[i]
            new_x = cx + (x - cx) * nx
            new_y = y * scale_y
            coords[i] = (int(round(new_x)), int(round(new_y)))

        glyph.recalcBounds(glyf)
        count += 1

    print(
        f"[luo] transformed {count} glyphs: scale_y={scale_y:.2f}, "
        f"narrow simple={narrow_simple:.2f}({stats['simple']}) "
        f"regular={narrow_regular:.2f}({stats['regular']}) "
        f"complex={narrow_complex:.2f}({stats['complex']})"
    )


# --- Component-aware refinement ---
# First-match wins: a char in multiple categories gets the earliest one.

CHAR_CATEGORIES: dict[str, str] = {
    "enclosed": (
        "国回图固日目田囗闰月闻问间阅品器曾"
        "四因圆困围园团口"
        "嗟嘻唯喻咏咸哉"
        "内向同周面由西"
    ),
    "dense_top": (
        "霜露霞雪草落蓝营笔简答篇藏艺蒙节茂荒蓄蒸薄蔽莫"
        "暮暗暑"
        "慕幕募墓"
        "春茅荟萃万"
    ),
    "wide_split": (
        "说读诗语论设计清流润源终结经续纸妙好如社视"
        "规则继愿舒族旅排版印短"
        "诞谓诸话词训让识讨记谈"
        "激湍映殊殇"
        "她始妄"
        "础礼祈祝"
        "使信修做倦值促仰件住体余作但保候代你"
        "接收放打把抱承技持招择担拉"
        "悟悲悼惠想感慢慨性息"
        "测浪温游汉法深浅洪"
        "码磨确"
        "验骑骋"
        "编缩绵统给练绝纟"
        "服胜能腾脏"
        "观览觉"
        "议试负责购趣起"
        "部郡都"
        "阴阵陈随际隐"
        "饰馆"
        "旋断斯"
        "牌特犹"
        "猜独狂"
        "构样标格档桥林杂极楚条"
        "利创刚到削别"
        "听呼唤"
        "切分初功化"
        "封对寸将寄察"
        "取卫端媚冷板炫秩横轻竖软现陪"
        "动制解改转换新旧知校检扩批"
        "张缺轮廓净细钩准复糊跳散"
        "朗俯休何"
    ),
    "walk_enclosed": (
        "远近道遇迁迹逸造连过这还进运遍适选述"
        "透通达送逢迫递途边"
    ),
    "dense_complex": (
        "馈赢耀魔题额锦覆籍麟"
        "群贤毕稽禊觞畅叙幽慨慢"
        "魏晋羲癸藏霜霞露"
        "骋懈惯"
        "繁编续缘"
        "颜领"
        "魄魂"
        "鼹鼠"
        "韵静"
        "雅"
    ),
    "multi_horiz": (
        "书言青春者暑量重墨章律吕盈盛曾寒"
        "骨兰亭集黄善美宇宙"
        "王正主平年干于土士生至三二上下"
        "丽录"
    ),
    "top_bottom": (
        "安宇宙宿定室宝完宣家容密寒"
        "字学会香念意"
        "产亭亦亮京享交"
        "文天玄黄云雨金水玉冬尽盖齐"
        "写点背音章"
        "前券剪"
        "兴其具典冀"
        "异弃"
        "奏契套奖"
        "虽虚"
        "岁岂岭峻崇山"
        "号各合名向吕古台叶只可另右史召"
        "象足"
        "管筋符竹类籍"
        "系紧索累"
        "耐老者"
    ),
}

ENCLOSED_INNER_CONTRACT = 0.97
DENSE_TOP_REDUCE = 0.97
WIDE_SPLIT_LEFT_NARROW = 0.98
WALK_INNER_CONTRACT = 0.98
DENSE_COMPLEX_INNER = 0.970
DENSE_COMPLEX_INNER_EXTRA = float(os.environ.get("LUO_DENSE_COMPLEX_INNER_EXTRA", "0.945"))
DENSE_TOP_REDUCE_EXTRA = float(os.environ.get("LUO_DENSE_TOP_REDUCE_EXTRA", "0.955"))
MULTI_HORIZ_SECONDARY = 0.965
TOP_BOTTOM_UPPER_CONTRACT = 0.98

# Final walk-radical containment. The category pass above opens the enclosed
# body; this pass only reins in the lowest, widest 辶 contour on a short
# whitelist so 透/道/遇 stop reading as bottom-heavy.
WALK_FINAL_CHARS = "透道遇述远"
WALK_FINAL_X_CONTAIN = float(os.environ.get("LUO_WALK_FINAL_X_CONTAIN", "0.955"))
WALK_FINAL_BOTTOM_RAISE_EM = float(os.environ.get("LUO_WALK_FINAL_BOTTOM_RAISE_EM", "0.028"))
WALK_FINAL_TAIL_CONTAIN = float(os.environ.get("LUO_WALK_FINAL_TAIL_CONTAIN", "0.055"))
WALK_BODY_TARGET_TOP = float(os.environ.get("LUO_WALK_BODY_TARGET_TOP", "0.840"))
WALK_BODY_TOP_RAISE_MAX = float(os.environ.get("LUO_WALK_BODY_TOP_RAISE_MAX", "0.045"))
WALK_BODY_X_CONTAIN = float(os.environ.get("LUO_WALK_BODY_X_CONTAIN", "0.985"))
WALK_FINAL_SETTLE_EM = float(os.environ.get("LUO_WALK_FINAL_SETTLE_EM", "0.024"))

# 黑部点群 needs protection from generic xiaokai-dot shaping. In 墨, those dots
# sit inside a dense stacked glyph; keep thickness and only shorten their long
# axis slightly so they remain compact without becoming slash-like.
BLACK_DOT_CLUSTER_CHARS = "墨"
BLACK_DOT_CLUSTER_LONG_AXIS = float(os.environ.get("LUO_BLACK_DOT_CLUSTER_LONG_AXIS", "0.90"))
BLACK_DOT_CLUSTER_SHORT_AXIS = float(os.environ.get("LUO_BLACK_DOT_CLUSTER_SHORT_AXIS", "1.00"))

EXTRA_DENSE_CHARS = "落藏霞霜露馈赢耀魔籍麟题额锦续群贤禊觞湍幽怀"


def _build_reverse_cmap(font: TTFont) -> dict[str, int]:
    rcmap: dict[str, int] = {}
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                for cp, gname in table.cmap.items():
                    rcmap[gname] = cp
    return rcmap


def _char_category(char: str) -> str | None:
    for cat, chars in CHAR_CATEGORIES.items():
        if char in chars:
            return cat
    return None


def _refine_enclosed(glyph, glyf) -> None:
    if glyph.numberOfContours < 2:
        return
    coords = glyph.coordinates
    ends = list(glyph.endPtsOfContours)
    contours = []
    start = 0
    for end in ends:
        xs = [coords[i][0] for i in range(start, end + 1)]
        ys = [coords[i][1] for i in range(start, end + 1)]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys)) if xs else 0
        contours.append((area, start, end))
        start = end + 1
    contours.sort(reverse=True)
    all_xs = [coords[i][0] for i in range(len(coords))]
    cx = (min(all_xs) + max(all_xs)) / 2.0
    for _, s, e in contours[1:]:
        for i in range(s, e + 1):
            x, y = coords[i]
            coords[i] = (int(round(cx + (x - cx) * ENCLOSED_INNER_CONTRACT)), y)
    glyph.recalcBounds(glyf)


def _refine_dense_top(glyph, glyf, char: str = "") -> None:
    coords = glyph.coordinates
    n = len(coords)
    if n == 0:
        return
    ys = [coords[i][1] for i in range(n)]
    y_min, y_max = min(ys), max(ys)
    y_range = y_max - y_min
    if y_range <= 0:
        return
    xs = [coords[i][0] for i in range(n)]
    cx = (min(xs) + max(xs)) / 2.0
    top_threshold = y_min + y_range * 0.6
    reduce = DENSE_TOP_REDUCE_EXTRA if char in EXTRA_DENSE_CHARS else DENSE_TOP_REDUCE
    for i in range(n):
        x, y = coords[i]
        if y > top_threshold:
            t = (y - top_threshold) / (y_max - top_threshold) if y_max > top_threshold else 0
            factor = 1.0 - (1.0 - reduce) * t
            coords[i] = (int(round(cx + (x - cx) * factor)), y)
    glyph.recalcBounds(glyf)


def _refine_top_bottom(glyph, glyf) -> None:
    coords = glyph.coordinates
    n = len(coords)
    if n == 0:
        return
    ys = [coords[i][1] for i in range(n)]
    y_min, y_max = min(ys), max(ys)
    y_range = y_max - y_min
    if y_range <= 0:
        return
    xs = [coords[i][0] for i in range(n)]
    cx = (min(xs) + max(xs)) / 2.0
    y_mid = (y_min + y_max) / 2.0
    for i in range(n):
        x, y = coords[i]
        if y > y_mid:
            t = (y - y_mid) / (y_max - y_mid) if y_max > y_mid else 0
            factor = 1.0 - (1.0 - TOP_BOTTOM_UPPER_CONTRACT) * t
            new_x = cx + (x - cx) * factor
            coords[i] = (int(round(new_x)), y)
    glyph.recalcBounds(glyf)


def _refine_dense_complex(glyph, glyf, char: str = "") -> None:
    if glyph.numberOfContours < 2:
        return
    coords = glyph.coordinates
    ends = list(glyph.endPtsOfContours)
    contours = []
    start = 0
    for end in ends:
        xs = [coords[i][0] for i in range(start, end + 1)]
        ys = [coords[i][1] for i in range(start, end + 1)]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys)) if xs else 0
        contours.append((area, start, end))
        start = end + 1
    contours.sort(reverse=True)
    all_xs = [coords[i][0] for i in range(len(coords))]
    all_ys = [coords[i][1] for i in range(len(coords))]
    cx = (min(all_xs) + max(all_xs)) / 2.0
    cy = (min(all_ys) + max(all_ys)) / 2.0
    factor = DENSE_COMPLEX_INNER_EXTRA if char in EXTRA_DENSE_CHARS else DENSE_COMPLEX_INNER
    for _, s, e in contours[1:]:
        for i in range(s, e + 1):
            x, y = coords[i]
            new_x = cx + (x - cx) * factor
            new_y = cy + (y - cy) * factor
            coords[i] = (int(round(new_x)), int(round(new_y)))
    glyph.recalcBounds(glyf)


def _refine_multi_horiz(glyph, glyf) -> None:
    coords = glyph.coordinates
    n = len(coords)
    if n == 0:
        return
    xs = [coords[i][0] for i in range(n)]
    ys = [coords[i][1] for i in range(n)]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    cx = (x_min + x_max) / 2.0
    cy = (y_min + y_max) / 2.0
    y_range = y_max - y_min
    if y_range <= 0:
        return
    for i in range(n):
        x, y = coords[i]
        dist = abs(y - cy) / (y_range / 2.0)
        if dist < 0.4:
            factor = MULTI_HORIZ_SECONDARY
            new_x = cx + (x - cx) * factor
            coords[i] = (int(round(new_x)), y)
    glyph.recalcBounds(glyf)


def _refine_wide_split(glyph, glyf) -> None:
    coords = glyph.coordinates
    n = len(coords)
    if n == 0:
        return
    xs = [coords[i][0] for i in range(n)]
    x_min, x_max = min(xs), max(xs)
    x_mid = (x_min + x_max) / 2.0
    for i in range(n):
        x, y = coords[i]
        if x < x_mid:
            new_x = x_mid + (x - x_mid) * WIDE_SPLIT_LEFT_NARROW
            coords[i] = (int(round(new_x)), y)
    glyph.recalcBounds(glyf)


def _refine_walk_enclosed(glyph, glyf) -> None:
    if glyph.numberOfContours < 2:
        return
    coords = glyph.coordinates
    ends = list(glyph.endPtsOfContours)
    contours = []
    start = 0
    for end in ends:
        xs = [coords[i][0] for i in range(start, end + 1)]
        ys = [coords[i][1] for i in range(start, end + 1)]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys)) if xs else 0
        contours.append((area, start, end))
        start = end + 1
    contours.sort(reverse=True)
    all_xs = [coords[i][0] for i in range(len(coords))]
    all_ys = [coords[i][1] for i in range(len(coords))]
    cx = (min(all_xs) + max(all_xs)) / 2.0
    cy = (min(all_ys) + max(all_ys)) / 2.0
    for _, s, e in contours[1:]:
        for i in range(s, e + 1):
            x, y = coords[i]
            new_x = cx + (x - cx) * WALK_INNER_CONTRACT
            new_y = cy + (y - cy) * WALK_INNER_CONTRACT
            coords[i] = (int(round(new_x)), int(round(new_y)))
    glyph.recalcBounds(glyf)


def _refine_walk_final_glyph(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    if glyph.numberOfContours < 2 or len(coords) == 0:
        return False

    all_xs = [coords[i][0] for i in range(len(coords))]
    all_ys = [coords[i][1] for i in range(len(coords))]
    glyph_x_min, glyph_x_max = min(all_xs), max(all_xs)
    glyph_y_min, glyph_y_max = min(all_ys), max(all_ys)
    glyph_w = glyph_x_max - glyph_x_min
    glyph_h = glyph_y_max - glyph_y_min
    if glyph_w <= 0 or glyph_h <= 0:
        return False

    contours = []
    start = 0
    for end in glyph.endPtsOfContours:
        x_min, y_min, x_max, y_max, n_pts = _contour_bounds(coords, start, end)
        w = x_max - x_min
        h = y_max - y_min
        if (
            n_pts >= 24
            and w > glyph_w * 0.70
            and y_min <= glyph_y_min + glyph_h * 0.10
            and y_max <= glyph_y_min + glyph_h * 0.72
        ):
            contours.append((y_min, -w, start, end, x_min, y_min, x_max, y_max))
        start = end + 1

    if not contours:
        return False

    _, _, start, end, x_min, y_min, x_max, y_max = sorted(contours)[0]
    cx = (glyph_x_min + glyph_x_max) / 2.0
    c_cx = (x_min + x_max) / 2.0
    c_h = y_max - y_min
    if c_h <= 0:
        return False

    touched = False
    walk_start, walk_end = start, end
    body_indices = [
        i
        for i in range(len(coords))
        if i < walk_start or i > walk_end
    ]
    body_raise = 0.0
    body_y_min = body_y_max = 0
    if body_indices:
        body_ys = [coords[i][1] for i in body_indices]
        body_y_min = min(body_ys)
        body_y_max = max(body_ys)
        target_top = WALK_BODY_TARGET_TOP * upm
        body_raise = max(0.0, min(WALK_BODY_TOP_RAISE_MAX * upm, target_top - body_y_max))

    if body_raise > 0:
        body_h = max(1.0, body_y_max - body_y_min)
        for i in body_indices:
            x, y = coords[i]
            t = max(0.0, min(1.0, (y - body_y_min) / body_h))
            new_x = cx + (x - cx) * (1.0 - (1.0 - WALK_BODY_X_CONTAIN) * t)
            new_y = y + body_raise * t
            coords[i] = (int(round(new_x)), int(round(new_y)))
            touched = True

    raise_y = WALK_FINAL_BOTTOM_RAISE_EM * upm
    bottom_cut = y_min + c_h * 0.42
    right_span = max(1.0, x_max - c_cx)

    for i in range(walk_start, walk_end + 1):
        x, y = coords[i]
        bottom_t = 0.0
        if y < bottom_cut:
            bottom_t = (bottom_cut - y) / max(1.0, bottom_cut - y_min)
            bottom_t = max(0.0, min(1.0, bottom_t))

        x_factor = 1.0 - (1.0 - WALK_FINAL_X_CONTAIN) * (0.35 + 0.65 * bottom_t)
        new_x = cx + (x - cx) * x_factor
        if x > c_cx and bottom_t > 0:
            right_t = max(0.0, min(1.0, (x - c_cx) / right_span))
            new_x -= (x - c_cx) * WALK_FINAL_TAIL_CONTAIN * right_t * bottom_t
        new_y = y + raise_y * bottom_t

        if int(round(new_x)) != x or int(round(new_y)) != y:
            coords[i] = (int(round(new_x)), int(round(new_y)))
            touched = True

    if touched:
        settle_y = int(round(WALK_FINAL_SETTLE_EM * upm))
        if settle_y:
            for i in range(len(coords)):
                x, y = coords[i]
                coords[i] = (x, y - settle_y)
        glyph.recalcBounds(glyf)
    return touched


def refine_walk_final(font: TTFont) -> None:
    glyf = font["glyf"]
    cmap = font.getBestCmap() or {}
    upm = font["head"].unitsPerEm

    touched = []
    for char in WALK_FINAL_CHARS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if _refine_walk_final_glyph(glyph, glyf, upm):
            touched.append(char)

    if touched:
        print(
            f"[luo] final-contained walk radicals: {''.join(touched)} "
            f"(x={WALK_FINAL_X_CONTAIN}, raise={WALK_FINAL_BOTTOM_RAISE_EM}em, "
            f"tail={WALK_FINAL_TAIL_CONTAIN}, body_top={WALK_BODY_TARGET_TOP}em, "
            f"body_raise={WALK_BODY_TOP_RAISE_MAX}em, body_x={WALK_BODY_X_CONTAIN}, "
            f"settle={WALK_FINAL_SETTLE_EM}em)"
        )


def refine_by_category(font: TTFont) -> None:
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    stats: dict[str, int] = {}
    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if not cp:
            continue
        char = chr(cp)
        cat = _char_category(char)
        if not cat:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        if cat == "enclosed":
            _refine_enclosed(glyph, glyf)
        elif cat == "dense_top":
            _refine_dense_top(glyph, glyf, char)
        elif cat == "wide_split":
            _refine_wide_split(glyph, glyf)
        elif cat == "walk_enclosed":
            _refine_walk_enclosed(glyph, glyf)
        elif cat == "dense_complex":
            _refine_dense_complex(glyph, glyf, char)
        elif cat == "multi_horiz":
            _refine_multi_horiz(glyph, glyf)
        elif cat == "top_bottom":
            _refine_top_bottom(glyph, glyf)
        stats[cat] = stats.get(cat, 0) + 1
    total = sum(stats.values())
    if total > 0:
        detail = " ".join(f"{k}={v}" for k, v in sorted(stats.items()))
        print(f"[luo] refined {total} glyphs by category ({detail})")


def _contour_info(glyph, coords) -> list[dict[str, float | int]]:
    contours = []
    start = 0
    for ci, end in enumerate(glyph.endPtsOfContours):
        xs = [coords[i][0] for i in range(start, end + 1)]
        ys = [coords[i][1] for i in range(start, end + 1)]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        contours.append({
            "idx": ci,
            "start": start,
            "end": end,
            "cx": sum(xs) / len(xs),
            "cy": sum(ys) / len(ys),
            "xmin": min(xs),
            "xmax": max(xs),
            "ymin": min(ys),
            "ymax": max(ys),
            "area": w * h,
        })
        start = end + 1
    return contours


def _refine_anchor_luo(glyph, glyf) -> None:
    coords = glyph.coordinates
    if len(coords) == 0:
        return
    xs = [coords[i][0] for i in range(len(coords))]
    ys = [coords[i][1] for i in range(len(coords))]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    y_range = y_max - y_min
    if y_range <= 0:
        return
    cx = (x_min + x_max) / 2.0
    top_start = y_min + y_range * 0.62
    bottom_end = y_min + y_range * 0.34
    for i in range(len(coords)):
        x, y = coords[i]
        new_x = x
        if y > top_start and y_max > top_start:
            t = (y - top_start) / (y_max - top_start)
            factor = 1.0 + (ANCHOR_LUO_TOP_EXPAND - 1.0) * t
            new_x = cx + (x - cx) * factor
        elif y < bottom_end and bottom_end > y_min:
            t = (bottom_end - y) / (bottom_end - y_min)
            factor = 1.0 - (1.0 - ANCHOR_LUO_BOTTOM_CONTRACT) * t
            new_x = cx + (x - cx) * factor
        coords[i] = (int(round(new_x)), y)
    glyph.recalcBounds(glyf)


def _refine_anchor_bi(glyph, glyf) -> None:
    coords = glyph.coordinates
    if glyph.numberOfContours < 2 or len(coords) == 0:
        return
    ys = [coords[i][1] for i in range(len(coords))]
    y_min, y_max = min(ys), max(ys)
    y_range = y_max - y_min
    if y_range <= 0:
        return
    top_cut = y_min + y_range * 0.58
    for c in _contour_info(glyph, coords):
        if c["cy"] <= top_cut:
            continue
        cx = float(c["cx"])
        cy = float(c["cy"])
        for i in range(int(c["start"]), int(c["end"]) + 1):
            x, y = coords[i]
            new_x = cx + (x - cx) * ANCHOR_BI_TOP_SCALE_X
            new_y = cy + (y - cy) * ANCHOR_BI_TOP_SCALE_Y
            coords[i] = (int(round(new_x)), int(round(new_y)))
    glyph.recalcBounds(glyf)


def _refine_anchor_jian(glyph, glyf, upm: int) -> None:
    coords = glyph.coordinates
    if len(coords) == 0:
        return
    xs = [coords[i][0] for i in range(len(coords))]
    ys = [coords[i][1] for i in range(len(coords))]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    y_range = y_max - y_min
    if y_range <= 0:
        return
    cx = (x_min + x_max) / 2.0
    bottom_cut = y_min + y_range * 0.32
    raise_y = ANCHOR_JIAN_BOTTOM_RAISE_EM * upm
    for i in range(len(coords)):
        x, y = coords[i]
        if y >= bottom_cut or bottom_cut <= y_min:
            continue
        t = (bottom_cut - y) / (bottom_cut - y_min)
        new_x = cx + (x - cx) * (1.0 - ANCHOR_JIAN_BOTTOM_CONTAIN * t)
        if x > cx:
            new_x -= (x - cx) * ANCHOR_JIAN_RIGHT_TAIL_CONTAIN * t
        new_y = y + raise_y * t
        coords[i] = (int(round(new_x)), int(round(new_y)))
    glyph.recalcBounds(glyf)


def refine_display_anchor_chars(font: TTFont) -> None:
    """Final tiny adjustments for large display anchor glyphs."""
    glyf = font["glyf"]
    cmap = font.getBestCmap() or {}
    upm = font["head"].unitsPerEm
    refiners = {
        "落": lambda glyph: _refine_anchor_luo(glyph, glyf),
        "笔": lambda glyph: _refine_anchor_bi(glyph, glyf),
        "见": lambda glyph: _refine_anchor_jian(glyph, glyf, upm),
    }
    touched = []
    for char, refiner in refiners.items():
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        refiner(glyph)
        touched.append(char)
    if touched:
        print(f"[luo] refined display anchors: {''.join(touched)}")


# --- Pass A: Dot contour refinement ---

HEART_CHARS = (
    "心思意念想感悲惠慨悟您志必恩愁惊慎"
    "忠忽怠恨恐恭忙忆忍忘"
)

# 忄-radical, 灬-bottom and 黑部点群 chars: skip generic dot pass entirely.
# 忄 flanking dots break under 14° rotation; dense dot clusters get over-rotated.
DOT_SKIP_CHARS = (
    "快情怀性恼愉悄惯惜慢忆慎慨悟悬"
    "然照熊燃焦煮热"
    "墨"
    "每"
)

# 氵/讠 chars: use soft channel (rotation preserved for consistency, short-axis eased).
# v0.5.3 skipped these entirely, losing angle normalization; v0.5.4 restores it softly.
DOT_SOFT_CHARS = (
    "江没注治法油况活洪派济浅清润淡深温流游源湍满滴潮激"  # 氵 radicals
    "计认议记许论设证识词试话诞该详语说请诸读调谢"  # 讠 radicals
    "述"  # standalone top dot: keep length, normalize angle only
)
DOT_SHORT_AXIS_SOFT = 0.95  # SOFT: near-identity short axis; normalize angle, don't carve

HOOK_FINAL_CHARS = (
    "字书亭序家设计排版印旅妙馈成式透远道遇永可事将到"
    "心清落读说规则使用方族校走明分手子该受收战支改或"
    "待持动阶了己信仰他指水打你已林期句月接第刷孤色划"
    "保学号传开纸记行张才体义必代织叫服前证求骨利角种"
    "等话克飞弦快载调感语乐九听院制就气马副联发特继只"
    "光也住值我科同线带争志何她农先们级花儿引刺强初"
    "于时见列向写请别认包完系周以元腾终存"
)

TURN_FINAL_CHARS = "".join(dict.fromkeys(
    "落纸风骨短版排印集章源雅舒服规则"
    "国回图园日目用月田间问阅品亭曾会"
    "章言书骨兰量重墨春青善美黄宇宙寒暑律吕"
))

TURN_FINAL_FRAME_CHARS = "国回图园日目用月田间问阅品"


def _build_cmap(font: TTFont) -> dict[int, str]:
    cmap: dict[int, str] = {}
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                cmap.update(table.cmap)
    return cmap


def refine_dot_contours(font: TTFont) -> None:
    """Compress and rotate small dot contours for directional xiaokai feel."""
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)

    dot_count = 0
    glyph_count = 0
    rad = math.radians(DOT_ROTATE_DEG)
    cos_r, sin_r = math.cos(rad), math.sin(rad)

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if not cp:
            continue
        char = chr(cp)
        if not (0x3400 <= cp <= 0x9FFF):
            continue
        if char in HEART_CHARS or char in DOT_SKIP_CHARS:
            continue
        use_soft = char in DOT_SOFT_CHARS

        glyph = glyf[gname]
        if glyph.numberOfContours < 2:
            continue

        coords = glyph.coordinates
        ends = list(glyph.endPtsOfContours)
        all_xs = [coords[i][0] for i in range(len(coords))]
        all_ys = [coords[i][1] for i in range(len(coords))]
        total_area = (max(all_xs) - min(all_xs)) * (max(all_ys) - min(all_ys))
        if total_area <= 0:
            continue

        glyph_x_mid = (min(all_xs) + max(all_xs)) / 2.0
        glyph_y_min = min(all_ys)
        glyph_y_range = max(all_ys) - glyph_y_min
        touched = False

        start = 0
        for end in ends:
            n_pts = end - start + 1
            if n_pts > DOT_MAX_POINTS:
                start = end + 1
                continue
            # Real xiaokai dots in LXGW are 14-18-point smooth curves.
            # Contours with n < 12 are almost always simple stroke structures
            # (rectangle caps, internal small frames in 用/腾/所/幽/地, etc.)
            # — directional shaping twists them into irregular quads.
            if n_pts < 12:
                start = end + 1
                continue

            c_xs = [coords[i][0] for i in range(start, end + 1)]
            c_ys = [coords[i][1] for i in range(start, end + 1)]
            c_w = max(c_xs) - min(c_xs)
            c_h = max(c_ys) - min(c_ys)
            if c_w <= 0 or c_h <= 0:
                start = end + 1
                continue

            aspect = max(c_w, c_h) / min(c_w, c_h)
            # Real xiaokai dots (after bolden + scale) have aspect up to ~3.
            # Pure rectangles (4-pt contours) are filtered above. What's left
            # are long curves (e.g. 卧钩 in 心 with aspect 4+) which we still
            # want to keep orthogonal.
            if aspect > 1.8:
                start = end + 1
                continue

            c_area = c_w * c_h
            pct = c_area / total_area * 100
            if pct >= DOT_AREA_PCT:
                start = end + 1
                continue

            cx = sum(c_xs) / n_pts
            cy = sum(c_ys) / n_pts

            rot = DOT_ROTATE_DEG
            is_left = cx < glyph_x_mid
            is_top = glyph_y_range > 0 and (cy - glyph_y_min) / glyph_y_range > 0.6
            left_dots_on_left = is_left and not is_top
            top_dots = is_top

            if left_dots_on_left:
                rot *= 1.3
            elif top_dots:
                rot *= 0.5

            # Find the long axis by picking the two farthest contour points.
            long_axis_len_sq = 0.0
            long_ax = 1.0
            long_ay = 0.0
            for a in range(n_pts):
                xa, ya = c_xs[a], c_ys[a]
                for b in range(a + 1, n_pts):
                    dxv = c_xs[b] - xa
                    dyv = c_ys[b] - ya
                    d2 = dxv * dxv + dyv * dyv
                    if d2 > long_axis_len_sq:
                        long_axis_len_sq = d2
                        long_ax, long_ay = dxv, dyv
            long_len = math.hypot(long_ax, long_ay)
            if long_len < 1e-6:
                start = end + 1
                continue
            long_ax /= long_len
            long_ay /= long_len

            # Lerp short-axis carve factor toward 1.0 for elongated source dots.
            long_axis_factor = DOT_LONG_AXIS_SOFT if use_soft else DOT_LONG_AXIS
            base_short = DOT_SHORT_AXIS_SOFT if use_soft else DOT_SHORT_AXIS
            relax_t = max(0.0, min(1.0, (aspect - DOT_RELAX_PIVOT) / (DOT_RELAX_GATE - DOT_RELAX_PIVOT)))
            short_axis_factor = base_short + (1.0 - base_short) * relax_t

            local_rad = math.radians(rot)
            local_cos = math.cos(local_rad)
            local_sin = math.sin(local_rad)

            for i in range(start, end + 1):
                x, y = coords[i]
                dx = x - cx
                dy = y - cy
                # Project onto long axis; keep length, carve width.
                proj_long = dx * long_ax + dy * long_ay
                proj_short = -dx * long_ay + dy * long_ax
                proj_long *= long_axis_factor
                proj_short *= short_axis_factor
                shaped_dx = proj_long * long_ax - proj_short * long_ay
                shaped_dy = proj_long * long_ay + proj_short * long_ax
                rx = shaped_dx * local_cos - shaped_dy * local_sin
                ry = shaped_dx * local_sin + shaped_dy * local_cos
                coords[i] = (int(round(cx + rx)), int(round(cy + ry)))

            dot_count += 1
            touched = True
            start = end + 1

        if touched:
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] refined {dot_count} dot contours across {glyph_count} glyphs "
        f"(long={DOT_LONG_AXIS}, soft_long={DOT_LONG_AXIS_SOFT}, "
        f"short={DOT_SHORT_AXIS}, rotate={DOT_ROTATE_DEG}°)"
    )


def refine_black_dot_cluster(font: TTFont) -> None:
    """Protect 黑部点群 from becoming uneven slash-like dots."""
    glyf = font["glyf"]
    cmap = font.getBestCmap() or {}

    dot_count = 0
    touched_chars = []

    for char in BLACK_DOT_CLUSTER_CHARS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours < 2:
            continue

        coords = glyph.coordinates
        all_xs = [coords[i][0] for i in range(len(coords))]
        all_ys = [coords[i][1] for i in range(len(coords))]
        glyph_y_min, glyph_y_max = min(all_ys), max(all_ys)
        glyph_h = glyph_y_max - glyph_y_min
        total_area = (max(all_xs) - min(all_xs)) * glyph_h
        if glyph_h <= 0 or total_area <= 0:
            continue

        touched = False
        start = 0
        for end in glyph.endPtsOfContours:
            n_pts = end - start + 1
            if n_pts < 12 or n_pts > DOT_MAX_POINTS:
                start = end + 1
                continue

            x_min, y_min, x_max, y_max, _ = _contour_bounds(coords, start, end)
            c_w = x_max - x_min
            c_h = y_max - y_min
            if c_w <= 0 or c_h <= 0:
                start = end + 1
                continue

            c_cy = (y_min + y_max) / 2.0
            y_rel = (c_cy - glyph_y_min) / glyph_h
            area_pct = c_w * c_h / total_area * 100.0
            if not (0.20 <= y_rel <= 0.50 and area_pct <= DOT_AREA_PCT * 1.8):
                start = end + 1
                continue

            pts = [coords[i] for i in range(start, end + 1)]
            cx = sum(p[0] for p in pts) / n_pts
            cy = sum(p[1] for p in pts) / n_pts

            long_axis_len_sq = 0.0
            long_ax = 1.0
            long_ay = 0.0
            for a in range(n_pts):
                xa, ya = pts[a]
                for b in range(a + 1, n_pts):
                    dx = pts[b][0] - xa
                    dy = pts[b][1] - ya
                    d2 = dx * dx + dy * dy
                    if d2 > long_axis_len_sq:
                        long_axis_len_sq = d2
                        long_ax, long_ay = dx, dy
            long_len = math.hypot(long_ax, long_ay)
            if long_len < 1e-6:
                start = end + 1
                continue
            long_ax /= long_len
            long_ay /= long_len

            for i in range(start, end + 1):
                x, y = coords[i]
                dx = x - cx
                dy = y - cy
                proj_long = dx * long_ax + dy * long_ay
                proj_short = -dx * long_ay + dy * long_ax
                proj_long *= BLACK_DOT_CLUSTER_LONG_AXIS
                proj_short *= BLACK_DOT_CLUSTER_SHORT_AXIS
                new_x = cx + proj_long * long_ax - proj_short * long_ay
                new_y = cy + proj_long * long_ay + proj_short * long_ax
                coords[i] = (int(round(new_x)), int(round(new_y)))

            dot_count += 1
            touched = True
            start = end + 1

        if touched:
            glyph.recalcBounds(glyf)
            touched_chars.append(char)

    if touched_chars:
        print(
            f"[luo] refined black-dot clusters: {''.join(touched_chars)} "
            f"({dot_count} contours, long={BLACK_DOT_CLUSTER_LONG_AXIS}, "
            f"short={BLACK_DOT_CLUSTER_SHORT_AXIS})"
        )


# --- Pass B: Second hook refinement ---

def refine_hooks_final(font: TTFont) -> None:
    """Second-pass hook tightening on targeted characters."""
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)

    hook_count = 0
    tail_count = 0
    glyph_count = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if not cp:
            continue
        char = chr(cp)
        if char not in HOOK_FINAL_CHARS:
            continue

        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue

        coords = glyph.coordinates
        ends = glyph.endPtsOfContours
        new_coords = list(coords)
        touched = False

        start = 0
        for end in ends:
            n = end - start + 1
            # Skip low-point-count contours: they're rectangles or simple
            # stroke structures (small frames, internal short strokes), not
            # hooks. Real hooks live inside main contours (n=60+) which
            # still get processed.
            if n < 12:
                start = end + 1
                continue

            for j in range(n):
                idx = start + j
                i_prev = start + (j - 1) % n
                i_next = start + (j + 1) % n
                i_next2 = start + (j + 2) % n

                p0 = coords[i_prev]
                p1 = coords[idx]
                p2 = coords[i_next]
                p3 = coords[i_next2]

                d_in = (p1[0] - p0[0], p1[1] - p0[1])
                d_out = (p2[0] - p1[0], p2[1] - p1[1])

                len_in = math.hypot(*d_in)
                len_out = math.hypot(*d_out)
                if len_in < 8 or len_out < 5:
                    continue
                if len_out <= 20:
                    continue

                cos_a = (d_in[0] * d_out[0] + d_in[1] * d_out[1]) / (len_in * len_out)
                cos_a = max(-1.0, min(1.0, cos_a))
                angle = math.degrees(math.acos(cos_a))

                if angle < 60 or angle > 130:
                    continue
                if len_out > 90 or len_in < len_out * 1.5:
                    continue

                new_coords[i_next] = (
                    int(round(p2[0] + HOOK_FINAL_SHORTEN * (p1[0] - p2[0]))),
                    int(round(p2[1] + HOOK_FINAL_SHORTEN * (p1[1] - p2[1]))),
                )

                axis_x = p2[0] - p1[0]
                axis_y = p2[1] - p1[1]
                axis_len = math.hypot(axis_x, axis_y)
                if axis_len > 1e-6:
                    axis_ux = axis_x / axis_len
                    axis_uy = axis_y / axis_len
                    perp_x = -axis_y / axis_len
                    perp_y = axis_x / axis_len
                    for tip_idx in (i_next, i_next2):
                        pt = new_coords[tip_idx]
                        proj = (pt[0] - p1[0]) * perp_x + (pt[1] - p1[1]) * perp_y
                        new_coords[tip_idx] = (
                            int(round(pt[0] - HOOK_FINAL_TIP_SHARPEN * proj * perp_x)),
                            int(round(pt[1] - HOOK_FINAL_TIP_SHARPEN * proj * perp_y)),
                        )
                    tip = new_coords[i_next2]
                    axial = (tip[0] - p1[0]) * axis_ux + (tip[1] - p1[1]) * axis_uy
                    if axial > 0:
                        new_coords[i_next2] = (
                            int(round(tip[0] - HOOK_FINAL_TAIL_CONTAIN * axial * axis_ux)),
                            int(round(tip[1] - HOOK_FINAL_TAIL_CONTAIN * axial * axis_uy)),
                        )
                        tail_count += 1

                hook_count += 1
                touched = True

            start = end + 1

        if touched:
            for i, c in enumerate(new_coords):
                coords[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] final-refined {hook_count} hooks across {glyph_count} glyphs "
        f"(shorten={HOOK_FINAL_SHORTEN}, sharpen={HOOK_FINAL_TIP_SHARPEN}, "
        f"tail={HOOK_FINAL_TAIL_CONTAIN}, contained={tail_count})"
    )


# --- Pass C: Targeted turn refinement ---

def refine_turns_final(font: TTFont) -> None:
    """Add a small bone-node touch on priority endpoint/frame/multi-horiz chars."""
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)

    threshold_rad = math.radians(TURN_FINAL_ANGLE_MAX)
    turn_count = 0
    frame_turn_count = 0
    glyph_count = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if not cp:
            continue
        char = chr(cp)
        if char not in TURN_FINAL_CHARS:
            continue
        is_frame_turn = char in TURN_FINAL_FRAME_CHARS
        seg_max = TURN_FINAL_FRAME_SEG_MAX if is_frame_turn else TURN_FINAL_SEG_MAX
        displace = TURN_FINAL_FRAME_DISPLACE if is_frame_turn else TURN_FINAL_DISPLACE
        inner = TURN_FINAL_FRAME_INNER if is_frame_turn else TURN_FINAL_INNER

        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue

        coords = glyph.coordinates
        flags = glyph.flags
        ends = glyph.endPtsOfContours
        all_xs = [coords[i][0] for i in range(len(coords))]
        all_ys = [coords[i][1] for i in range(len(coords))]
        total_area = (max(all_xs) - min(all_xs)) * (max(all_ys) - min(all_ys))
        new_coords = list(coords)
        touched = False

        start = 0
        for end in ends:
            n = end - start + 1
            if n < 12 or _is_dot_like_contour(coords, start, end, total_area):
                start = end + 1
                continue

            for j in range(n):
                idx = start + j
                if not (flags[idx] & 1):
                    continue

                i_prev = start + (j - 1) % n
                i_next = start + (j + 1) % n

                cx, cy = coords[idx]
                px, py = coords[i_prev]
                nx_pt, ny_pt = coords[i_next]

                dx_in, dy_in = px - cx, py - cy
                dx_out, dy_out = nx_pt - cx, ny_pt - cy

                len_in = math.hypot(dx_in, dy_in)
                len_out = math.hypot(dx_out, dy_out)
                if len_in < TURN_FINAL_SEG_MIN or len_out < TURN_FINAL_SEG_MIN:
                    continue
                if len_in > seg_max or len_out > seg_max:
                    continue

                dot = max(-1.0, min(1.0,
                    (dx_in * dx_out + dy_in * dy_out) / (len_in * len_out)))
                angle = math.acos(dot)
                if angle >= threshold_rad:
                    continue

                v_in_x, v_in_y = dx_in / len_in, dy_in / len_in
                v_out_x, v_out_y = dx_out / len_out, dy_out / len_out
                bis_x = -(v_in_x + v_out_x)
                bis_y = -(v_in_y + v_out_y)
                bis_len = math.hypot(bis_x, bis_y)
                if bis_len < 1e-6:
                    continue

                bis_x /= bis_len
                bis_y /= bis_len

                new_coords[idx] = (
                    int(round(cx + displace * bis_x)),
                    int(round(cy + displace * bis_y)),
                )

                cross = dx_in * dy_out - dy_in * dx_out
                inner_idx = i_next if cross > 0 else i_prev
                ix, iy = new_coords[inner_idx]
                apex_x, apex_y = new_coords[idx]
                new_coords[inner_idx] = (
                    int(round(apex_x + inner * (ix - apex_x))),
                    int(round(apex_y + inner * (iy - apex_y))),
                )

                turn_count += 1
                if is_frame_turn:
                    frame_turn_count += 1
                touched = True

            start = end + 1

        if touched:
            for i, c in enumerate(new_coords):
                coords[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] final-refined {turn_count} turns across {glyph_count} glyphs "
        f"(angle<{TURN_FINAL_ANGLE_MAX}°, displace={TURN_FINAL_DISPLACE}, "
        f"inner={TURN_FINAL_INNER}, frame_displace={TURN_FINAL_FRAME_DISPLACE}, "
        f"frame_inner={TURN_FINAL_FRAME_INNER}, frame_seg_max={TURN_FINAL_FRAME_SEG_MAX}, "
        f"frame_turns={frame_turn_count})"
    )


# --- Dead-code Pass C: Bone turn refinement ---

def refine_bone_turns(font: TTFont) -> None:
    """Add bone-node quality at sharp direction changes."""
    glyf = font["glyf"]
    cmap = _build_cmap(font)

    threshold_rad = math.radians(BONE_TURN_ANGLE_MAX)
    turn_count = 0
    glyph_count = 0

    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue
        if not _is_cjk_glyph(name, cmap):
            continue

        coords = glyph.coordinates
        flags = glyph.flags
        ends = glyph.endPtsOfContours
        new_coords = list(coords)
        touched = False

        start = 0
        for end in ends:
            n = end - start + 1
            if n < 4:
                start = end + 1
                continue

            for j in range(n):
                idx = start + j
                if not (flags[idx] & 1):
                    continue

                i_prev = start + (j - 1) % n
                i_next = start + (j + 1) % n

                cx, cy = coords[idx]
                px, py = coords[i_prev]
                nx_pt, ny_pt = coords[i_next]

                dx_in, dy_in = px - cx, py - cy
                dx_out, dy_out = nx_pt - cx, ny_pt - cy

                len_in = math.hypot(dx_in, dy_in)
                len_out = math.hypot(dx_out, dy_out)
                if len_in < BONE_TURN_SEG_MIN or len_in > BONE_TURN_SEG_MAX:
                    continue
                if len_out < BONE_TURN_SEG_MIN or len_out > BONE_TURN_SEG_MAX:
                    continue

                dot = max(-1.0, min(1.0,
                    (dx_in * dx_out + dy_in * dy_out) / (len_in * len_out)))
                angle = math.acos(dot)
                if angle >= threshold_rad:
                    continue

                ang_in = abs(math.atan2(dy_in, dx_in))
                ang_out = abs(math.atan2(dy_out, dx_out))
                is_h_in = ang_in < 0.26 or ang_in > 2.88
                is_v_in = 1.31 < ang_in < 1.83
                is_h_out = ang_out < 0.26 or ang_out > 2.88
                is_v_out = 1.31 < ang_out < 1.83
                if (is_h_in or is_v_in) and (is_h_out or is_v_out):
                    continue

                v_in_x, v_in_y = dx_in / len_in, dy_in / len_in
                v_out_x, v_out_y = dx_out / len_out, dy_out / len_out
                bis_x = -(v_in_x + v_out_x)
                bis_y = -(v_in_y + v_out_y)
                bis_len = math.hypot(bis_x, bis_y)
                if bis_len < 1e-6:
                    continue

                bis_x /= bis_len
                bis_y /= bis_len

                new_coords[idx] = (
                    int(round(cx + BONE_TURN_DISPLACE * bis_x)),
                    int(round(cy + BONE_TURN_DISPLACE * bis_y)),
                )

                cross = dx_in * dy_out - dy_in * dx_out
                inner_idx = i_next if cross > 0 else i_prev
                ix, iy = new_coords[inner_idx]
                apex_x, apex_y = new_coords[idx]
                new_coords[inner_idx] = (
                    int(round(apex_x + BONE_TURN_INNER_REDUCE * (ix - apex_x))),
                    int(round(apex_y + BONE_TURN_INNER_REDUCE * (iy - apex_y))),
                )

                turn_count += 1
                touched = True

            start = end + 1

        if touched:
            for i, c in enumerate(new_coords):
                coords[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] refined {turn_count} bone turns across {glyph_count} glyphs "
        f"(displace={BONE_TURN_DISPLACE}, inner={BONE_TURN_INNER_REDUCE})"
    )


# --- Pass D: Stroke taper refinement ---

def refine_stroke_taper(font: TTFont) -> None:
    """Taper stroke endings for clean containment."""
    glyf = font["glyf"]
    cmap = _build_cmap(font)

    taper_points = 0
    glyph_count = 0

    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue
        if not _is_cjk_glyph(name, cmap):
            continue

        coords = glyph.coordinates
        flags = glyph.flags
        ends = glyph.endPtsOfContours
        new_coords = list(coords)
        touched = False

        start = 0
        for end in ends:
            n = end - start + 1
            if n < TAPER_MIN_CONTOUR_PTS:
                start = end + 1
                continue

            c_xs = [coords[i][0] for i in range(start, end + 1)]
            c_ys = [coords[i][1] for i in range(start, end + 1)]
            cx = sum(c_xs) / n
            cy = sum(c_ys) / n

            arc_lengths = [0.0]
            for k in range(1, n):
                dx = coords[start + k][0] - coords[start + k - 1][0]
                dy = coords[start + k][1] - coords[start + k - 1][1]
                arc_lengths.append(arc_lengths[-1] + math.hypot(dx, dy))
            total_arc = arc_lengths[-1]
            if total_arc < 1e-6:
                start = end + 1
                continue

            threshold = total_arc * TAPER_ARC_PCT

            for k in range(n):
                idx = start + k
                arc = arc_lengths[k]

                if arc < threshold:
                    t = 1.0 - arc / threshold
                elif arc > total_arc - threshold:
                    t = (arc - (total_arc - threshold)) / threshold
                else:
                    continue

                i_prev = start + (k - 1) % n
                i_next = start + (k + 1) % n
                px, py = coords[i_prev]
                nx_pt, ny_pt = coords[i_next]
                dx_s = nx_pt - px
                dy_s = ny_pt - py
                seg_ang = abs(math.atan2(dy_s, dx_s))

                x, y = coords[idx]
                dx_in = coords[idx][0] - px
                dy_in = coords[idx][1] - py
                dx_out = nx_pt - coords[idx][0]
                dy_out = ny_pt - coords[idx][1]
                len_a = math.hypot(dx_in, dy_in)
                len_b = math.hypot(dx_out, dy_out)
                if len_a > 1e-6 and len_b > 1e-6:
                    dot_val = (dx_in * dx_out + dy_in * dy_out) / (len_a * len_b)
                    dot_val = max(-1.0, min(1.0, dot_val))
                    local_angle = math.degrees(math.acos(dot_val))
                    is_h = seg_ang < 0.26 or seg_ang > 2.88
                    is_v = 1.31 < seg_ang < 1.83
                    if 75 < local_angle < 105 and (is_h or is_v):
                        continue

                factor = 1.0 - TAPER_INWARD * t
                new_x = cx + (x - cx) * factor
                new_y = cy + (y - cy) * factor
                new_coords[idx] = (int(round(new_x)), int(round(new_y)))
                taper_points += 1
                touched = True

            start = end + 1

        if touched:
            for i, c in enumerate(new_coords):
                coords[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] tapered {taper_points} stroke endpoints across {glyph_count} glyphs "
        f"(arc={TAPER_ARC_PCT:.0%}, inward={TAPER_INWARD})"
    )


# --- Pass E: Heart character refinement ---

def refine_heart_chars(font: TTFont) -> None:
    """Reshape heart-bottom dots and reclining hook for xiaokai feel."""
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm

    dot_count = 0
    hook_count = 0
    glyph_count = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if not cp:
            continue
        char = chr(cp)
        if char not in HEART_CHARS:
            continue

        glyph = glyf[gname]
        if glyph.numberOfContours < 2:
            continue

        coords = glyph.coordinates
        ends = list(glyph.endPtsOfContours)
        all_ys = [coords[i][1] for i in range(len(coords))]
        all_xs = [coords[i][0] for i in range(len(coords))]
        y_mid = (min(all_ys) + max(all_ys)) / 2.0
        glyph_cx = (min(all_xs) + max(all_xs)) / 2.0
        total_area = (max(all_xs) - min(all_xs)) * (max(all_ys) - min(all_ys))
        if total_area <= 0:
            continue

        contour_info = []
        start = 0
        for ci, end in enumerate(ends):
            c_xs = [coords[i][0] for i in range(start, end + 1)]
            c_ys = [coords[i][1] for i in range(start, end + 1)]
            c_cx = sum(c_xs) / len(c_xs)
            c_cy = sum(c_ys) / len(c_ys)
            c_w = max(c_xs) - min(c_xs)
            c_h = max(c_ys) - min(c_ys)
            c_area = c_w * c_h
            contour_info.append({
                "idx": ci, "start": start, "end": end,
                "cx": c_cx, "cy": c_cy,
                "area": c_area, "pct": c_area / total_area * 100,
                "xmin": min(c_xs),
            })
            start = end + 1

        is_standalone = char == "心"
        dot_long_axis = HEART_STANDALONE_DOT_LONG_AXIS if is_standalone else HEART_DOT_LONG_AXIS
        dot_short_axis = HEART_STANDALONE_DOT_SHORT_AXIS if is_standalone else HEART_DOT_SHORT_AXIS
        dot_spacing = HEART_STANDALONE_DOT_SPACING if is_standalone else HEART_DOT_SPACING
        hook_shorten = HEART_STANDALONE_HOOK_SHORTEN if is_standalone else HEART_HOOK_SHORTEN
        hook_tail_contain = HEART_STANDALONE_HOOK_TAIL_CONTAIN if is_standalone else 0.0

        if is_standalone:
            bottom_contours = contour_info
        else:
            bottom_contours = [c for c in contour_info if c["cy"] < y_mid]

        if not bottom_contours:
            continue

        hook_contour = max(bottom_contours, key=lambda c: c["area"])
        dot_contours = sorted(
            [c for c in bottom_contours
             if c["idx"] != hook_contour["idx"] and c["pct"] < 12],
            key=lambda c: c["cx"],
        )

        touched = False

        for di, dc in enumerate(dot_contours):
            s, e = dc["start"], dc["end"]
            n_pts = e - s + 1
            dc_cx = dc["cx"]
            dc_cy = dc["cy"]

            if di == 0:
                rot_deg = HEART_DOT_ANGLE
            elif di == len(dot_contours) - 1:
                rot_deg = -HEART_DOT_ANGLE * 0.5
            else:
                rot_deg = HEART_DOT_ANGLE * 0.6

            rad = math.radians(rot_deg)
            cos_r = math.cos(rad)
            sin_r = math.sin(rad)

            offset_x = (dc_cx - glyph_cx) * (dot_spacing - 1.0)
            is_left_standalone_dot = is_standalone and di == 0
            is_right_standalone_dot = is_standalone and di == len(dot_contours) - 1
            if is_left_standalone_dot:
                offset_x += (dc_cx - glyph_cx) * HEART_STANDALONE_LEFT_DOT_OUTSET
            elif is_right_standalone_dot:
                offset_x -= (dc_cx - glyph_cx) * HEART_STANDALONE_RIGHT_DOT_INSET

            d_xs = [coords[i][0] for i in range(s, e + 1)]
            d_ys = [coords[i][1] for i in range(s, e + 1)]
            long_axis_len_sq = 0.0
            long_ax = 1.0
            long_ay = 0.0
            for a in range(n_pts):
                xa, ya = d_xs[a], d_ys[a]
                for b in range(a + 1, n_pts):
                    dxv = d_xs[b] - xa
                    dyv = d_ys[b] - ya
                    d2 = dxv * dxv + dyv * dyv
                    if d2 > long_axis_len_sq:
                        long_axis_len_sq = d2
                        long_ax, long_ay = dxv, dyv
            long_len = math.hypot(long_ax, long_ay)
            if long_len < 1e-6:
                continue
            long_ax /= long_len
            long_ay /= long_len

            for i in range(s, e + 1):
                x, y = coords[i]
                dx = x - dc_cx
                dy = y - dc_cy
                proj_long = dx * long_ax + dy * long_ay
                proj_short = -dx * long_ay + dy * long_ax
                if is_right_standalone_dot:
                    proj_long *= HEART_STANDALONE_RIGHT_DOT_LONG_SCALE
                proj_long *= dot_long_axis
                proj_short *= dot_short_axis
                shaped_dx = proj_long * long_ax - proj_short * long_ay
                shaped_dy = proj_long * long_ay + proj_short * long_ax
                rx = shaped_dx * cos_r - shaped_dy * sin_r
                ry = shaped_dx * sin_r + shaped_dy * cos_r
                extra_y = HEART_STANDALONE_RIGHT_DOT_RAISE_EM * upm if is_right_standalone_dot else 0
                coords[i] = (int(round(dc_cx + rx + offset_x)), int(round(dc_cy + ry + extra_y)))

            dot_count += 1
            touched = True

        hc = hook_contour
        hs, he = hc["start"], hc["end"]
        h_xs = [coords[i][0] for i in range(hs, he + 1)]
        h_ys = [coords[i][1] for i in range(hs, he + 1)]
        h_xmin = min(h_xs)
        h_xmax = max(h_xs)
        h_xrange = h_xmax - h_xmin
        if h_xrange > 0:
            cutoff = h_xmin + h_xrange * 0.3
            for i in range(hs, he + 1):
                x, y = coords[i]
                if x < cutoff:
                    t = 1.0 - (x - h_xmin) / (cutoff - h_xmin) if cutoff > h_xmin else 0
                    pull = hook_shorten * t
                    coords[i] = (int(round(x + pull * (h_xmax - x))), y)
                elif hook_tail_contain > 0 and x > h_xmax - h_xrange * 0.22:
                    tail_start = h_xmax - h_xrange * 0.22
                    t = (x - tail_start) / (h_xmax - tail_start) if h_xmax > tail_start else 0
                    pull = hook_tail_contain * t
                    coords[i] = (int(round(x - pull * (x - h_xmin))), y)
            if is_standalone and HEART_STANDALONE_HOOK_STEM_THICKEN > 0:
                h_ymin = min(h_ys)
                h_ymax = max(h_ys)
                h_yrange = h_ymax - h_ymin
                h_cx = (h_xmin + h_xmax) / 2.0
                tail_start = h_xmax - h_xrange * 0.22
                stem_y0 = h_ymin + h_yrange * 0.30 if h_yrange > 0 else h_ymin
                for i in range(hs, he + 1):
                    x, y = coords[i]
                    if y <= stem_y0 or x >= tail_start or h_ymax <= stem_y0:
                        continue
                    t = (y - stem_y0) / (h_ymax - stem_y0)
                    factor = 1.0 + HEART_STANDALONE_HOOK_STEM_THICKEN * t
                    coords[i] = (int(round(h_cx + (x - h_cx) * factor)), y)
            hook_count += 1
            touched = True

        if is_standalone and HEART_STANDALONE_HOOK_SHIFT_X_EM != 0:
            shift_x = int(round(HEART_STANDALONE_HOOK_SHIFT_X_EM * upm))
            for i in range(hs, he + 1):
                x, y = coords[i]
                coords[i] = (x + shift_x, y)
            touched = True

        if is_standalone and HEART_STANDALONE_RAISE_EM != 0:
            raise_y = int(round(HEART_STANDALONE_RAISE_EM * upm))
            for i in range(len(coords)):
                x, y = coords[i]
                coords[i] = (x, y + raise_y)
            touched = True

        if touched:
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] refined {dot_count} heart dots + {hook_count} hooks "
        f"across {glyph_count} glyphs "
        f"(long={HEART_DOT_LONG_AXIS}, short={HEART_DOT_SHORT_AXIS}, "
        f"angle={HEART_DOT_ANGLE}°, spacing={HEART_DOT_SPACING}, "
        f"hook={HEART_HOOK_SHORTEN}; standalone_long={HEART_STANDALONE_DOT_LONG_AXIS}, "
        f"standalone_short={HEART_STANDALONE_DOT_SHORT_AXIS}, "
        f"standalone_spacing={HEART_STANDALONE_DOT_SPACING}, "
        f"standalone_hook={HEART_STANDALONE_HOOK_SHORTEN}, "
        f"standalone_tail={HEART_STANDALONE_HOOK_TAIL_CONTAIN}, "
        f"standalone_raise={HEART_STANDALONE_RAISE_EM}, "
        f"standalone_left_outset={HEART_STANDALONE_LEFT_DOT_OUTSET}, "
        f"standalone_right_inset={HEART_STANDALONE_RIGHT_DOT_INSET}, "
        f"standalone_right_long={HEART_STANDALONE_RIGHT_DOT_LONG_SCALE}, "
        f"standalone_right_raise={HEART_STANDALONE_RIGHT_DOT_RAISE_EM}, "
        f"standalone_hook_shift={HEART_STANDALONE_HOOK_SHIFT_X_EM}, "
        f"standalone_stem={HEART_STANDALONE_HOOK_STEM_THICKEN})"
    )


def fit_punctuation_width(font: TTFont, width_ratio: float) -> None:
    """Compress CJK punctuation advances and keep marks close to preceding text."""
    glyf = font["glyf"]
    hmtx = font["hmtx"]

    cmap = {}
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                cmap.update(table.cmap)

    count = 0
    for name in font.getGlyphOrder():
        if not _is_cjk_punctuation_glyph(name, cmap):
            continue

        adv, _lsb = hmtx[name]
        target_adv = max(320, int(round(adv * width_ratio)))
        glyph = glyf[name]

        if glyph.numberOfContours > 0:
            glyph.recalcBounds(glyf)
            left_padding = max(40, int(round(target_adv * 0.16)))
            dx = int(round(left_padding - glyph.xMin))
            coords = glyph.coordinates
            for i in range(len(coords)):
                x, y = coords[i]
                coords[i] = (x + dx, y)
            glyph.recalcBounds(glyf)
            hmtx[name] = (target_adv, glyph.xMin)
        else:
            hmtx[name] = (target_adv, 0)
        count += 1

    print(f"[luo] fitted {count} CJK punctuation glyphs to {width_ratio:.2f}em")


def adjust_space_width(font: TTFont, ratio: float) -> None:
    """Set space advance to a fraction of its current width."""
    hmtx = font["hmtx"]
    cmap = {}
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                cmap.update(table.cmap)

    space_name = cmap.get(0x20)
    if not space_name or space_name not in hmtx.metrics:
        print("[luo] space glyph not found, skipping")
        return

    adv, lsb = hmtx[space_name]
    new_adv = int(round(adv * ratio))
    hmtx[space_name] = (new_adv, lsb)
    print(f"[luo] space width: {adv} -> {new_adv} ({ratio:.0%})")


def adjust_cjk_spacing(font: TTFont) -> None:
    """Graduated CJK advance width scaling: more contours = more breathing room."""
    glyf = font["glyf"]
    hmtx = font["hmtx"]

    cmap = {}
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                cmap.update(table.cmap)

    factor_hist: dict[str, int] = {}
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue
        if not _is_cjk_glyph(name, cmap):
            continue
        if _is_cjk_punctuation_glyph(name, cmap):
            continue

        factor = _spacing_factor(glyph)
        key = f"{factor:.3f}"
        factor_hist[key] = factor_hist.get(key, 0) + 1

        adv, _lsb = hmtx[name]
        new_adv = int(round(adv * factor))
        shift = (new_adv - adv) // 2

        if shift > 0:
            coords = glyph.coordinates
            for i in range(len(coords)):
                x, y = coords[i]
                coords[i] = (x + shift, y)
            glyph.recalcBounds(glyf)

        hmtx[name] = (new_adv, glyph.xMin)

    total = sum(factor_hist.values())
    dist = " | ".join(f"×{k}: {v}" for k, v in sorted(factor_hist.items()))
    print(f"[luo] adjusted spacing for {total} CJK glyphs (graduated)")
    print(f"[luo]   spacing distribution: {dist}")


def rewrite_names(font: TTFont) -> None:
    full_name = f"{FAMILY} {SUBFAMILY}"
    ps_name = f"{FAMILY}-{SUBFAMILY}"
    unique_id = f"{ps_name};{VERSION};{datetime.now(timezone.utc):%Y%m%d}"

    records = {
        0: COPYRIGHT,
        1: FAMILY,
        2: SUBFAMILY,
        3: unique_id,
        4: full_name,
        5: f"Version {VERSION}",
        6: ps_name,
        8: "Luo project authors",
        9: "Luo project authors",
        11: "https://github.com/tw93/luo",
        12: "https://github.com/tw93/luo",
        13: LICENSE_TEXT,
        14: LICENSE_URL,
        16: FAMILY,
        17: SUBFAMILY,
    }

    if "OS/2" in font:
        font["OS/2"].achVendID = "LUO "

    name_table = font["name"]
    name_table.names = []
    for name_id, value in records.items():
        name_table.setName(value, name_id, 3, 1, 0x409)
        name_table.setName(value, name_id, 1, 0, 0)

    print(f"[luo] rewrote name table -> {full_name}")


def save_outputs(font: TTFont) -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    otf_path = DIST_DIR / f"{OUTPUT_PREFIX}.otf"
    ttf_path = DIST_DIR / f"{OUTPUT_PREFIX}.ttf"
    woff2_path = DIST_DIR / f"{OUTPUT_PREFIX}.woff2"

    font.flavor = None
    font.save(str(otf_path))
    print(f"[luo] wrote {otf_path.relative_to(ROOT)}")

    font.save(str(ttf_path))
    print(f"[luo] wrote {ttf_path.relative_to(ROOT)}")

    font.flavor = "woff2"
    font.save(str(woff2_path))
    print(f"[luo] wrote {woff2_path.relative_to(ROOT)}")


SEED_CHARS = "永国家文字设计用爱心回馈社会开源工具写纸技书妙言清理终端旅行潮流骨筋端章印排版兰亭集序"

# Starter mode is the first usable web/print subset. It covers all local
# sample pages plus a compact set of high-frequency Simplified Chinese chars.
STARTER_FILES = (
    ROOT / "index.html",
    ROOT / "proof" / "a4.html",
    ROOT / "README.md",
)

LANTING_TEXT = """
永和九年，岁在癸丑，暮春之初，会于会稽山阴之兰亭，修禊事也。
群贤毕至，少长咸集。此地有崇山峻岭，茂林修竹，又有清流激湍，
映带左右，引以为流觞曲水，列坐其次。虽无丝竹管弦之盛，一觞一咏，
亦足以畅叙幽情。
是日也，天朗气清，惠风和畅。仰观宇宙之大，俯察品类之盛，
所以游目骋怀，足以极视听之娱，信可乐也。
夫人之相与，俯仰一世。或取诸怀抱，悟言一室之内；
或因寄所托，放浪形骸之外。虽趣舍万殊，静躁不同，
当其欣于所遇，暂得于己，快然自足，不知老之将至。
及其所之既倦，情随事迁，感慨系之矣。向之所欣，
俯仰之间，已为陈迹，犹不能不以之兴怀。况修短随化，
终期于尽。古人云：死生亦大矣。岂不痛哉！
每览昔人兴感之由，若合一契，未尝不临文嗟悼，不能喻之于怀。
固知一死生为虚诞，齐彭殇为妄作。后之视今，亦犹今之视昔。
悲夫！故列叙时人，录其所述，虽世殊事异，所以兴怀，其致一也。
后之览者，亦将有感于斯文。
"""

COMMON_STARTER_CHARS = """
的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就
分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民
得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两
体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那
社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或
但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已
通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求
老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几
九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百
规热领七海口东导器压志世金增争济阶油思术极交受联认六共权收证
改清美再采转更单风切打白教速花带安场身车例真务具万每目至达走
积示议声报斗完类八离华名确才科张信马节话米整空元况今集温传土
许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容
儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感
劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲
快效斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火
住调满县局照参红细引听该铁价严龙飞未试息肉请级您初习许源落纸
阅读出版字体风骨温润端正清朗长文短句标题页面设计开源工具系统
"""

PRIORITY_GROUPS: dict[str, str] = {
    "core_anchors": "落文字书心清骨风纸印国回月雨霜藏魔赢道远家亭序集章兰永天玄黄",
    "point_marks": "清润源落读说语社视意念终寒露霜霞",
    "hooks": "字书亭序家设计排版印旅妙馈成式透远道遇",
    "endpoints": "落纸风骨短版排印集章源雅舒服规则",
    "multi_horiz": "章言书骨兰量重墨春青善美黄宇宙寒暑律吕",
    "frames": "国回图园日目用月田间问阅品亭曾会",
    "dense_complex": "落藏霞霜露馈赢耀魔读题额锦继续源族章集端筋群贤禊觞湍幽怀籍麟",
    "heart_checks": "心必思意念想感悲惠慨悟志怀愿恩愁惊慎忠忽怠忍",
    "homepage_display": "以文为名字落纸取法卫夫人见风骨纸上得来终觉浅字里行间答案魏晋书风入笔形气韵端正不媚不失内筋温润发冷板结排版纸面耐读文字文气炫技装饰大字小字秩序落笔见心横轻竖重圆尖软争声色第一行安静陪读天地玄黄宇宙洪荒重心灰度稳定长文阅读旧笔意新纸面",
    "text_controls": "耐长使用方式首页样张部件校准展示标题开源打包想法交给得上人愿点奇生所好换息世事香天地玄黄洪荒月盈昃辰宿来往秋收冬藏闰余成岁云腾致雨结金丽水玉出永和年春稽山阴修毕至少咸茂林竹流激映带曲畅叙情常用字田字格覆盖优化待补打印输出验证",
}

PRIORITY_CHARS = "".join(dict.fromkeys("".join(PRIORITY_GROUPS.values())))


def cjk_from_text(text: str) -> str:
    chars = re.findall(r"[\u3000-\u303f\ufe10-\ufe4f\uff01-\uff60\u3400-\u4dbf\u4e00-\u9fff]", text)
    return "".join(dict.fromkeys(chars))


def chars_from_files(paths: tuple[Path, ...]) -> str:
    chunks: list[str] = []
    for path in paths:
        if not path.exists():
            sys.exit(f"[luo] required text file not found: {path}")
        chunks.append(cjk_from_text(path.read_text(encoding="utf-8")))
    return "".join(dict.fromkeys("".join(chunks)))


def is_gb2312_cjk(ch: str) -> bool:
    cp = ord(ch)
    return 0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF


def gb2312_chars() -> tuple[str, str, str]:
    """Return GB2312 level-1, level-2, and combined CJK characters."""
    level1: list[str] = []
    level2: list[str] = []
    for high in range(0xB0, 0xD8):
        for low in range(0xA1, 0xFF):
            try:
                ch = bytes((high, low)).decode("gb2312")
            except UnicodeDecodeError:
                continue
            if len(ch) == 1 and is_gb2312_cjk(ch):
                level1.append(ch)
    for high in range(0xD8, 0xF8):
        for low in range(0xA1, 0xFF):
            try:
                ch = bytes((high, low)).decode("gb2312")
            except UnicodeDecodeError:
                continue
            if len(ch) == 1 and is_gb2312_cjk(ch):
                level2.append(ch)
    all_chars = "".join(dict.fromkeys(level1 + level2))
    if len(all_chars) != 6763:
        sys.exit(f"[luo] expected 6763 GB2312 chars, got {len(all_chars)}")
    return "".join(level1), "".join(level2), all_chars


def site_chars() -> str:
    chars = "".join(dict.fromkeys(SEED_CHARS + chars_from_files((ROOT / "index.html",))))
    print(f"[luo] collected {len(chars)} CJK chars from index.html")
    return chars


def starter_chars() -> str:
    chars = "".join(
        dict.fromkeys(
            SEED_CHARS
            + cjk_from_text(LANTING_TEXT)
            + cjk_from_text(COMMON_STARTER_CHARS)
            + PRIORITY_CHARS
            + chars_from_files(STARTER_FILES)
        )
    )
    print(f"[luo] collected {len(chars)} CJK chars for starter subset")
    return chars


def gb2312_level1_chars() -> str:
    gb_level1, _, _ = gb2312_chars()
    chars = "".join(dict.fromkeys(starter_chars() + gb_level1))
    print(f"[luo] collected {len(chars)} CJK chars for GB2312 level-1 subset")
    return chars


def gb2312_full_chars() -> str:
    _, _, gb_chars = gb2312_chars()
    chars = "".join(dict.fromkeys(starter_chars() + gb_chars))
    print(f"[luo] collected {len(chars)} CJK chars for GB2312 full subset")
    return chars


def subset_to_seed(font: TTFont, chars: str) -> None:
    from fontTools.subset import Subsetter, Options
    opts = Options()
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.recommended_glyphs = True
    opts.glyph_names = True
    opts.drop_tables = ["DSIG"]
    opts.hinting = False
    sub = Subsetter(options=opts)
    sub.populate(text=chars + " ")
    sub.subset(font)
    print(f"[luo] subset to {len(chars)} requested chars")


def font_codepoints(font: TTFont) -> set[int]:
    cps: set[int] = set()
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                cps.update(table.cmap)
    return cps


def validate_required_chars(font: TTFont, chars: str, label: str) -> None:
    covered = font_codepoints(font)
    missing = "".join(ch for ch in chars if ord(ch) not in covered)
    if missing:
        preview = missing[:120]
        sys.exit(
            f"[luo] missing {len(missing)} required chars for {label}:\n"
            f"       {preview}"
        )
    print(f"[luo] coverage ok for {label}: {len(chars)} chars")


def write_debug_reports(font: TTFont, requested_chars: str) -> None:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    covered = font_codepoints(font)
    covered_chars = "".join(ch for ch in requested_chars if ord(ch) in covered)
    missing_chars = "".join(ch for ch in requested_chars if ord(ch) not in covered)
    optimized = "".join(ch for ch in covered_chars if _char_category(ch))
    unoptimized = "".join(ch for ch in covered_chars if not _char_category(ch))

    by_category: dict[str, int] = {}
    for ch in covered_chars:
        cat = _char_category(ch)
        if cat:
            by_category[cat] = by_category.get(cat, 0) + 1

    priority_groups = {
        name: {
            "chars": chars,
            "count": len(chars),
            "missing": "".join(ch for ch in chars if ord(ch) not in covered),
        }
        for name, chars in PRIORITY_GROUPS.items()
    }

    report = {
        "build_mode": BUILD_CHARS,
        "requested_unique_chars": len(requested_chars),
        "covered_count": len(covered_chars),
        "missing_count": len(missing_chars),
        "optimized_count": len(optimized),
        "unoptimized_count": len(unoptimized),
        "coverage_rate": (
            f"{len(covered_chars) / len(requested_chars) * 100:.1f}%"
            if requested_chars else "100.0%"
        ),
        "by_category": dict(sorted(by_category.items())),
        "priority_groups": priority_groups,
        "missing_chars": missing_chars,
        "top_unoptimized": unoptimized[:160],
    }

    (PROOF_DIR / "page_chars.txt").write_text(covered_chars, encoding="utf-8")
    (PROOF_DIR / "optimized_chars.txt").write_text(optimized, encoding="utf-8")
    (PROOF_DIR / "unoptimized_chars.txt").write_text(unoptimized, encoding="utf-8")
    (PROOF_DIR / "missing_chars.txt").write_text(missing_chars, encoding="utf-8")
    report_json = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (PROOF_DIR / "coverage_report.json").write_text(report_json, encoding="utf-8")
    (PROOF_DIR / "page_coverage_report.json").write_text(report_json, encoding="utf-8")
    (PROOF_DIR / "priority_groups.json").write_text(
        json.dumps(priority_groups, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[luo] wrote proof coverage: {len(covered_chars)}/"
        f"{len(requested_chars)} chars, optimized={len(optimized)}"
    )


def main() -> None:
    font = load_font(BASE_FONT)
    requested_chars = ""
    required_chars = ""

    if BUILD_CHARS == "seed":
        requested_chars = SEED_CHARS
        subset_to_seed(font, requested_chars)
        required_chars = requested_chars
    elif BUILD_CHARS == "site":
        requested_chars = site_chars()
        subset_to_seed(font, requested_chars)
        required_chars = requested_chars
    elif BUILD_CHARS == "starter":
        requested_chars = starter_chars()
        subset_to_seed(font, requested_chars)
        required_chars = chars_from_files(STARTER_FILES)
    elif BUILD_CHARS == "gb2312-level1":
        requested_chars = gb2312_level1_chars()
        subset_to_seed(font, requested_chars)
        required_chars = requested_chars
    elif BUILD_CHARS == "gb2312-full":
        requested_chars = gb2312_full_chars()
        subset_to_seed(font, requested_chars)
        required_chars = requested_chars
    elif BUILD_CHARS == "full":
        print(f"[luo] keeping all {len(font.getGlyphOrder())} glyphs")
        requested_chars = starter_chars()
        required_chars = chars_from_files(STARTER_FILES)
    else:
        modes = ", ".join(repr(mode) for mode in BUILD_CHAR_MODES)
        sys.exit(f"[luo] LUO_BUILD_CHARS must be one of: {modes}")

    # Boldening: direction-aware or legacy single-value
    if BOLDEN_DELTA is not None:
        d = float(BOLDEN_DELTA)
        bolden_glyphs(font, d, d)
    else:
        bolden_glyphs(font, BOLDEN_H, BOLDEN_V)

    soften_endpoints(font)
    # refine_hooks (initial) removed: its 60-130° angle + long-in/short-out
    # detection cannot distinguish 顿点 (LXGW stroke head/tail thickness) from
    # real hooks. Visible artifacts: 木字旁 vertical top sprouts a triangle,
    # 金 人字头 protrusion gets exaggerated, 横画 ends grow barbs. Genuine hook
    # tightening for 31 hand-curated chars happens later in refine_hooks_final.
    # Function kept as dead code at line ~426 for future per-character reuse.

    # Narrowing: legacy single-value or complexity-aware
    if NARROW_X is not None:
        nx = float(NARROW_X)
        narrow_and_scale(font, nx, nx, nx, SCALE_Y)
    else:
        narrow_and_scale(font, NARROW_SIMPLE, NARROW_REGULAR, NARROW_COMPLEX, SCALE_Y)

    refine_by_category(font)
    refine_heart_chars(font)
    refine_dot_contours(font)
    refine_turns_final(font)
    refine_black_dot_cluster(font)
    refine_hooks_final(font)
    refine_walk_final(font)
    refine_display_anchor_chars(font)
    # refine_stroke_taper / refine_bone_turns removed: geometric heuristics
    # cannot distinguish 骨节 (e.g. 日 corners, should bulge) from 末端
    # (e.g. hook tips, should stay clean) — same local geometry, opposite
    # calligraphic intent. Functions kept for future character-level reuse.
    fit_punctuation_width(font, PUNCT_WIDTH_RATIO)
    adjust_space_width(font, SPACE_WIDTH_RATIO)
    adjust_cjk_spacing(font)
    rewrite_names(font)
    validate_required_chars(font, required_chars, BUILD_CHARS)
    write_debug_reports(font, requested_chars)
    save_outputs(font)
    print("[luo] done.")


if __name__ == "__main__":
    main()
