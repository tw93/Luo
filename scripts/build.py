"""
Luo font builder.

Pipeline:
  1. Load the source TTF.
  2. Subset to starter/site/seed characters.
  3. Graduated stroke thickening (横细竖重, contour-scaled).
  4. Endpoint softening (硬切 -> 软切).
  5. Hook refinement (钩根减重, 钩身缩短, 钩尖减轻).
  6. Complexity-aware horizontal narrowing + vertical scaling.
  7. Component-aware refinement (6 categories).
  8. CJK punctuation + space + spacing.
  9. Rewrite name table -> Luo.
 10. Write Luo-Regular.otf/.ttf/.woff2 into dist/.

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
NARROW_SIMPLE = float(os.environ.get("LUO_NARROW_SIMPLE", "0.995"))   # 简字几乎不收，大方舒展
NARROW_REGULAR = float(os.environ.get("LUO_NARROW_REGULAR", "0.965")) # 常规字微收，保持端正
NARROW_COMPLEX = float(os.environ.get("LUO_NARROW_COMPLEX", "0.935")) # 复杂字适度收，不挤不糊
# Legacy single-value override; if set, disables complexity split.
NARROW_X = os.environ.get("LUO_NARROW_X")

# Contour thresholds for classifying CJK glyph complexity.
COMPLEXITY_SIMPLE_MAX = int(os.environ.get("LUO_COMPLEXITY_SIMPLE", "3"))
COMPLEXITY_COMPLEX_MIN = int(os.environ.get("LUO_COMPLEXITY_COMPLEX", "8"))

# --- Vertical scaling ---
SCALE_Y = float(os.environ.get("LUO_SCALE_Y", "1.05"))

# --- Punctuation ---
# Tsanger-style proportional CJK punctuation: keep the marks compact instead
# of leaving fullwidth punctuation gaps in running text.
PUNCT_WIDTH_RATIO = float(os.environ.get("LUO_PUNCT_WIDTH", "0.75"))

# --- Boldening ---
# Direction-aware: horizontal strokes get less delta, vertical strokes more,
# producing the 横细竖重 feel without uniform fattening.
BOLDEN_H = float(os.environ.get("LUO_BOLDEN_H", "6"))   # 横画恢复分量，不能发虚
BOLDEN_V = float(os.environ.get("LUO_BOLDEN_V", "15"))  # 竖重保持
# Legacy single-value override.
BOLDEN_DELTA = os.environ.get("LUO_BOLDEN")
# Graduated boldening: reduce delta as contour count rises.
BOLDEN_GRAD_STEP = float(os.environ.get("LUO_BOLDEN_GRAD_STEP", "0.06"))
BOLDEN_GRAD_FLOOR = float(os.environ.get("LUO_BOLDEN_GRAD_FLOOR", "0.85"))
BOLDEN_GRAD_ONSET = int(os.environ.get("LUO_BOLDEN_GRAD_ONSET", "3"))

# Endpoint softening (软切角): round sharp corners after boldening.
SOFTEN_ANGLE = float(os.environ.get("LUO_SOFTEN_ANGLE", "130"))
SOFTEN_BLEND = float(os.environ.get("LUO_SOFTEN_BLEND", "0.08"))
SOFTEN_SEG_MAX = float(os.environ.get("LUO_SOFTEN_SEG_MAX", "80"))

# Space width: half-width space for tighter CJK typesetting.
SPACE_WIDTH_RATIO = float(os.environ.get("LUO_SPACE_WIDTH", "0.50"))

# Hook refinement (钩画): thinner root, shorter body, lighter tip.
HOOK_ROOT_THIN = float(os.environ.get("LUO_HOOK_ROOT_THIN", "0.09"))
HOOK_SHORTEN = float(os.environ.get("LUO_HOOK_SHORTEN", "0.14"))
HOOK_TIP_TAPER = float(os.environ.get("LUO_HOOK_TIP_TAPER", "-0.02"))

# CJK spacing: keep 1em advances by default for predictable reading text.
SPACING_BASE = float(os.environ.get("LUO_SPACING_BASE", "1.00"))
SPACING_STEP = float(os.environ.get("LUO_SPACING_STEP", "0.000"))
SPACING_ONSET = int(os.environ.get("LUO_SPACING_ONSET", "3"))
SPACING_CAP = float(os.environ.get("LUO_SPACING_CAP", "1.00"))

# --- Dot contour refinement (Pass A) ---
DOT_AREA_PCT = float(os.environ.get("LUO_DOT_AREA_PCT", "5.0"))
DOT_MAX_POINTS = int(os.environ.get("LUO_DOT_MAX_POINTS", "20"))
DOT_COMPRESS = float(os.environ.get("LUO_DOT_COMPRESS", "0.82"))
DOT_ROTATE_DEG = float(os.environ.get("LUO_DOT_ROTATE_DEG", "6.0"))

# --- Second hook pass (Pass B) ---
HOOK_FINAL_SHORTEN = float(os.environ.get("LUO_HOOK_FINAL_SHORTEN", "0.10"))
HOOK_FINAL_TIP_SHARPEN = float(os.environ.get("LUO_HOOK_FINAL_TIP_SHARPEN", "0.12"))

# --- Bone turn refinement (Pass C) ---
BONE_TURN_ANGLE_MAX = float(os.environ.get("LUO_BONE_TURN_ANGLE_MAX", "120"))
BONE_TURN_SEG_MIN = float(os.environ.get("LUO_BONE_TURN_SEG_MIN", "15"))
BONE_TURN_SEG_MAX = float(os.environ.get("LUO_BONE_TURN_SEG_MAX", "80"))
BONE_TURN_DISPLACE = float(os.environ.get("LUO_BONE_TURN_DISPLACE", "2.0"))
BONE_TURN_INNER_REDUCE = float(os.environ.get("LUO_BONE_TURN_INNER_REDUCE", "0.92"))

# --- Stroke taper refinement (Pass D) ---
TAPER_ARC_PCT = float(os.environ.get("LUO_TAPER_ARC_PCT", "0.15"))
TAPER_INWARD = float(os.environ.get("LUO_TAPER_INWARD", "0.04"))
TAPER_MIN_CONTOUR_PTS = int(os.environ.get("LUO_TAPER_MIN_CONTOUR_PTS", "12"))

# --- Heart character refinement (Pass E) ---
HEART_DOT_COMPRESS = float(os.environ.get("LUO_HEART_DOT_COMPRESS", "0.80"))
HEART_DOT_ANGLE = float(os.environ.get("LUO_HEART_DOT_ANGLE", "8.0"))
HEART_HOOK_SHORTEN = float(os.environ.get("LUO_HEART_HOOK_SHORTEN", "0.08"))
HEART_DOT_SPACING = float(os.environ.get("LUO_HEART_DOT_SPACING", "1.06"))

BUILD_CHARS = os.environ.get("LUO_BUILD_CHARS", "starter")

FAMILY = os.environ.get("LUO_FAMILY", "Luo")
SUBFAMILY = os.environ.get("LUO_SUBFAMILY", "Regular")
OUTPUT_PREFIX = os.environ.get("LUO_OUTPUT_PREFIX", "Luo-Regular")
VERSION = "0.3.0"

COPYRIGHT = (
    "Luo, a CJK typeface for Kami. "
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
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue

        if _is_cjk_glyph(name, cmap):
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

        new_coords = list(coords)
        start = 0
        for end in ends:
            n = end - start + 1
            for j in range(n):
                idx = start + j
                px, py = coords[start + (j - 1) % n]
                nx_pt, ny_pt = coords[start + (j + 1) % n]
                tx, ty = nx_pt - px, ny_pt - py
                length = math.hypot(tx, ty)
                if length < 1e-6:
                    continue
                norm_x = -ty / length
                norm_y = tx / length
                horiz_ratio = abs(tx) / length
                delta = local_h * horiz_ratio + local_v * (1.0 - horiz_ratio)
                x, y = coords[idx]
                new_coords[idx] = (
                    int(round(x + delta * norm_x)),
                    int(round(y + delta * norm_y)),
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

        start = 0
        for end in ends:
            n = end - start + 1
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

                sharpness = 1.0 - angle / threshold_rad
                blend = SOFTEN_BLEND * sharpness

                mid_x = (px + nx_pt) / 2.0
                mid_y = (py + ny_pt) / 2.0
                new_x = cx + blend * (mid_x - cx)
                new_y = cy + blend * (mid_y - cy)
                new_coords[idx] = (int(round(new_x)), int(round(new_y)))
                softened_points += 1
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
        f"blend={SOFTEN_BLEND}, seg_max={SOFTEN_SEG_MAX})"
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
            if n < 5:
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
        "快怀悟悲悼情惠想感慢慨性息"
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
DENSE_COMPLEX_INNER = 0.975
MULTI_HORIZ_SECONDARY = 0.97
TOP_BOTTOM_UPPER_CONTRACT = 0.98


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


def _refine_dense_top(glyph, glyf) -> None:
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
    for i in range(n):
        x, y = coords[i]
        if y > top_threshold:
            t = (y - top_threshold) / (y_max - top_threshold) if y_max > top_threshold else 0
            factor = 1.0 - (1.0 - DENSE_TOP_REDUCE) * t
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


def _refine_dense_complex(glyph, glyf) -> None:
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
            new_x = cx + (x - cx) * DENSE_COMPLEX_INNER
            new_y = cy + (y - cy) * DENSE_COMPLEX_INNER
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
            _refine_dense_top(glyph, glyf)
        elif cat == "wide_split":
            _refine_wide_split(glyph, glyf)
        elif cat == "walk_enclosed":
            _refine_walk_enclosed(glyph, glyf)
        elif cat == "dense_complex":
            _refine_dense_complex(glyph, glyf)
        elif cat == "multi_horiz":
            _refine_multi_horiz(glyph, glyf)
        elif cat == "top_bottom":
            _refine_top_bottom(glyph, glyf)
        stats[cat] = stats.get(cat, 0) + 1
    total = sum(stats.values())
    if total > 0:
        detail = " ".join(f"{k}={v}" for k, v in sorted(stats.items()))
        print(f"[luo] refined {total} glyphs by category ({detail})")


# --- Pass A: Dot contour refinement ---

HEART_CHARS = (
    "心思意念想感悲惠慨悟您志必恩愁惊慎"
    "忠忽怠恨恐恭忙忆忍忘"
)

HOOK_FINAL_CHARS = (
    "字书亭序家设计排版印旅妙馈成式透远道遇永可事将到"
    "心清落读说规则使用方族校"
)


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
        if char in HEART_CHARS:
            continue

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

            c_xs = [coords[i][0] for i in range(start, end + 1)]
            c_ys = [coords[i][1] for i in range(start, end + 1)]
            c_w = max(c_xs) - min(c_xs)
            c_h = max(c_ys) - min(c_ys)
            if c_w <= 0 or c_h <= 0:
                start = end + 1
                continue

            aspect = max(c_w, c_h) / min(c_w, c_h)
            if aspect > 4.0:
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

            local_rad = math.radians(rot)
            local_cos = math.cos(local_rad)
            local_sin = math.sin(local_rad)

            for i in range(start, end + 1):
                x, y = coords[i]
                dx = (x - cx) * DOT_COMPRESS
                dy = (y - cy) * DOT_COMPRESS
                rx = dx * local_cos - dy * local_sin
                ry = dx * local_sin + dy * local_cos
                coords[i] = (int(round(cx + rx)), int(round(cy + ry)))

            dot_count += 1
            touched = True
            start = end + 1

        if touched:
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] refined {dot_count} dot contours across {glyph_count} glyphs "
        f"(compress={DOT_COMPRESS}, rotate={DOT_ROTATE_DEG}°)"
    )


# --- Pass B: Second hook refinement ---

def refine_hooks_final(font: TTFont) -> None:
    """Second-pass hook tightening on targeted characters."""
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)

    hook_count = 0
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
            if n < 5:
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
                    perp_x = -axis_y / axis_len
                    perp_y = axis_x / axis_len
                    for tip_idx in (i_next, i_next2):
                        pt = new_coords[tip_idx]
                        proj = (pt[0] - p1[0]) * perp_x + (pt[1] - p1[1]) * perp_y
                        new_coords[tip_idx] = (
                            int(round(pt[0] - HOOK_FINAL_TIP_SHARPEN * proj * perp_x)),
                            int(round(pt[1] - HOOK_FINAL_TIP_SHARPEN * proj * perp_y)),
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
        f"[luo] final-refined {hook_count} hooks across {glyph_count} glyphs "
        f"(shorten={HOOK_FINAL_SHORTEN}, sharpen={HOOK_FINAL_TIP_SHARPEN})"
    )


# --- Pass C: Bone turn refinement ---

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

            offset_x = (dc_cx - glyph_cx) * (HEART_DOT_SPACING - 1.0)

            for i in range(s, e + 1):
                x, y = coords[i]
                dx = (x - dc_cx) * HEART_DOT_COMPRESS
                dy = (y - dc_cy) * HEART_DOT_COMPRESS
                rx = dx * cos_r - dy * sin_r
                ry = dx * sin_r + dy * cos_r
                coords[i] = (int(round(dc_cx + rx + offset_x)), int(round(dc_cy + ry)))

            dot_count += 1
            touched = True

        hc = hook_contour
        hs, he = hc["start"], hc["end"]
        h_xs = [coords[i][0] for i in range(hs, he + 1)]
        h_xmin = min(h_xs)
        h_xmax = max(h_xs)
        h_xrange = h_xmax - h_xmin
        if h_xrange > 0:
            cutoff = h_xmin + h_xrange * 0.3
            for i in range(hs, he + 1):
                x, y = coords[i]
                if x < cutoff:
                    t = 1.0 - (x - h_xmin) / (cutoff - h_xmin) if cutoff > h_xmin else 0
                    pull = HEART_HOOK_SHORTEN * t
                    coords[i] = (int(round(x + pull * (h_xmax - x))), y)
            hook_count += 1
            touched = True

        if touched:
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] refined {dot_count} heart dots + {hook_count} hooks "
        f"across {glyph_count} glyphs "
        f"(compress={HEART_DOT_COMPRESS}, angle={HEART_DOT_ANGLE}°, "
        f"spacing={HEART_DOT_SPACING}, hook={HEART_HOOK_SHORTEN})"
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
    "point_marks": "清润源落读说语社视意念终寒露霜霞",
    "hooks": "字书亭序家设计排版印旅妙馈成式透远道遇",
    "endpoints": "落纸风骨短版排印集章源雅舒服规则",
    "multi_horiz": "章言书骨兰量重墨春青善美黄宇宙寒暑律吕",
    "frames": "国回图园日目田间阅品亭曾会",
    "dense_complex": "落藏霞霜露馈赢耀魔读题额锦继续源族章集端筋群贤禊觞湍幽怀籍麟",
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
    elif BUILD_CHARS == "full":
        print(f"[luo] keeping all {len(font.getGlyphOrder())} glyphs")
        requested_chars = starter_chars()
        required_chars = chars_from_files(STARTER_FILES)
    else:
        sys.exit("[luo] LUO_BUILD_CHARS must be 'seed', 'site', 'starter', or 'full'")

    # Boldening: direction-aware or legacy single-value
    if BOLDEN_DELTA is not None:
        d = float(BOLDEN_DELTA)
        bolden_glyphs(font, d, d)
    else:
        bolden_glyphs(font, BOLDEN_H, BOLDEN_V)

    soften_endpoints(font)
    refine_hooks(font)

    # Narrowing: legacy single-value or complexity-aware
    if NARROW_X is not None:
        nx = float(NARROW_X)
        narrow_and_scale(font, nx, nx, nx, SCALE_Y)
    else:
        narrow_and_scale(font, NARROW_SIMPLE, NARROW_REGULAR, NARROW_COMPLEX, SCALE_Y)

    refine_by_category(font)
    refine_dot_contours(font)
    refine_hooks_final(font)
    refine_bone_turns(font)
    refine_stroke_taper(font)
    refine_heart_chars(font)
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
