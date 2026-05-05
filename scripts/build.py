"""
Luo font builder.

Pipeline (mirrors main()):
  1. Load the source TTF.
  2. Subset to starter/site/seed or explicit GB2312 expansion characters.
  3. Graduated stroke thickening (横细竖重, dot-aware cap).
  4. Endpoint softening (硬切 -> 软切, with h/v_bottom/diag subtypes).
  5. Stroke straightening (v0.4: flatten LXGW bow on long near-axis spans).
  6. Complexity-aware horizontal narrowing + vertical scaling.
  7. Component-aware refinement (7 categories).
  8. Heart-character reshape (心字底/旁, hook + sorted dot group).
  9. Dot contour direction (xiaokai dot rotation + compression).
  9a. v0.4.6 typographic-kai abstractions (4 generic component refiners):
       bottom_anchor_settle, left_radical_contain, inner_counter_open,
       dense_counter_tier.
 10. Targeted turn refinement (priority frames/endpoints/multi-horiz).
 10b. Luo signature: long-h end micro-emphasis (luo_horiz_end_emphasis).
 11. Dense dot-cluster protection (墨).
 12. Hook refinement on whitelist (refine_hooks_final).
 12b. Geometric cap: hook tail width <= stem width at hook root (cap_hook_tail_widths).
 12c. Luo signature: hook-root inward handle (luo_hook_root_inward_handle).
 13. Walk-radical final containment (透/道/遇/etc.).
 14. Display anchor refinement (落/笔/见).
 15. Identity refinement (anchor + all-covered guardrails + core_v2).
 15b. Visible-problem glyph correction (两/月/或/则/魔 audit set).
 16. CJK punctuation + space + spacing.
 17. Rewrite name table -> Luo.
 18. Write Luo-Regular.ttf/.woff2 into dist/.
 19. Patch asset-version cache-bust strings in luo.css/print.css/index.html.

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
BOLDEN_H = float(os.environ.get("LUO_BOLDEN_H", "6"))   # v0.4.2 回补: 5 在前一轮系统回退后偏瘦，回到 v0.3 档
BOLDEN_V = float(os.environ.get("LUO_BOLDEN_V", "14"))  # v0.4.2 回补: 13 在补偿参数被撤后主竖发虚，回到 v0.3 档
# Diagonal bonus: linear interpolation gives 撇/捺 about 10.5 at 45° — visually
# too thin next to 15-unit verticals. Add a parabolic bonus that peaks at
# horiz_ratio=0.5 so 撇/捺 carry more weight without disturbing pure
# horizontals/verticals.
BOLDEN_DIAG_BONUS = float(os.environ.get("LUO_BOLDEN_DIAG", "7.0"))  # v0.4.2 观察撇捺，过粗再降到 6.0
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
ENDPOINT_H_BLEND = float(os.environ.get("LUO_ENDPOINT_H_BLEND", "0.025"))   # v0.4: 横端更直
ENDPOINT_V_BOTTOM_BLEND = float(os.environ.get("LUO_ENDPOINT_V_BOTTOM_BLEND", "0.045"))
ENDPOINT_DIAG_BLEND = float(os.environ.get("LUO_ENDPOINT_DIAG_BLEND", "0.020"))  # v0.4: 撇捺端更直

# --- Stroke straightening (v0.4 print-kai pivot) ---
# LXGW WenKai's body strokes are quadratic Beziers with visible bow; ~92% of
# 一/丨 segments are curves. The v0.4 direction prefers cleaner straight-ish
# typographic-kai strokes. This pass walks each contour, detects spans between
# consecutive on-curve points, and pulls the in-between control points toward
# the chord by a blend factor that depends on the chord's angle.
#
# Three blends apply by chord direction (the more axial the chord, the more
# we want to flatten it; diagonals carry stroke speed and need lighter
# treatment so 撇/捺 don't go geometric):
STRAIGHTEN_H_BLEND = float(os.environ.get("LUO_STRAIGHTEN_H_BLEND", "0.65"))
STRAIGHTEN_V_BLEND = float(os.environ.get("LUO_STRAIGHTEN_V_BLEND", "0.60"))
STRAIGHTEN_DIAG_BLEND = float(os.environ.get("LUO_STRAIGHTEN_DIAG_BLEND", "0.30"))
# Chord-angle bands (degrees from nearest axis). H = chord within this many
# degrees of horizontal, V = within this many of vertical, DIAG = remainder.
STRAIGHTEN_H_BAND = float(os.environ.get("LUO_STRAIGHTEN_H_BAND", "30.0"))
STRAIGHTEN_V_BAND = float(os.environ.get("LUO_STRAIGHTEN_V_BAND", "30.0"))
# Legacy gate kept for back-compat but unused when bands cover [0, 90).
STRAIGHTEN_ANGLE_GATE = float(os.environ.get("LUO_STRAIGHTEN_ANGLE_GATE", "30.0"))
# Spans shorter than this fraction of the glyph's max(w, h) are skipped to
# avoid touching tiny joinery segments. Set low because the visible bow on
# LXGW lives in the cap regions (short spans with interior off-curves),
# not the long body spans (which usually have no interior off-curves to
# flatten in the first place).
STRAIGHTEN_MIN_LEN_RATIO = float(os.environ.get("LUO_STRAIGHTEN_MIN_LEN_RATIO", "0.04"))
# Absolute floor in font units, regardless of glyph size — protects 1-unit
# joinery on tiny dot/heart contours from accidental moves.
STRAIGHTEN_MIN_LEN_ABS = float(os.environ.get("LUO_STRAIGHTEN_MIN_LEN_ABS", "30.0"))
# v0.4.2 corner protection: if an interior off-curve sits more than this
# fraction of the chord length perpendicular from the chord, treat it as a
# corner-shaping control rather than a stem bow and skip it. Bow controls on
# LXGW long stems usually sit at <5% perp/chord; the bao-gai right corner
# (字) and 横折钩 (子, 无) sit at 15%-30%, so a 0.18 gate cleanly separates
# the two without a character whitelist. Without this gate the H_BLEND=0.65
# pull on these corner controls drags them along the chord and creates a
# downward triangular spike at the right end of long horizontals.
STRAIGHTEN_MAX_PERP_RATIO = float(os.environ.get("LUO_STRAIGHTEN_MAX_PERP_RATIO", "0.20"))  # v0.4.3 audit fix: 0.18 仍在长横右端拉出三角下尖，放宽到 0.20 让更多 corner controls 被识别保护
# Glyph categories where straightening is known to interfere with a
# dedicated downstream pass; left alone here and shaped by their own
# refiners later in the pipeline.
STRAIGHTEN_SKIP_CHARS = (
    # Walk-radical chars: refine_walk_final has its own dedicated geometry
    # for the bottom 辶 stroke. STRAIGHTEN before it would muddle the result.
    "透道遇述远近过这还进通达选送逢迁连运遍适迹造"
    # 忄-radical chars: the left-side three-stroke 忄 has small joining
    # segments that STRAIGHTEN would visibly distort. The right-hand body
    # is straightened normally because TURN/HOOK passes also see it; only
    # the ones flagged via DOT_SKIP_CHARS keep the 忄 hook intact.
    "快情怀性恼愉悄惯惜慢慎慨悟悬"
    # Standalone "all-heart" glyphs where the hook IS the glyph. v0.4-fix
    # shrinks the v0.4 list (which over-protected compounds) to just three
    # truly-standalone shapes. Compound 心字底 chars (思/想/感/etc.) are now
    # straightened uniformly with their top component so the within-glyph
    # weight reads consistently; the prior list made compounds look uneven.
    "心必忍"
)

# Space width: half-width space for tighter CJK typesetting.
SPACE_WIDTH_RATIO = float(os.environ.get("LUO_SPACE_WIDTH", "0.50"))

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
DOT_SHORT_AXIS = float(os.environ.get("LUO_DOT_SHORT_AXIS", "0.55"))  # v0.4.1: 楔形保留，但回到 v0.3 上限避免 12-19px body 掉点
DOT_ROTATE_DEG = float(os.environ.get("LUO_DOT_ROTATE_DEG", "17.0"))  # v0.4.4 widen: was 14.0; xiaokai 楔形点 转角再加 3° 拉开与 LXGW 的距离
# Adaptive carve: as source aspect rises toward the gate, lerp short-axis factor
# toward 1.0 so elongated dots (岭/信/令 style) are not over-carved into slashes.
DOT_RELAX_PIVOT = float(os.environ.get("LUO_DOT_RELAX_PIVOT", "1.0"))
DOT_RELAX_GATE  = float(os.environ.get("LUO_DOT_RELAX_GATE",  "1.8"))
# Dot-aware bolden cap: stop small dot-like contours from gaining very
# different horizontal expansion in dense vs open glyph contexts.
DOT_BOLDEN_X_CAP_FACTOR = float(os.environ.get("LUO_DOT_BOLDEN_X_CAP_FACTOR", "1.15"))
DOT_BOLDEN_ASPECT_GATE = 2.2

# --- Second hook pass (Pass B) ---
# v0.4.1 reduction: the v0.4 values stacked with bone-node turn refinement and
# created a two-segment kink at 弯钩/竖弯钩 corners (笔/书/览/无). Pull SHORTEN /
# TIP_SHARPEN back toward the v0.3 / v0.4 midpoint, keep TAIL_CONTAIN very low,
# and reserve an even gentler tip sharpening for hooks that turn by >= 80° so
# the curved tail survives instead of collapsing into a near-straight chord.
HOOK_FINAL_SHORTEN = float(os.environ.get("LUO_HOOK_FINAL_SHORTEN", "0.16"))
HOOK_FINAL_TIP_SHARPEN = float(os.environ.get("LUO_HOOK_FINAL_TIP_SHARPEN", "0.15"))  # v0.4.3 audit fix: 0.18 仍把 弯钩/横折钩 末端尖刺化，再降一档
HOOK_FINAL_TIP_SHARPEN_CURVED = float(os.environ.get("LUO_HOOK_FINAL_TIP_SHARPEN_CURVED", "0.10"))
HOOK_FINAL_TAIL_CONTAIN = float(os.environ.get("LUO_HOOK_FINAL_TAIL_CONTAIN", "0.045"))
# Hooks that turn by at least this many degrees are treated as 弯钩/竖弯钩:
# the off-curve handle keeps its perpendicular position so the tail reads as
# a continuous curve, not as two linear segments meeting at a sharp corner.
HOOK_FINAL_CURVED_ANGLE = float(os.environ.get("LUO_HOOK_FINAL_CURVED_ANGLE", "80.0"))

# v0.4.2 geometric cap: after refine_hooks_final, ensure the local outline
# width along the hook tail does not exceed the perpendicular stroke width
# measured at the hook root (where the tail leaves the main stem). This is
# whitelist-free — the same hook detection used by refine_hooks_final picks
# the contour neighbourhood, then a perpendicular ray cast measures stem
# width at the knee and tail width at the next few points; if the tail is
# wider than the stem (plus tolerance), both sides are pushed inward by half
# the excess. Fixes 无 type 头轻脚重 where the 竖弯钩 tail reads heavier than
# the main vertical.
HOOK_TAIL_CAP_ENABLED = os.environ.get("LUO_HOOK_TAIL_CAP_ENABLED", "1") not in ("0", "false", "False")
HOOK_TAIL_CAP_TOLERANCE = float(os.environ.get("LUO_HOOK_TAIL_CAP_TOLERANCE", "0.05"))
HOOK_TAIL_CAP_MAX_PUSH = float(os.environ.get("LUO_HOOK_TAIL_CAP_MAX_PUSH", "16.0"))
HOOK_TAIL_CAP_SAMPLES = int(os.environ.get("LUO_HOOK_TAIL_CAP_SAMPLES", "4"))

# --- v0.4.4 Luo signature passes ---
# Three small geometric features that exist only in Luo, not in any pure
# LXGW-derived shaping. The intent is structural distance from the source
# without raising weight or going back to soft-kai bow.
#
# A1: long horizontal end micro-emphasis ("Luo stop"). At the right end of
# every long, near-horizontal stroke (>= LUO_HORIZ_END_EMPHASIS_MIN_RATIO
# of glyph max(w,h), within ±LUO_HORIZ_END_EMPHASIS_ANGLE_DEG of horizontal),
# walk a few outline points around the cap and push them DOWN by up to
# LUO_HORIZ_END_EMPHASIS_PUSH_EM, decaying away from the cap. The result is
# a small downward "顿" beneath the cap, much like a quiet print-kai final
# stop, that LXGW does not have. Skips contours whose next on-curve drops
# more than ~20% of glyph height (那是 横折/钩 root, not a free 横画 stop).
LUO_HORIZ_END_EMPHASIS_PUSH_EM = float(os.environ.get("LUO_HORIZ_END_EMPHASIS_PUSH_EM", "0.005"))
LUO_HORIZ_END_EMPHASIS_LEN_RATIO = float(os.environ.get("LUO_HORIZ_END_EMPHASIS_LEN_RATIO", "0.06"))
# Parent plan called for "length >= 0.40 of glyph max(w,h)" but LXGW outlines
# subdivide long edges with multiple on-curve points, so a 0.40 chord-length
# gate fires only on a handful of unbroken-edge glyphs (一 / 二 / 三 / 工).
# 0.25 is the minimum that catches the per-chord segments of typical multi-
# horizontal stacks (王 / 主 / 章 / 兰 / 集 / 印) while still excluding short
# joinery segments.
LUO_HORIZ_END_EMPHASIS_MIN_RATIO = float(os.environ.get("LUO_HORIZ_END_EMPHASIS_MIN_RATIO", "0.25"))
LUO_HORIZ_END_EMPHASIS_ANGLE_DEG = float(os.environ.get("LUO_HORIZ_END_EMPHASIS_ANGLE_DEG", "10.0"))
LUO_HORIZ_END_EMPHASIS_SAMPLES = int(os.environ.get("LUO_HORIZ_END_EMPHASIS_SAMPLES", "4"))

# A2: hook root inward handle. After refine_hooks_final and the geometric
# hook tail width cap, find the off-curve handle just before each detected
# hook root (p1) and push it slightly toward the glyph centroid. The off-
# curve sits on the stem just above the knee, and a small inward push pulls
# the stem-to-hook transition into a slightly inward-curving "knuckle"
# instead of LXGW's straight-into-the-hook geometry.
LUO_HOOK_ROOT_HANDLE_PUSH_EM = float(os.environ.get("LUO_HOOK_ROOT_HANDLE_PUSH_EM", "0.003"))

# --- v0.4.6 Typographic-kai abstractions (4 generic component refiners) ---
# Small geometry-only refinement passes that emerged from a deep study
# of high-quality typographic-kai references. Each is anchored on contour
# topology (signed area, centroid position, aspect, area ratio), not on
# character whitelists, so they generalise across the full CJK set without
# private-reference name bindings. All four share the same safety budget:
# small magnitudes, presence-floor guarded, and explicit skip lists for
# glyph categories that already have dedicated geometry downstream.
#
# B1: bottom_anchor_settle. The "lower-stroke too heavy" pattern. Outer
# bottom contours that sit in the lower ~32% of glyph height with high
# aspect or wide footprint get a small Y compression and an upward shift,
# echoing how a reading-grade kai pulls the foot up off the baseline so the
# whole glyph stops feeling sunk. Generalises the per-char roof_bottom /
# stack_bottom tweaks in refine_kai_component_balance to every CJK glyph.
LUO_BOTTOM_ANCHOR_SCALE_Y = float(os.environ.get("LUO_BOTTOM_ANCHOR_SCALE_Y", "0.945"))
LUO_BOTTOM_ANCHOR_LIFT_EM = float(os.environ.get("LUO_BOTTOM_ANCHOR_LIFT_EM", "0.008"))
LUO_BOTTOM_ANCHOR_BAND = float(os.environ.get("LUO_BOTTOM_ANCHOR_BAND", "0.36"))
LUO_BOTTOM_ANCHOR_MIN_AREA = float(os.environ.get("LUO_BOTTOM_ANCHOR_MIN_AREA", "0.015"))
# Max area gate: if the "foot" contour covers more than this fraction of the
# glyph, it is the dominant body shape (e.g. 气 / 兮 outer outline) and
# should not be treated as a separable foot layer.
LUO_BOTTOM_ANCHOR_MAX_AREA = float(os.environ.get("LUO_BOTTOM_ANCHOR_MAX_AREA", "0.30"))
LUO_BOTTOM_ANCHOR_MIN_ASPECT = float(os.environ.get("LUO_BOTTOM_ANCHOR_MIN_ASPECT", "1.5"))
LUO_BOTTOM_ANCHOR_MIN_WIDTH = float(os.environ.get("LUO_BOTTOM_ANCHOR_MIN_WIDTH", "0.40"))

# B2: left_radical_contain. The "left side bulges" pattern. A self-contained
# outer contour cluster occupying < 46% of glyph width on the left, with
# total area between 4% and 22% of glyph area, gets a small inward scale
# and a rightward gap shift so the right component breathes. Generalises
# KAI_BALANCE_SIDE_SPLIT (currently 11 chars) to every glyph that exhibits
# the same topology, without reaching into glyphs that already have
# dedicated speech / water / frame / walk passes.
LUO_LEFT_RADICAL_X = float(os.environ.get("LUO_LEFT_RADICAL_X", "0.940"))
LUO_LEFT_RADICAL_Y = float(os.environ.get("LUO_LEFT_RADICAL_Y", "0.975"))
LUO_LEFT_RADICAL_GAP_EM = float(os.environ.get("LUO_LEFT_RADICAL_GAP_EM", "0.006"))
LUO_LEFT_RADICAL_SPLIT = float(os.environ.get("LUO_LEFT_RADICAL_SPLIT", "0.46"))
LUO_LEFT_RADICAL_MIN_AREA = float(os.environ.get("LUO_LEFT_RADICAL_MIN_AREA", "0.04"))
LUO_LEFT_RADICAL_MAX_AREA = float(os.environ.get("LUO_LEFT_RADICAL_MAX_AREA", "0.22"))

# B3: inner_counter_open. The "middle column over-inked" pattern. Inner
# counter contours (signed area > 0) whose centroid sits in the middle
# horizontal third get a small horizontal expansion so the centre column
# reads more open. Excludes frame chars (国回...) which have their own
# counter pass, and glyphs with too-few contours (single-counter shapes).
LUO_INNER_COUNTER_X = float(os.environ.get("LUO_INNER_COUNTER_X", "1.040"))
LUO_INNER_COUNTER_Y = float(os.environ.get("LUO_INNER_COUNTER_Y", "1.020"))
LUO_INNER_COUNTER_BAND_LO = float(os.environ.get("LUO_INNER_COUNTER_BAND_LO", "0.30"))
LUO_INNER_COUNTER_BAND_HI = float(os.environ.get("LUO_INNER_COUNTER_BAND_HI", "0.70"))
LUO_INNER_COUNTER_MIN_AREA = float(os.environ.get("LUO_INNER_COUNTER_MIN_AREA", "0.005"))
LUO_INNER_COUNTER_MAX_AREA = float(os.environ.get("LUO_INNER_COUNTER_MAX_AREA", "0.15"))

# B4: dense_counter_tier. The homepage queue exposed a topology the base B3
# rule under-serves: dense multi-contour glyphs whose center has at least one
# eligible counter and several small dot-like / component contours. These need
# a little extra interior white, not whole-glyph lightening. The gate is based
# on contour count + eligible counter count + dot-like contour count, so it
# catches 籍/赢/魔/麟-style density without naming those glyphs.
LUO_DENSE_COUNTER_MIN_CONTOURS = int(os.environ.get("LUO_DENSE_COUNTER_MIN_CONTOURS", "7"))
LUO_DENSE_COUNTER_MIN_INNERS = int(os.environ.get("LUO_DENSE_COUNTER_MIN_INNERS", "1"))
LUO_DENSE_COUNTER_DOT_MIN = int(os.environ.get("LUO_DENSE_COUNTER_DOT_MIN", "3"))
LUO_DENSE_COUNTER_X = float(os.environ.get("LUO_DENSE_COUNTER_X", "1.018"))
LUO_DENSE_COUNTER_Y = float(os.environ.get("LUO_DENSE_COUNTER_Y", "1.010"))

# --- Targeted turn refinement (Pass C, full CJK with priority bump) ---
# v0.4.1 reduction: the v0.4 default DISPLACE=2.5 ran on every CJK glyph and
# created sharp 折点 at hook roots and short-stroke joints, contributing to
# the 笔/书/览/无 two-segment look. The new default keeps a quieter bone-node
# globally and reserves the v0.4 displacement only for the curated priority
# anchor / frame / multi-horiz characters that benefit from explicit骨节.
TURN_FINAL_ANGLE_MAX = 105.0
TURN_FINAL_DISPLACE = float(os.environ.get("LUO_TURN_FINAL_DISPLACE", "1.6"))
TURN_FINAL_INNER = float(os.environ.get("LUO_TURN_FINAL_INNER", "0.955"))
TURN_FINAL_PRIORITY_DISPLACE = float(os.environ.get("LUO_TURN_FINAL_PRIORITY_DISPLACE", "1.9"))  # v0.4.3 audit fix: 2.2 在 priority 字仍出现钉头/折点，再压一档同时保留 default 1.6
TURN_FINAL_PRIORITY_INNER = float(os.environ.get("LUO_TURN_FINAL_PRIORITY_INNER", "0.94"))
TURN_FINAL_SEG_MIN = 15.0
TURN_FINAL_SEG_MAX = 90.0
TURN_FINAL_FRAME_DISPLACE = float(os.environ.get("LUO_TURN_FINAL_FRAME_DISPLACE", "1.6"))
TURN_FINAL_FRAME_INNER = float(os.environ.get("LUO_TURN_FINAL_FRAME_INNER", "0.955"))
TURN_FINAL_FRAME_SEG_MAX = float(os.environ.get("LUO_TURN_FINAL_FRAME_SEG_MAX", "140"))

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
ANCHOR_LUO_TOP_EXPAND = float(os.environ.get("LUO_ANCHOR_LUO_TOP_EXPAND", "0.970"))
ANCHOR_LUO_BOTTOM_CONTRACT = float(os.environ.get("LUO_ANCHOR_LUO_BOTTOM_CONTRACT", "0.925"))
ANCHOR_BI_TOP_SCALE_X = float(os.environ.get("LUO_ANCHOR_BI_TOP_SCALE_X", "0.940"))
ANCHOR_BI_TOP_SCALE_Y = float(os.environ.get("LUO_ANCHOR_BI_TOP_SCALE_Y", "0.975"))
ANCHOR_JIAN_BOTTOM_RAISE_EM = float(os.environ.get("LUO_ANCHOR_JIAN_BOTTOM_RAISE_EM", "0.035"))
ANCHOR_JIAN_BOTTOM_CONTAIN = float(os.environ.get("LUO_ANCHOR_JIAN_BOTTOM_CONTAIN", "0.018"))
ANCHOR_JIAN_RIGHT_TAIL_CONTAIN = float(os.environ.get("LUO_ANCHOR_JIAN_RIGHT_TAIL_CONTAIN", "0.035"))

# Source-separation pass. Earlier passes make Luo cleaner and more print-ready,
# but many simple starter glyphs still share the source outline posture. This
# white-list pass changes structure language instead of global weight: slightly
# taller top/bottom rhythm, stronger secondary-horizontal hierarchy, larger
# frame counters, and more tension in diagonal glyphs.
IDENTITY_HIGH_RISK_CHARS = (
    "去壁辞前来序藏永赤兮纸湍落墨赋归雨笔激风游黑流霜代"
    "字印书兰章月魔家清点淡亭文集回骨国黄天玄"
)
IDENTITY_POSTURE_CHARS = "章天兰书文集字回骨月玄亭清家点国黄印"
IDENTITY_FRAME_CHARS = "国回图园日目月团"  # v0.4.4: 团 加入框形通道，外框稳，内白透气
IDENTITY_MULTI_HORIZ_CHARS = "章兰书集骨黄点"
IDENTITY_DIAG_CHARS = "文天玄"
# Counter opening helps these frame glyphs separate from the source without
# making the frame body heavier. 用/田/由/曲/电/自/直 are deliberately left on
# guardrails only for now: counter opening made them look closer to the source.
IDENTITY_FRAME_RISK_CHARS = "目日月且"
IDENTITY_LAYER_RISK_CHARS = "昔音喜甚基真备审省革其"
IDENTITY_CORE_V2_CHARS = (
    "落文字书心清骨风纸印永和九年兰亭集序国回日目用月团透道遇墨点游流黑"
    "前赤壁赋归去来兮辞春暮山用壁年之来癸在于稽赤丑阴"
)  # v0.4.4: + 团 frame extension
IDENTITY_CORE_FRAME_CHARS = "国回日目用月团"  # v0.4.4: + 团
IDENTITY_CORE_LAYER_CHARS = "春暮壁前墨黑兰亭集序"
IDENTITY_CORE_DIAG_CHARS = "文永之来去归兮辞"
IDENTITY_POSTURE_TOP_RAISE_EM = float(os.environ.get("LUO_IDENTITY_TOP_RAISE_EM", "0.026"))
IDENTITY_POSTURE_BOTTOM_SETTLE_EM = float(os.environ.get("LUO_IDENTITY_BOTTOM_SETTLE_EM", "0.010"))
IDENTITY_POSTURE_UPPER_X_CONTAIN = float(os.environ.get("LUO_IDENTITY_UPPER_X_CONTAIN", "0.980"))
IDENTITY_POSTURE_LOWER_X_EXPAND = float(os.environ.get("LUO_IDENTITY_LOWER_X_EXPAND", "1.012"))
IDENTITY_FRAME_COUNTER_EXPAND_X = float(os.environ.get("LUO_IDENTITY_FRAME_COUNTER_EXPAND_X", "1.050"))
IDENTITY_FRAME_COUNTER_EXPAND_Y = float(os.environ.get("LUO_IDENTITY_FRAME_COUNTER_EXPAND_Y", "1.025"))
IDENTITY_MULTI_MID_CONTAIN = float(os.environ.get("LUO_IDENTITY_MULTI_MID_CONTAIN", "0.935"))
IDENTITY_MULTI_BOTTOM_EXPAND = float(os.environ.get("LUO_IDENTITY_MULTI_BOTTOM_EXPAND", "1.018"))
IDENTITY_DIAG_EDGE_EXPAND = float(os.environ.get("LUO_IDENTITY_DIAG_EDGE_EXPAND", "0.030"))
IDENTITY_RISK_FRAME_COUNTER_EXPAND_X = float(os.environ.get("LUO_IDENTITY_RISK_FRAME_COUNTER_EXPAND_X", "1.065"))
IDENTITY_RISK_FRAME_COUNTER_EXPAND_Y = float(os.environ.get("LUO_IDENTITY_RISK_FRAME_COUNTER_EXPAND_Y", "1.040"))
IDENTITY_LAYER_COUNTER_EXPAND_X = float(os.environ.get("LUO_IDENTITY_LAYER_COUNTER_EXPAND_X", "1.040"))
IDENTITY_LAYER_COUNTER_EXPAND_Y = float(os.environ.get("LUO_IDENTITY_LAYER_COUNTER_EXPAND_Y", "1.022"))
IDENTITY_LAYER_SECONDARY_SCALE = float(os.environ.get("LUO_IDENTITY_LAYER_SECONDARY_SCALE", "0.986"))
IDENTITY_LAYER_TOP_RAISE_EM = float(os.environ.get("LUO_IDENTITY_LAYER_TOP_RAISE_EM", "0.006"))
IDENTITY_LAYER_BOTTOM_SETTLE_EM = float(os.environ.get("LUO_IDENTITY_LAYER_BOTTOM_SETTLE_EM", "0.004"))
IDENTITY_LAYER_TOP_CONTAIN = float(os.environ.get("LUO_IDENTITY_LAYER_TOP_CONTAIN", "0.992"))
IDENTITY_SOURCE_SHIFT_X_EM = float(os.environ.get("LUO_IDENTITY_SOURCE_SHIFT_X_EM", "0.000"))
IDENTITY_SOURCE_SHIFT_Y_EM = float(os.environ.get("LUO_IDENTITY_SOURCE_SHIFT_Y_EM", "0.000"))
IDENTITY_ALL_TOP_RAISE_EM = float(os.environ.get("LUO_IDENTITY_ALL_TOP_RAISE_EM", "0.010"))
IDENTITY_ALL_BOTTOM_SETTLE_EM = float(os.environ.get("LUO_IDENTITY_ALL_BOTTOM_SETTLE_EM", "0.003"))
IDENTITY_ALL_TOP_CONTAIN = float(os.environ.get("LUO_IDENTITY_ALL_TOP_CONTAIN", "0.985"))   # v0.4: 顶部更收
IDENTITY_ALL_BOTTOM_EXPAND = float(os.environ.get("LUO_IDENTITY_ALL_BOTTOM_EXPAND", "1.012"))  # v0.4: 底部更撑
IDENTITY_ALL_WAIST_CONTAIN = float(os.environ.get("LUO_IDENTITY_ALL_WAIST_CONTAIN", "0.994"))
IDENTITY_ALL_COUNTER_EXPAND_X = float(os.environ.get("LUO_IDENTITY_ALL_COUNTER_EXPAND_X", "1.012"))
IDENTITY_ALL_COUNTER_EXPAND_Y = float(os.environ.get("LUO_IDENTITY_ALL_COUNTER_EXPAND_Y", "1.008"))
IDENTITY_ALL_COMPONENT_SHIFT_EM = float(os.environ.get("LUO_IDENTITY_ALL_COMPONENT_SHIFT_EM", "0.002"))
IDENTITY_ALL_COMPONENT_Y_EM = float(os.environ.get("LUO_IDENTITY_ALL_COMPONENT_Y_EM", "0.001"))
IDENTITY_ALL_EDGE_TENSION_EM = float(os.environ.get("LUO_IDENTITY_ALL_EDGE_TENSION_EM", "0.001"))
IDENTITY_SIMPLE_FACE_X = float(os.environ.get("LUO_IDENTITY_SIMPLE_FACE_X", "1.020"))  # v0.4: 简单字字面更舒展
IDENTITY_SIMPLE_FACE_Y = float(os.environ.get("LUO_IDENTITY_SIMPLE_FACE_Y", "1.006"))
IDENTITY_REGULAR_FACE_X = float(os.environ.get("LUO_IDENTITY_REGULAR_FACE_X", "1.012"))  # v0.4: 常规字字面更舒展
IDENTITY_REGULAR_FACE_Y = float(os.environ.get("LUO_IDENTITY_REGULAR_FACE_Y", "1.004"))
IDENTITY_COMPLEX_FACE_X = float(os.environ.get("LUO_IDENTITY_COMPLEX_FACE_X", "1.002"))
IDENTITY_COMPLEX_FACE_Y = float(os.environ.get("LUO_IDENTITY_COMPLEX_FACE_Y", "1.002"))
# v0.4.1: 0.990 / 0.994 stacked with MULTI_HORIZ_SECONDARY (0.965) and pulled
# secondary horizontals down to ~0.96 in 无/东/亦/荒/起/代 — they read as
# missing strokes at body sizes. Raise both knobs and let MULTI_HORIZ's own
# value carry the weight reduction for layered glyphs.
IDENTITY_SIMPLE_H_LAYER_X = float(os.environ.get("LUO_IDENTITY_SIMPLE_H_LAYER_X", "0.995"))
IDENTITY_ALL_H_LAYER_X = float(os.environ.get("LUO_IDENTITY_ALL_H_LAYER_X", "0.999"))  # v0.4.3 audit fix: 0.997 仍在 multi-horiz 字叠出微缩，回到接近 identity
IDENTITY_ALL_H_LAYER_ROTATE_DEG = float(os.environ.get("LUO_IDENTITY_ALL_H_LAYER_ROTATE_DEG", "0.25"))
IDENTITY_ALL_V_STEM_X = float(os.environ.get("LUO_IDENTITY_ALL_V_STEM_X", "0.994"))
IDENTITY_ALL_V_STEM_Y = float(os.environ.get("LUO_IDENTITY_ALL_V_STEM_Y", "1.004"))
IDENTITY_ALL_DIAG_EXPAND = float(os.environ.get("LUO_IDENTITY_ALL_DIAG_EXPAND", "1.004"))
IDENTITY_ALL_SECONDARY_SCALE = float(os.environ.get("LUO_IDENTITY_ALL_SECONDARY_SCALE", "0.994"))
IDENTITY_ALL_SIDE_COMPONENT_X_EM = float(os.environ.get("LUO_IDENTITY_ALL_SIDE_COMPONENT_X_EM", "0.001"))
IDENTITY_ALL_SIDE_COMPONENT_Y_EM = float(os.environ.get("LUO_IDENTITY_ALL_SIDE_COMPONENT_Y_EM", "0.000"))
IDENTITY_CORE_COUNTER_EXPAND_X = float(os.environ.get("LUO_IDENTITY_CORE_COUNTER_EXPAND_X", "1.055"))
IDENTITY_CORE_COUNTER_EXPAND_Y = float(os.environ.get("LUO_IDENTITY_CORE_COUNTER_EXPAND_Y", "1.035"))
IDENTITY_CORE_SECONDARY_SCALE = float(os.environ.get("LUO_IDENTITY_CORE_SECONDARY_SCALE", "0.960"))
IDENTITY_CORE_HORIZ_Y_SCALE = float(os.environ.get("LUO_IDENTITY_CORE_HORIZ_Y_SCALE", "0.925"))
IDENTITY_CORE_LAYER_GAP_EM = float(os.environ.get("LUO_IDENTITY_CORE_LAYER_GAP_EM", "0.010"))
IDENTITY_CORE_FRAME_STEM_X = float(os.environ.get("LUO_IDENTITY_CORE_FRAME_STEM_X", "0.988"))
IDENTITY_CORE_DIAG_EDGE_EM = float(os.environ.get("LUO_IDENTITY_CORE_DIAG_EDGE_EM", "0.020"))
IDENTITY_CORE_DIAG_TOP_CONTAIN = float(os.environ.get("LUO_IDENTITY_CORE_DIAG_TOP_CONTAIN", "0.990"))
IDENTITY_CORE_DIAG_TAIL_CONTAIN = float(os.environ.get("LUO_IDENTITY_CORE_DIAG_TAIL_CONTAIN", "0.012"))

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
VERSION = "0.4.6"

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
    cmap = _build_cmap(font)

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
    cmap = _build_cmap(font)

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


def _classify_segment_axis(dx: float, dy: float, _angle_gate_unused: float = 0.0):
    """Return (band_name, blend_factor) for a chord, or None if degenerate.

    Bands cover the full [0, 90] range so every chord gets a treatment:
      - within H_BAND of horizontal -> H_BLEND (most aggressive)
      - within V_BAND of vertical   -> V_BLEND
      - remainder (diagonal)        -> DIAG_BLEND (lightest, preserves 撇/捺 speed)
    """
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return None
    angle_deg = abs(math.degrees(math.atan2(dy, dx)))
    if angle_deg > 90:
        angle_deg = 180 - angle_deg
    # angle_deg now in [0, 90]: 0 = horizontal, 90 = vertical
    if angle_deg <= STRAIGHTEN_H_BAND:
        return "h", STRAIGHTEN_H_BLEND
    if angle_deg >= 90 - STRAIGHTEN_V_BAND:
        return "v", STRAIGHTEN_V_BLEND
    return "diag", STRAIGHTEN_DIAG_BLEND


def straighten_strokes(font: TTFont) -> None:
    """Pull off-curve points toward the chord on long near-axis spans.

    For each CJK glyph, walk every contour and look at consecutive on-curve
    points (P_a, P_b). If the chord PaPb is long enough and near horizontal,
    vertical, or 45-degree diagonal, lerp every point lying between them
    perpendicular to the chord by `*_BLEND`. The on-curve endpoints are
    untouched so stroke joinery and turn corners survive.

    This is the v0.4 pivot's structural change: LXGW's quadratic curves
    have natural bow that survives every other refinement; only by
    actively flattening the long spans can Luo escape "soft kai" gesture.
    """
    if STRAIGHTEN_H_BLEND <= 0 and STRAIGHTEN_V_BLEND <= 0 and STRAIGHTEN_DIAG_BLEND <= 0:
        print("[luo] skipped straighten (all blends 0)")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    angle_gate = STRAIGHTEN_ANGLE_GATE
    min_len_ratio = STRAIGHTEN_MIN_LEN_RATIO

    stats = {"h": 0, "v": 0, "diag": 0}
    span_count = 0
    point_count = 0
    glyph_count = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None:
            continue
        if not (0x3400 <= cp <= 0x9FFF):
            continue
        char = chr(cp)
        if char in STRAIGHTEN_SKIP_CHARS:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue

        coords = glyph.coordinates
        flags = glyph.flags
        ends = glyph.endPtsOfContours

        all_xs = [c[0] for c in coords]
        all_ys = [c[1] for c in coords]
        glyph_w = max(all_xs) - min(all_xs)
        glyph_h = max(all_ys) - min(all_ys)
        if glyph_w <= 0 or glyph_h <= 0:
            continue
        glyph_max = max(glyph_w, glyph_h)
        min_len = max(STRAIGHTEN_MIN_LEN_ABS, min_len_ratio * glyph_max)

        new_coords = list(coords)
        glyph_touched = False

        start = 0
        for end in ends:
            n = end - start + 1
            if n < 6:
                start = end + 1
                continue

            on_curve_indices = [
                start + j for j in range(n) if flags[start + j] & 1
            ]
            if len(on_curve_indices) < 2:
                start = end + 1
                continue

            num_oc = len(on_curve_indices)
            for k in range(num_oc):
                i_a = on_curve_indices[k]
                i_b = on_curve_indices[(k + 1) % num_oc]

                # Walk the in-between indices (off-curve points, possibly
                # zero of them); skip when the span has no interior points
                # or wraps to itself.
                if i_b == i_a:
                    continue
                if i_b > i_a:
                    interior = list(range(i_a + 1, i_b))
                else:
                    # Wrap-around at end of contour.
                    interior = list(range(i_a + 1, end + 1)) + list(range(start, i_b))
                if not interior:
                    continue

                ax, ay = coords[i_a]
                bx, by = coords[i_b]
                dx = bx - ax
                dy = by - ay
                length = math.hypot(dx, dy)
                if length < min_len:
                    continue

                axis = _classify_segment_axis(dx, dy, angle_gate)
                if axis is None:
                    continue
                kind, blend = axis
                if blend <= 0:
                    continue

                # Project each interior point onto the chord and lerp it
                # perpendicular toward the line. We move ALONG-axis position
                # alone too (small effect): keep parametric t but pin the
                # perpendicular component down by BLEND.
                #
                # v0.4.2 corner protection: skip individual off-curves whose
                # perpendicular distance from the chord exceeds
                # STRAIGHTEN_MAX_PERP_RATIO. These controls shape a corner
                # (e.g. 字's bao-gai right end, 子/无 横折钩 right end), not a
                # stem bow; pulling them along the chord drags the corner
                # outward and produces a sharp downward spike at the end of
                # long horizontals.
                inv_len = 1.0 / length
                inv_len2 = inv_len * inv_len
                perp_x = -dy * inv_len
                perp_y = dx * inv_len
                max_perp = STRAIGHTEN_MAX_PERP_RATIO * length
                touched_any = False
                for idx in interior:
                    px, py = new_coords[idx]
                    perp_dist = abs((px - ax) * perp_x + (py - ay) * perp_y)
                    if perp_dist > max_perp:
                        continue
                    t = ((px - ax) * dx + (py - ay) * dy) * inv_len2
                    proj_x = ax + t * dx
                    proj_y = ay + t * dy
                    new_x = px + blend * (proj_x - px)
                    new_y = py + blend * (proj_y - py)
                    new_coords[idx] = (int(round(new_x)), int(round(new_y)))
                    point_count += 1
                    touched_any = True
                if not touched_any:
                    continue
                stats[kind] += 1
                span_count += 1
                glyph_touched = True

            start = end + 1

        if glyph_touched:
            for i, c in enumerate(new_coords):
                coords[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] straightened {span_count} spans / {point_count} points "
        f"across {glyph_count} glyphs "
        f"(h={stats['h']} v={stats['v']} diag={stats['diag']}, "
        f"blends={STRAIGHTEN_H_BLEND}/{STRAIGHTEN_V_BLEND}/{STRAIGHTEN_DIAG_BLEND}, "
        f"angle_gate={angle_gate}°, min_len={min_len_ratio:.2f})"
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
    cmap = _build_cmap(font)

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
        "霜露霞雪草落蓝营笔简答篇藏艺蒙节茂荒蓄蒸薄蔽莫苦"
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
        "书言青春者暑量重墨章律吕盈盛曾寒皆熹"
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
# v0.4.1: 0.965 stacked with the IDENTITY_ALL_H_LAYER_X (0.994) all-glyph pass
# pulled secondary horizontals down to ~0.96 — body text 荒 草头第二横, 无 中横,
# 东 中横, 起 己内两横, 代 弋横钩 went missing. Raise the floor and have the
# all-glyph pass skip H_LAYER compression for chars that already passed here.
MULTI_HORIZ_SECONDARY = float(os.environ.get("LUO_MULTI_HORIZ_SECONDARY", "0.985"))  # v0.4.3 audit fix: 0.978 与 H_LAYER 叠后 secondary 横画仍偏弱，再抬一档
TOP_BOTTOM_UPPER_CONTRACT = 0.98

# Final walk-radical containment. The category pass above opens the enclosed
# body; this pass only reins in the lowest, widest 辶 contour on a short
# whitelist so 透/道/遇 stop reading as bottom-heavy.
# Walk-radical (辶) final containment whitelist. Started in v0.3 with five
# anchor glyphs; v0.4 adds the high-frequency GB2312 level-1 走之 chars so
# the bottom doesn't read as overweight in body copy. Parameters
# (WALK_FINAL_*) stay frozen; only this list grows.
WALK_FINAL_CHARS = "透道遇述远近过这还进通达选送逢迁连运遍适迹造"
WALK_FINAL_X_CONTAIN = float(os.environ.get("LUO_WALK_FINAL_X_CONTAIN", "0.910"))
WALK_FINAL_BOTTOM_RAISE_EM = float(os.environ.get("LUO_WALK_FINAL_BOTTOM_RAISE_EM", "0.050"))
WALK_FINAL_TAIL_CONTAIN = float(os.environ.get("LUO_WALK_FINAL_TAIL_CONTAIN", "0.125"))
WALK_BODY_TARGET_TOP = float(os.environ.get("LUO_WALK_BODY_TARGET_TOP", "0.860"))
WALK_BODY_TOP_RAISE_MAX = float(os.environ.get("LUO_WALK_BODY_TOP_RAISE_MAX", "0.052"))
WALK_BODY_X_CONTAIN = float(os.environ.get("LUO_WALK_BODY_X_CONTAIN", "0.968"))
WALK_FINAL_SETTLE_EM = float(os.environ.get("LUO_WALK_FINAL_SETTLE_EM", "0.018"))

# 黑部点群 needs protection from generic xiaokai-dot shaping. In 墨, those dots
# sit inside a dense stacked glyph; keep thickness and only shorten their long
# axis slightly so they remain compact without becoming slash-like.
BLACK_DOT_CLUSTER_CHARS = "墨"
BLACK_DOT_CLUSTER_LONG_AXIS = float(os.environ.get("LUO_BLACK_DOT_CLUSTER_LONG_AXIS", "0.90"))
BLACK_DOT_CLUSTER_SHORT_AXIS = float(os.environ.get("LUO_BLACK_DOT_CLUSTER_SHORT_AXIS", "1.00"))

EXTRA_DENSE_CHARS = "落藏霞霜露馈赢耀魔籍麟题额锦续群贤禊觞湍幽怀"

# v0.4.1 print-kai balance: these are component-balance rules, not another
# global weight pass. The goal is left-side subordination and open dense
# counters; pure BOLDEN changes cannot express that hierarchy.
KAI_BALANCE_WATER_CHARS = (
    "清源落流润淡游湍激法汉海江河湖溪洗波测浪温浅深洪"
    "泪注泽沐沙治沿沟没油消液洋洁活"
)
# v0.4.1: 0.915/0.910 + the in-function bottom-dot extra cap (min 0.920/0.900)
# made 源 third dot break into chips at body sizes. Roll back one notch and let
# the WEB_PRESENCE floor catch the remaining cases.
KAI_BALANCE_WATER_X_SCALE = float(os.environ.get("LUO_KAI_BALANCE_WATER_X_SCALE", "0.950"))  # v0.4.3 audit fix: 0.940 在源/清/落 body size 偶尔丢三点，再放松一档
KAI_BALANCE_WATER_Y_SCALE = float(os.environ.get("LUO_KAI_BALANCE_WATER_Y_SCALE", "0.945"))  # v0.4.3 audit fix: 同步放松，保证三点在 dot floor 内仍可见
KAI_BALANCE_WATER_BOTTOM_RAISE_EM = float(os.environ.get("LUO_KAI_BALANCE_WATER_BOTTOM_RAISE_EM", "0.024"))
KAI_BALANCE_WATER_TOP_RAISE_EM = float(os.environ.get("LUO_KAI_BALANCE_WATER_TOP_RAISE_EM", "0.006"))

KAI_BALANCE_DENSE_COUNTER_CHARS = "魔赢耀题额籍麟馈覆藏霜霞露感皆熹苦"
KAI_BALANCE_COUNTER_EXPAND_X = float(os.environ.get("LUO_KAI_BALANCE_COUNTER_EXPAND_X", "1.125"))
KAI_BALANCE_COUNTER_EXPAND_Y = float(os.environ.get("LUO_KAI_BALANCE_COUNTER_EXPAND_Y", "1.095"))
KAI_BALANCE_DENSE_LAYER_X = float(os.environ.get("LUO_KAI_BALANCE_DENSE_LAYER_X", "0.970"))
KAI_BALANCE_DENSE_LAYER_Y = float(os.environ.get("LUO_KAI_BALANCE_DENSE_LAYER_Y", "0.965"))
KAI_BALANCE_DENSE_LAYER_GAP_EM = float(os.environ.get("LUO_KAI_BALANCE_DENSE_LAYER_GAP_EM", "0.004"))
KAI_BALANCE_DENSE_UPPER_X = float(os.environ.get("LUO_KAI_BALANCE_DENSE_UPPER_X", "0.985"))
KAI_BALANCE_DENSE_UPPER_Y = float(os.environ.get("LUO_KAI_BALANCE_DENSE_UPPER_Y", "0.970"))

KAI_BALANCE_BOOK_DOT_X_SCALE = float(os.environ.get("LUO_KAI_BALANCE_BOOK_DOT_X_SCALE", "0.940"))
KAI_BALANCE_BOOK_DOT_Y_SCALE = float(os.environ.get("LUO_KAI_BALANCE_BOOK_DOT_Y_SCALE", "0.880"))
KAI_BALANCE_BOOK_DOT_RAISE_EM = float(os.environ.get("LUO_KAI_BALANCE_BOOK_DOT_RAISE_EM", "0.006"))

KAI_BALANCE_SPEECH_CHARS = (
    "言计订讣认讥讦讧讨让讪讫训议讯记讲讳讴讵讶讷许讹论"
    "讼讽设访诀证评诅识诈诉诊诋诌词译试诗诚话诞诡询"
    "该详诧诫诬语误诱诲说诵请诸诺读课谁调谅谈谊谋谍"
    "谎谐谓谗谦谧谨"
)
KAI_BALANCE_SPEECH_SECONDARY_X = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_SECONDARY_X", "0.945"))
KAI_BALANCE_SPEECH_SECONDARY_Y = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_SECONDARY_Y", "0.960"))
KAI_BALANCE_SPEECH_DOT_X = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_DOT_X", "0.880"))  # v0.4.3 audit fix: 言/讠点 body size 偏小，放宽 X 让点不收成针
KAI_BALANCE_SPEECH_DOT_Y = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_DOT_Y", "0.860"))  # v0.4.3 audit fix: 同步放宽 Y
KAI_BALANCE_SPEECH_COUNTER_X = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_COUNTER_X", "1.110"))
KAI_BALANCE_SPEECH_COUNTER_Y = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_COUNTER_Y", "1.060"))
KAI_BALANCE_SPEECH_UPPER_CHARS = "言"
KAI_BALANCE_SPEECH_UPPER_X = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_UPPER_X", "0.975"))
KAI_BALANCE_SPEECH_UPPER_Y = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_UPPER_Y", "0.900"))

KAI_BALANCE_ROOF_CHARS = "实寒字学安宇宙宿定室宝完宣家容密客审宜宁寄察"
KAI_BALANCE_ROOF_BOTTOM_X = float(os.environ.get("LUO_KAI_BALANCE_ROOF_BOTTOM_X", "0.945"))  # v0.4.3 audit fix: 0.925 让 字/宇/宙/家 底压得过狠，放宽到 0.945
KAI_BALANCE_ROOF_BOTTOM_Y = float(os.environ.get("LUO_KAI_BALANCE_ROOF_BOTTOM_Y", "0.945"))  # v0.4.3 audit fix: 同步抬高，避免顶轻底碎
KAI_BALANCE_ROOF_BOTTOM_RAISE_EM = float(os.environ.get("LUO_KAI_BALANCE_ROOF_BOTTOM_RAISE_EM", "0.014"))

# v0.4.1: 0.945 / 0.960 starved 地/源/起/代-style left components at body
# sizes; the wide_split / wide_diag / water passes already carry left-side
# subordination for most affected chars. Roll back one notch and trim the
# split list to glyphs where the left radical truly benefits from extra
# subordination beyond what wide_split provides.
KAI_BALANCE_SIDE_SPLIT_CHARS = "欢剑给怡往径征观轻净缪"
KAI_BALANCE_SIDE_LEFT_X = float(os.environ.get("LUO_KAI_BALANCE_SIDE_LEFT_X", "0.970"))  # v0.4.3 audit fix: 0.960 仍让 split 字左偏旁过弱，再放松一档
KAI_BALANCE_SIDE_LEFT_Y = float(os.environ.get("LUO_KAI_BALANCE_SIDE_LEFT_Y", "0.980"))  # v0.4.3 audit fix: 同步放松
KAI_BALANCE_SIDE_LEFT_GAP_EM = float(os.environ.get("LUO_KAI_BALANCE_SIDE_LEFT_GAP_EM", "-0.002"))
KAI_BALANCE_SIDE_COUNTER_X = float(os.environ.get("LUO_KAI_BALANCE_SIDE_COUNTER_X", "1.060"))
KAI_BALANCE_SIDE_COUNTER_Y = float(os.environ.get("LUO_KAI_BALANCE_SIDE_COUNTER_Y", "1.035"))

# Web-size guardrails: component-balance passes may compress a contour that is
# already only 1-2 device pixels at body text sizes. Preserve a minimum visible
# extent for dot-like marks and short horizontals without changing main stems.
# v0.4.1 raises both floors so 地/发/东/亦/源 (氵 third dot) stop breaking into
# chips at 17-19px body. The dot floor is the primary lever; the horizontal
# floor secondarily protects 草头 / 中横 in 荒/无/东.
WEB_PRESENCE_DOT_MIN_EM = float(os.environ.get("LUO_WEB_PRESENCE_DOT_MIN_EM", "0.160"))  # v0.4.3 audit fix: 0.150 在 17-19px body 仍偶有 氵 第三点掉点，地板再抬一档
WEB_PRESENCE_H_MIN_EM = float(os.environ.get("LUO_WEB_PRESENCE_H_MIN_EM", "0.080"))  # v0.4.3 audit fix: 配合 H_LAYER 放松，给短横留更多余量

# Final web-body readability guard. v0.4.1 makes this dynamic so it tracks the
# actual prose shown on the homepage and printed proof: index.html, README.md,
# proof/a4.html, plus any CSS-embedded strings. The defect-set chars below are
# always included so visible regressions reported on a build (笔/书/源/览/发/
# 地/荒/无/东/亦/起/代) stay covered even if site copy changes.
SITE_BODY_READABILITY_FILES: tuple[Path, ...] = (
    ROOT / "index.html",
    ROOT / "README.md",
    ROOT / "proof" / "a4.html",
    ROOT / "assets" / "styles" / "luo.css",
    ROOT / "assets" / "styles" / "print.css",
)
SITE_BODY_READABILITY_DEFECT_CHARS = "笔书源览发地荒无东亦起代"
SITE_BODY_DOT_MIN_EM = float(os.environ.get("LUO_SITE_BODY_DOT_MIN_EM", "0.150"))
SITE_BODY_H_MIN_EM = float(os.environ.get("LUO_SITE_BODY_H_MIN_EM", "0.082"))
SITE_BODY_DOT_MAX_SCALE = float(os.environ.get("LUO_SITE_BODY_DOT_MAX_SCALE", "1.18"))
SITE_BODY_H_MAX_SCALE = float(os.environ.get("LUO_SITE_BODY_H_MAX_SCALE", "1.12"))
SITE_BODY_SECONDARY_SCALE = float(os.environ.get("LUO_SITE_BODY_SECONDARY_SCALE", "1.020"))

# Final visible-defect corrections for the current audit set. These are kept
# after identity/readability so they compensate pass stacking without changing
# global weight, straightening, or component-category behavior.
VISIBLE_PROBLEM_GLYPHS = "两月或则魔"


def _collect_site_body_readability_chars() -> str:
    """Build the body-readability char set from on-disk site/prose files.

    Each call rescans the configured files plus the always-on defect set so
    the guard tracks visible site prose without manual list maintenance.
    """
    chunks: list[str] = []
    for path in SITE_BODY_READABILITY_FILES:
        if not path.exists():
            continue
        try:
            chunks.append(cjk_from_text(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    chunks.append(SITE_BODY_READABILITY_DEFECT_CHARS)
    return "".join(dict.fromkeys("".join(chunks)))

KAI_BALANCE_STACK_CHARS = "实寒库头帝眷背"
KAI_BALANCE_STACK_BOTTOM_X = float(os.environ.get("LUO_KAI_BALANCE_STACK_BOTTOM_X", "0.930"))  # v0.4.3 audit fix: 0.910 让 实/寒/库/头 底碎，放宽
KAI_BALANCE_STACK_BOTTOM_Y = float(os.environ.get("LUO_KAI_BALANCE_STACK_BOTTOM_Y", "0.910"))  # v0.4.3 audit fix: 同步从 0.885 抬到 0.910
KAI_BALANCE_STACK_BOTTOM_RAISE_EM = float(os.environ.get("LUO_KAI_BALANCE_STACK_BOTTOM_RAISE_EM", "0.024"))

KAI_BALANCE_WIDE_DIAG_CHARS = "斗考兴今式气全分走去一而后层可"
KAI_BALANCE_WIDE_EDGE_CONTAIN = float(os.environ.get("LUO_KAI_BALANCE_WIDE_EDGE_CONTAIN", "0.030"))
KAI_BALANCE_WIDE_BOTTOM_CONTAIN = float(os.environ.get("LUO_KAI_BALANCE_WIDE_BOTTOM_CONTAIN", "0.045"))
KAI_BALANCE_WIDE_BOTTOM_RAISE_EM = float(os.environ.get("LUO_KAI_BALANCE_WIDE_BOTTOM_RAISE_EM", "0.006"))


def _build_reverse_cmap(font: TTFont) -> dict[str, int]:
    """Memoised glyph-name -> codepoint map for one font instance."""
    cached = getattr(font, _RCMAP_CACHE_ATTR, None)
    if cached is not None:
        return cached
    rcmap: dict[str, int] = {}
    for cp, gname in _build_cmap(font).items():
        rcmap[gname] = cp
    setattr(font, _RCMAP_CACHE_ATTR, rcmap)
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
            "n": end - start + 1,
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


def _dot_long_axis(xs, ys) -> tuple[float, float] | None:
    """Pick the long-axis unit vector of a dot-like contour.

    Walks every pair of points (O(n²)) to find the diameter; with n_pts capped
    at DOT_MAX_POINTS=20 this is at most ~190 ops per dot, far cheaper than
    setting up PCA. Returns None when the contour is degenerate (all points
    coincide).
    """
    n = len(xs)
    long_axis_len_sq = 0.0
    long_ax = 1.0
    long_ay = 0.0
    for a in range(n):
        xa = xs[a]
        ya = ys[a]
        for b in range(a + 1, n):
            dxv = xs[b] - xa
            dyv = ys[b] - ya
            d2 = dxv * dxv + dyv * dyv
            if d2 > long_axis_len_sq:
                long_axis_len_sq = d2
                long_ax, long_ay = dxv, dyv
    long_len = math.hypot(long_ax, long_ay)
    if long_len < 1e-6:
        return None
    return long_ax / long_len, long_ay / long_len


def _glyph_box(coords) -> tuple[float, float, float, float, float, float, float, float] | None:
    """Return (x_min, x_max, y_min, y_max, x_range, y_range, cx, cy) or None.

    Reused by every identity sub-pass to avoid duplicating the same nine-line
    bounds-and-centroid block. Returns None when the glyph is degenerate
    (empty, zero-width, or zero-height).
    """
    if not coords:
        return None
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    x_min = min(xs)
    x_max = max(xs)
    y_min = min(ys)
    y_max = max(ys)
    x_range = x_max - x_min
    y_range = y_max - y_min
    if x_range <= 0 or y_range <= 0:
        return None
    return (x_min, x_max, y_min, y_max, x_range, y_range,
            (x_min + x_max) / 2.0, (y_min + y_max) / 2.0)


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


def _refine_identity_posture(glyph, glyf, upm: int) -> None:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None:
        return
    _x_min, _x_max, y_min, y_max, _x_range, y_range, cx, _cy = box
    top_start = y_min + y_range * 0.58
    bottom_end = y_min + y_range * 0.22
    top_raise = IDENTITY_POSTURE_TOP_RAISE_EM * upm
    bottom_settle = IDENTITY_POSTURE_BOTTOM_SETTLE_EM * upm

    for i in range(len(coords)):
        x, y = coords[i]
        new_x = float(x)
        new_y = float(y)

        if y > top_start and y_max > top_start:
            t = (y - top_start) / (y_max - top_start)
            factor = 1.0 - (1.0 - IDENTITY_POSTURE_UPPER_X_CONTAIN) * t
            new_x = cx + (new_x - cx) * factor
            new_y += top_raise * t
        elif y < bottom_end and bottom_end > y_min:
            t = (bottom_end - y) / (bottom_end - y_min)
            factor = 1.0 + (IDENTITY_POSTURE_LOWER_X_EXPAND - 1.0) * t
            new_x = cx + (new_x - cx) * factor
            new_y -= bottom_settle * t

        coords[i] = (int(round(new_x)), int(round(new_y)))

    glyph.recalcBounds(glyf)


def _refine_identity_frame(glyph, glyf, upm: int) -> None:
    if glyph.numberOfContours < 2:
        return
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None:
        return
    glyph_x_min, glyph_x_max, glyph_y_min, glyph_y_max, glyph_w, glyph_h, _cx, _cy = box

    contours = _contour_info(glyph, coords)
    if not contours:
        return
    max_area = max(float(c["area"]) for c in contours)
    if max_area <= 0:
        return

    for c in contours:
        area = float(c["area"])
        x_min = float(c["xmin"])
        x_max = float(c["xmax"])
        y_min = float(c["ymin"])
        y_max = float(c["ymax"])
        # Counter contours in frame glyphs sit inside the outer frame and are
        # much smaller. Expand those counters from their own center to create a
        # Luo-specific print counter instead of tracing the source frame.
        inset = (
            x_min > glyph_x_min + glyph_w * 0.08
            and x_max < glyph_x_max - glyph_w * 0.08
            and y_min > glyph_y_min + glyph_h * 0.08
            and y_max < glyph_y_max - glyph_h * 0.08
        )
        if not inset or area > max_area * 0.62:
            continue

        cx = float(c["cx"])
        cy = float(c["cy"])
        for i in range(int(c["start"]), int(c["end"]) + 1):
            x, y = coords[i]
            new_x = cx + (x - cx) * IDENTITY_FRAME_COUNTER_EXPAND_X
            new_y = cy + (y - cy) * IDENTITY_FRAME_COUNTER_EXPAND_Y
            coords[i] = (int(round(new_x)), int(round(new_y)))

    glyph.recalcBounds(glyf)


def _refine_identity_frame_risk(glyph, glyf) -> None:
    """Open counters in high-overlap frame glyphs without changing the frame."""
    if glyph.numberOfContours < 2:
        return
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None:
        return
    glyph_x_min, glyph_x_max, glyph_y_min, glyph_y_max, glyph_w, glyph_h, _cx, _cy = box

    contours = _contour_info(glyph, coords)
    if not contours:
        return
    max_area = max(float(c["area"]) for c in contours)
    if max_area <= 0:
        return

    for c in contours:
        area = float(c["area"])
        c_xmin = float(c["xmin"])
        c_xmax = float(c["xmax"])
        c_ymin = float(c["ymin"])
        c_ymax = float(c["ymax"])
        c_cy = float(c["cy"])
        c_w = max(1.0, c_xmax - c_xmin)
        c_h = max(1.0, c_ymax - c_ymin)
        inset = (
            c_xmin > glyph_x_min + glyph_w * 0.07
            and c_xmax < glyph_x_max - glyph_w * 0.07
            and c_ymin > glyph_y_min + glyph_h * 0.05
            and c_ymax < glyph_y_max - glyph_h * 0.05
            and area < max_area * 0.46
        )
        if not inset:
            continue

        # Avoid making tiny ticks or accidental dots into oversized holes.
        if c_w < glyph_w * 0.11 or c_h < glyph_h * 0.07:
            continue

        cx = float(c["cx"])
        cy = float(c["cy"])
        for i in range(int(c["start"]), int(c["end"]) + 1):
            x, y = coords[i]
            new_x = cx + (x - cx) * IDENTITY_RISK_FRAME_COUNTER_EXPAND_X
            new_y = cy + (y - cy) * IDENTITY_RISK_FRAME_COUNTER_EXPAND_Y
            coords[i] = (int(round(new_x)), int(round(new_y)))

    glyph.recalcBounds(glyf)


def _refine_identity_multi_horiz(glyph, glyf) -> None:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None:
        return
    _x_min, _x_max, y_min, _y_max, _x_range, y_range, cx, cy = box
    bottom_cut = y_min + y_range * 0.28

    for i in range(len(coords)):
        x, y = coords[i]
        dist_mid = 1.0 - min(1.0, abs(y - cy) / max(1.0, y_range * 0.38))
        new_x = float(x)
        if dist_mid > 0:
            factor = 1.0 - (1.0 - IDENTITY_MULTI_MID_CONTAIN) * dist_mid
            new_x = cx + (new_x - cx) * factor
        if y < bottom_cut and bottom_cut > y_min:
            t = (bottom_cut - y) / (bottom_cut - y_min)
            factor = 1.0 + (IDENTITY_MULTI_BOTTOM_EXPAND - 1.0) * t
            new_x = cx + (new_x - cx) * factor
        coords[i] = (int(round(new_x)), y)

    glyph.recalcBounds(glyf)


def _refine_identity_layer_risk(glyph, glyf, upm: int) -> None:
    """Separate high-overlap top/bottom glyphs through counters and hierarchy."""
    if glyph.numberOfContours < 2:
        return
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None:
        return
    glyph_x_min, glyph_x_max, glyph_y_min, glyph_y_max, glyph_w, glyph_h, cx, cy = box
    top_raise = IDENTITY_LAYER_TOP_RAISE_EM * upm
    bottom_settle = IDENTITY_LAYER_BOTTOM_SETTLE_EM * upm

    contours = _contour_info(glyph, coords)
    if not contours:
        return
    max_area = max(float(c["area"]) for c in contours)
    if max_area <= 0:
        return

    for c in contours:
        area = float(c["area"])
        c_xmin = float(c["xmin"])
        c_xmax = float(c["xmax"])
        c_ymin = float(c["ymin"])
        c_ymax = float(c["ymax"])
        ccx = float(c["cx"])
        ccy = float(c["cy"])
        c_w = max(1.0, c_xmax - c_xmin)
        c_h = max(1.0, c_ymax - c_ymin)
        aspect = c_w / c_h
        inset = (
            c_xmin > glyph_x_min + glyph_w * 0.07
            and c_xmax < glyph_x_max - glyph_w * 0.07
            and c_ymin > glyph_y_min + glyph_h * 0.04
            and c_ymax < glyph_y_max - glyph_h * 0.04
            and area < max_area * 0.38
        )
        secondary = (
            area < max_area * 0.24
            and c_w > glyph_w * 0.16
            and c_h > glyph_h * 0.05
        )
        top_layer = ccy > cy + glyph_h * 0.14 and c_h < glyph_h * 0.58
        bottom_layer = ccy < cy - glyph_h * 0.20 and c_h < glyph_h * 0.50
        horizontal_gap = aspect > 1.85 and c_h < glyph_h * 0.18

        for i in range(int(c["start"]), int(c["end"]) + 1):
            x, y = coords[i]
            new_x = float(x)
            new_y = float(y)

            if inset:
                new_x = ccx + (new_x - ccx) * IDENTITY_LAYER_COUNTER_EXPAND_X
                new_y = ccy + (new_y - ccy) * IDENTITY_LAYER_COUNTER_EXPAND_Y
            elif secondary:
                scale = IDENTITY_LAYER_SECONDARY_SCALE
                if horizontal_gap:
                    scale = min(scale, 0.980)
                new_x = ccx + (new_x - ccx) * scale
                new_y = ccy + (new_y - ccy) * scale

            if top_layer:
                new_x = cx + (new_x - cx) * IDENTITY_LAYER_TOP_CONTAIN
                new_y += top_raise
            elif bottom_layer:
                new_y -= bottom_settle

            coords[i] = (int(round(new_x)), int(round(new_y)))

    glyph.recalcBounds(glyf)


def _refine_identity_diagonal(glyph, glyf, upm: int) -> None:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None:
        return
    _x_min, _x_max, _y_min, _y_max, x_range, y_range, cx, cy = box
    max_shift = IDENTITY_DIAG_EDGE_EXPAND * upm

    for i in range(len(coords)):
        x, y = coords[i]
        edge_t = min(1.0, abs(x - cx) / max(1.0, x_range * 0.50))
        vertical_t = min(1.0, abs(y - cy) / max(1.0, y_range * 0.50))
        tension = edge_t * vertical_t
        new_x = x + math.copysign(max_shift * tension, x - cx if x != cx else 1)
        new_y = cy + (y - cy) * (1.0 + 0.010 * vertical_t)
        coords[i] = (int(round(new_x)), int(round(new_y)))

    glyph.recalcBounds(glyf)


def _scale_contour(coords, c, scale_x: float = 1.0, scale_y: float = 1.0,
                   shift_x: float = 0.0, shift_y: float = 0.0) -> None:
    cx = float(c["cx"])
    cy = float(c["cy"])
    for i in range(int(c["start"]), int(c["end"]) + 1):
        x, y = coords[i]
        new_x = cx + (x - cx) * scale_x + shift_x
        new_y = cy + (y - cy) * scale_y + shift_y
        coords[i] = (int(round(new_x)), int(round(new_y)))


def _presence_guarded_scale(scale: float, current_extent: float, min_extent: float) -> float:
    if scale >= 1.0 or current_extent <= 0 or min_extent <= 0:
        return scale
    if current_extent <= min_extent:
        return 1.0
    return max(scale, min(1.0, min_extent / current_extent))


def _presence_floor_scale(current_extent: float, min_extent: float, max_scale: float) -> float:
    if current_extent <= 0 or min_extent <= 0 or max_scale <= 1.0:
        return 1.0
    if current_extent >= min_extent:
        return 1.0
    return min(max_scale, max(1.0, min_extent / current_extent))


def _contour_signed_area(coords, start: int, end: int) -> float:
    area = 0.0
    pts = [coords[i] for i in range(start, end + 1)]
    if len(pts) < 3:
        return 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _refine_kai_balance_water(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 3:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    glyph_area = glyph_w * glyph_h
    touched = False

    for c in _contour_info(glyph, coords):
        c_xmax = float(c["xmax"])
        c_ymin = float(c["ymin"])
        c_ymax = float(c["ymax"])
        c_cx = float(c["cx"])
        c_cy = float(c["cy"])
        c_w = max(1.0, c_xmax - float(c["xmin"]))
        c_h = max(1.0, c_ymax - c_ymin)
        area = float(c["area"])
        # Three-water contours live in the left third and are separate strokes.
        # Keep the filter conservative so the right-hand body is never touched.
        if (
            c_cx > x_min + glyph_w * 0.34
            or c_xmax > x_min + glyph_w * 0.40
            or area > glyph_area * 0.16
            or c_w > glyph_w * 0.34
            or c_h > glyph_h * 0.48
        ):
            continue

        y_t = (c_cy - y_min) / max(1.0, glyph_h)
        shift_y = 0.0
        scale_x = KAI_BALANCE_WATER_X_SCALE
        scale_y = KAI_BALANCE_WATER_Y_SCALE
        # v0.4.1: removed the per-position extra cap (was clamping below 0.920
        # / 0.895) that crushed the 氵 bottom dot in 源/清/落 at body sizes.
        # Position-driven shift_y still keeps the radical visually balanced.
        if y_t < 0.43:
            shift_y = KAI_BALANCE_WATER_BOTTOM_RAISE_EM * upm
        elif y_t > 0.70:
            shift_y = KAI_BALANCE_WATER_TOP_RAISE_EM * upm

        dot_min = WEB_PRESENCE_DOT_MIN_EM * upm
        scale_x = _presence_guarded_scale(scale_x, c_w, dot_min)
        scale_y = _presence_guarded_scale(scale_y, c_h, dot_min)
        _scale_contour(coords, c, scale_x=scale_x, scale_y=scale_y, shift_y=shift_y)
        touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_kai_balance_dense_counters(char: str, glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 3:
        return False
    glyph_x_min, glyph_x_max, glyph_y_min, glyph_y_max, glyph_w, glyph_h, _cx, _cy = box
    glyph_area = glyph_w * glyph_h
    touched = False

    for c in _contour_info(glyph, coords):
        c_xmin = float(c["xmin"])
        c_xmax = float(c["xmax"])
        c_ymin = float(c["ymin"])
        c_ymax = float(c["ymax"])
        c_cy = float(c["cy"])
        c_w = max(1.0, c_xmax - c_xmin)
        c_h = max(1.0, c_ymax - c_ymin)
        area = float(c["area"])
        if area <= 0:
            continue
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        inset = (
            c_xmin > glyph_x_min + glyph_w * 0.06
            and c_xmax < glyph_x_max - glyph_w * 0.04
            and c_ymin > glyph_y_min + glyph_h * 0.03
            and c_ymax < glyph_y_max - glyph_h * 0.03
            and c_w > glyph_w * 0.06
            and c_h > glyph_h * 0.035
            and area < glyph_area * 0.14
        )
        # In this source pipeline, positive inner contours are counters/holes.
        if inset and signed > 0:
            _scale_contour(
                coords,
                c,
                scale_x=KAI_BALANCE_COUNTER_EXPAND_X,
                scale_y=KAI_BALANCE_COUNTER_EXPAND_Y,
            )
            touched = True
            continue

        aspect = c_w / c_h
        layer = (
            signed <= 0
            and aspect > 2.05
            and glyph_y_min + glyph_h * 0.18 < c_ymax
            and c_ymin < glyph_y_max - glyph_h * 0.10
            and c_w > glyph_w * 0.18
            and c_h < glyph_h * 0.22
            and area < glyph_area * 0.22
        )
        if not layer:
            upper_component = (
                signed <= 0
                and c_cy > glyph_y_min + glyph_h * 0.52
                and c_ymax < glyph_y_max - glyph_h * 0.015
                and c_w < glyph_w * 0.70
                and c_h < glyph_h * 0.62
                and glyph_area * 0.10 < area < glyph_area * 0.40
            )
            if not upper_component:
                continue
            upper_scale_y = _presence_guarded_scale(
                KAI_BALANCE_DENSE_UPPER_Y,
                c_h,
                WEB_PRESENCE_H_MIN_EM * upm,
            )
            _scale_contour(
                coords,
                c,
                scale_x=KAI_BALANCE_DENSE_UPPER_X,
                scale_y=upper_scale_y,
            )
            touched = True
            continue

        y_t = (float(c["cy"]) - glyph_y_min) / max(1.0, glyph_h)
        shift_y = 0.0
        if y_t > 0.58:
            shift_y = KAI_BALANCE_DENSE_LAYER_GAP_EM * upm
        elif y_t < 0.34:
            shift_y = -KAI_BALANCE_DENSE_LAYER_GAP_EM * upm * 0.65
        if char in "熹喜" and y_t < 0.28:
            shift_y *= 0.5

        _scale_contour(
            coords,
            c,
            scale_x=KAI_BALANCE_DENSE_LAYER_X,
            scale_y=_presence_guarded_scale(
                KAI_BALANCE_DENSE_LAYER_Y,
                c_h,
                WEB_PRESENCE_H_MIN_EM * upm,
            ),
            shift_y=shift_y,
        )
        touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_kai_balance_book_dot(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    touched = False
    for c in _contour_info(glyph, coords):
        c_cx = float(c["cx"])
        c_cy = float(c["cy"])
        c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
        if (
            c_cx < x_min + glyph_w * 0.68
            or c_cy < y_min + glyph_h * 0.68
            or c_w > glyph_w * 0.34
            or c_h > glyph_h * 0.32
        ):
            continue
        dot_min = WEB_PRESENCE_DOT_MIN_EM * upm
        _scale_contour(
            coords,
            c,
            scale_x=_presence_guarded_scale(KAI_BALANCE_BOOK_DOT_X_SCALE, c_w, dot_min),
            scale_y=_presence_guarded_scale(KAI_BALANCE_BOOK_DOT_Y_SCALE, c_h, dot_min),
            shift_y=KAI_BALANCE_BOOK_DOT_RAISE_EM * upm,
        )
        touched = True
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_kai_balance_speech(char: str, glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    glyph_x_min, glyph_x_max, glyph_y_min, glyph_y_max, glyph_w, glyph_h, cx, _cy = box
    glyph_area = glyph_w * glyph_h
    touched = False

    for c in _contour_info(glyph, coords):
        c_xmin = float(c["xmin"])
        c_xmax = float(c["xmax"])
        c_ymin = float(c["ymin"])
        c_ymax = float(c["ymax"])
        c_cx = float(c["cx"])
        c_cy = float(c["cy"])
        c_w = max(1.0, c_xmax - c_xmin)
        c_h = max(1.0, c_ymax - c_ymin)
        area = float(c["area"])
        aspect = c_w / c_h
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))

        upper_horiz = (
            char in KAI_BALANCE_SPEECH_UPPER_CHARS
            and aspect > 3.0
            and c_h < glyph_h * 0.16
            and glyph_y_min + glyph_h * 0.58 < c_cy < glyph_y_min + glyph_h * 0.88
            and area < glyph_area * 0.18
        )
        if upper_horiz:
            _scale_contour(
                coords,
                c,
                scale_x=KAI_BALANCE_SPEECH_UPPER_X,
                scale_y=_presence_guarded_scale(
                    KAI_BALANCE_SPEECH_UPPER_Y,
                    c_h,
                    WEB_PRESENCE_H_MIN_EM * upm,
                ),
            )
            touched = True
            continue

        top_dot = (
            c_cy > glyph_y_min + glyph_h * 0.72
            and c_w < glyph_w * 0.42
            and c_h < glyph_h * 0.24
            and area < glyph_area * 0.075
        )
        if top_dot:
            dot_min = WEB_PRESENCE_DOT_MIN_EM * upm
            _scale_contour(
                coords,
                c,
                scale_x=_presence_guarded_scale(KAI_BALANCE_SPEECH_DOT_X, c_w, dot_min),
                scale_y=_presence_guarded_scale(KAI_BALANCE_SPEECH_DOT_Y, c_h, dot_min),
            )
            touched = True
            continue

        secondary_horiz = (
            aspect > 3.2
            and c_h < glyph_h * 0.16
            and glyph_y_min + glyph_h * 0.28 < c_cy < glyph_y_min + glyph_h * 0.78
        )
        if secondary_horiz:
            _scale_contour(
                coords,
                c,
                scale_x=KAI_BALANCE_SPEECH_SECONDARY_X,
                scale_y=_presence_guarded_scale(
                    KAI_BALANCE_SPEECH_SECONDARY_Y,
                    c_h,
                    WEB_PRESENCE_H_MIN_EM * upm,
                ),
            )
            touched = True
            continue

        inset_counter = (
            signed > 0
            and c_xmin > glyph_x_min + glyph_w * 0.08
            and c_xmax < glyph_x_max - glyph_w * 0.08
            and c_ymin > glyph_y_min + glyph_h * 0.04
            and c_ymax < glyph_y_max - glyph_h * 0.04
            and area < glyph_area * 0.18
        )
        if inset_counter:
            _scale_contour(
                coords,
                c,
                scale_x=KAI_BALANCE_SPEECH_COUNTER_X,
                scale_y=KAI_BALANCE_SPEECH_COUNTER_Y,
            )
            touched = True

    if touched:
        # Keep the speech stack optically centered after secondary compression.
        for i in range(len(coords)):
            x, y = coords[i]
            dist_mid = 1.0 - min(1.0, abs(x - cx) / max(1.0, glyph_w * 0.50))
            if dist_mid > 0 and glyph_y_min + glyph_h * 0.26 < y < glyph_y_min + glyph_h * 0.86:
                new_x = cx + (x - cx) * (1.0 - 0.010 * dist_mid)
                coords[i] = (int(round(new_x)), y)
        glyph.recalcBounds(glyf)
    return touched


def _refine_kai_balance_side_split(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    glyph_x_min, glyph_x_max, glyph_y_min, glyph_y_max, glyph_w, glyph_h, _cx, _cy = box
    glyph_area = glyph_w * glyph_h
    left_limit = glyph_x_min + glyph_w * 0.46
    touched = False

    for c in _contour_info(glyph, coords):
        c_xmin = float(c["xmin"])
        c_xmax = float(c["xmax"])
        c_ymin = float(c["ymin"])
        c_ymax = float(c["ymax"])
        c_w = max(1.0, c_xmax - c_xmin)
        c_h = max(1.0, c_ymax - c_ymin)
        area = float(c["area"])
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))

        # Left-side radicals often need lower gray, but earlier global
        # half-glyph narrowing was too blunt. Touch only self-contained left
        # contours and preserve their component gap with a tiny outward shift.
        left_component = (
            signed <= 0
            and c_xmax <= left_limit
            and c_w < glyph_w * 0.38
            and c_h < glyph_h * 0.78
            and glyph_area * 0.006 < area < glyph_area * 0.18
        )
        if left_component:
            component_min = WEB_PRESENCE_DOT_MIN_EM * upm
            _scale_contour(
                coords,
                c,
                scale_x=_presence_guarded_scale(KAI_BALANCE_SIDE_LEFT_X, c_w, component_min),
                scale_y=_presence_guarded_scale(KAI_BALANCE_SIDE_LEFT_Y, c_h, component_min),
                shift_x=KAI_BALANCE_SIDE_LEFT_GAP_EM * upm,
            )
            touched = True
            continue

        right_counter = (
            signed > 0
            and c_xmin > glyph_x_min + glyph_w * 0.34
            and c_xmax < glyph_x_max - glyph_w * 0.035
            and c_ymin > glyph_y_min + glyph_h * 0.035
            and c_ymax < glyph_y_max - glyph_h * 0.035
            and c_w > glyph_w * 0.06
            and c_h > glyph_h * 0.04
            and area < glyph_area * 0.15
        )
        if right_counter:
            _scale_contour(
                coords,
                c,
                scale_x=KAI_BALANCE_SIDE_COUNTER_X,
                scale_y=KAI_BALANCE_SIDE_COUNTER_Y,
            )
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_kai_balance_roof_bottom(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    _x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    glyph_area = glyph_w * glyph_h
    touched = False
    for c in _contour_info(glyph, coords):
        c_cy = float(c["cy"])
        c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
        area = float(c["area"])
        bottom_layer = (
            c_cy < y_min + glyph_h * 0.34
            and area > glyph_area * 0.015
            and c_w > glyph_w * 0.10
            and c_h > glyph_h * 0.04
        )
        if not bottom_layer:
            continue
        _scale_contour(
            coords,
            c,
            scale_x=KAI_BALANCE_ROOF_BOTTOM_X,
            scale_y=KAI_BALANCE_ROOF_BOTTOM_Y,
            shift_y=KAI_BALANCE_ROOF_BOTTOM_RAISE_EM * upm,
        )
        touched = True
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_kai_balance_stack_bottom(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    _x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    glyph_area = glyph_w * glyph_h
    touched = False

    for c in _contour_info(glyph, coords):
        c_cy = float(c["cy"])
        c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
        area = float(c["area"])
        if (
            c_cy >= y_min + glyph_h * 0.40
            or area <= glyph_area * 0.012
            or c_w <= glyph_w * 0.08
            or c_h <= glyph_h * 0.035
        ):
            continue
        _scale_contour(
            coords,
            c,
            scale_x=KAI_BALANCE_STACK_BOTTOM_X,
            scale_y=KAI_BALANCE_STACK_BOTTOM_Y,
            shift_y=KAI_BALANCE_STACK_BOTTOM_RAISE_EM * upm,
        )
        touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_kai_balance_wide_diag(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None:
        return False
    _x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    touched = False
    bottom_raise = KAI_BALANCE_WIDE_BOTTOM_RAISE_EM * upm

    for i in range(len(coords)):
        x, y = coords[i]
        yn = (y - y_min) / glyph_h
        edge_t = min(1.0, abs(x - cx) / max(1.0, glyph_w * 0.50))
        new_x = float(x)
        new_y = float(y)

        if edge_t > 0.42:
            contain_t = (edge_t - 0.42) / 0.58
            band_t = max(0.0, 1.0 - abs(yn - 0.52) / 0.48)
            factor = 1.0 - KAI_BALANCE_WIDE_EDGE_CONTAIN * contain_t * band_t
            new_x = cx + (new_x - cx) * factor

        if yn < 0.34 and edge_t > 0.22:
            bottom_t = (0.34 - yn) / 0.34
            factor = 1.0 - KAI_BALANCE_WIDE_BOTTOM_CONTAIN * bottom_t * edge_t
            new_x = cx + (new_x - cx) * factor
            new_y += bottom_raise * bottom_t

        nx = int(round(new_x))
        ny = int(round(new_y))
        if nx != x or ny != y:
            coords[i] = (nx, ny)
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def refine_kai_component_balance(font: TTFont) -> None:
    """Apply targeted typographic-kai component hierarchy to problem groups."""
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    stats = {
        "water": 0,
        "counter": 0,
        "book": 0,
        "speech": 0,
        "side": 0,
        "roof": 0,
        "stack": 0,
        "wide": 0,
    }

    for char in KAI_BALANCE_WATER_CHARS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours > 0 and _refine_kai_balance_water(glyph, glyf, upm):
            stats["water"] += 1

    for char in KAI_BALANCE_DENSE_COUNTER_CHARS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours > 0 and _refine_kai_balance_dense_counters(char, glyph, glyf, upm):
            stats["counter"] += 1

    gname = cmap.get(ord("书"))
    if gname and gname in glyf:
        glyph = glyf[gname]
        if glyph.numberOfContours > 0 and _refine_kai_balance_book_dot(glyph, glyf, upm):
            stats["book"] += 1

    for char in KAI_BALANCE_SPEECH_CHARS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours > 0 and _refine_kai_balance_speech(char, glyph, glyf, upm):
            stats["speech"] += 1

    for char in KAI_BALANCE_SIDE_SPLIT_CHARS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours > 0 and _refine_kai_balance_side_split(glyph, glyf, upm):
            stats["side"] += 1

    for char in KAI_BALANCE_ROOF_CHARS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours > 0 and _refine_kai_balance_roof_bottom(glyph, glyf, upm):
            stats["roof"] += 1

    for char in KAI_BALANCE_STACK_CHARS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours > 0 and _refine_kai_balance_stack_bottom(glyph, glyf, upm):
            stats["stack"] += 1

    for char in KAI_BALANCE_WIDE_DIAG_CHARS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours > 0 and _refine_kai_balance_wide_diag(glyph, glyf, upm):
            stats["wide"] += 1

    total = sum(stats.values())
    if total:
        detail = " ".join(f"{k}={v}" for k, v in stats.items() if v)
        print(f"[luo] refined kai component balance ({detail})")


def refine_site_body_readability(font: TTFont) -> None:
    """Restore body-size presence for homepage running-text glyphs.

    The char set is rebuilt at every call from the configured site / prose
    files (`SITE_BODY_READABILITY_FILES`) plus the visible-defect anchor list
    so the guard tracks site copy edits automatically.
    """
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    dot_min = SITE_BODY_DOT_MIN_EM * upm
    h_min = SITE_BODY_H_MIN_EM * upm
    touched: list[str] = []
    dot_count = 0
    h_count = 0
    secondary_count = 0

    body_chars = _collect_site_body_readability_chars()
    print(f"[luo] body readability guard: {len(body_chars)} glyphs")
    for char in body_chars:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        coords = glyph.coordinates
        box = _glyph_box(coords)
        if box is None:
            continue
        x_min, _x_max, _y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
        glyph_area = glyph_w * glyph_h
        contours = _contour_info(glyph, coords)
        if not contours:
            continue
        max_area = max(float(c["area"]) for c in contours)
        glyph_touched = False

        for c in contours:
            signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
            if signed > 0:
                continue
            c_xmin = float(c["xmin"])
            c_xmax = float(c["xmax"])
            c_w = max(1.0, c_xmax - c_xmin)
            c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
            area = float(c["area"])
            aspect = c_w / c_h
            n_pts = int(c["n"])
            ccx = float(c["cx"])

            dot_like = (
                n_pts <= DOT_MAX_POINTS
                and c_w < glyph_w * 0.34
                and c_h < glyph_h * 0.34
                and area < glyph_area * 0.070
            )
            horizontal_layer = (
                not dot_like
                and aspect > 2.0
                and c_h < glyph_h * 0.24
                and c_w > glyph_w * 0.08
            )
            side_secondary = (
                not dot_like
                and not horizontal_layer
                and glyph.numberOfContours >= 3
                and ccx < cx
                and c_xmax < x_min + glyph_w * 0.54
                and area < max_area * 0.34
                and c_w < glyph_w * 0.50
            )

            if dot_like:
                sx = _presence_floor_scale(c_w, dot_min, SITE_BODY_DOT_MAX_SCALE)
                sy = _presence_floor_scale(c_h, dot_min, SITE_BODY_DOT_MAX_SCALE)
                if sx > 1.0 or sy > 1.0:
                    _scale_contour(coords, c, scale_x=sx, scale_y=sy)
                    dot_count += 1
                    glyph_touched = True
                continue

            if horizontal_layer:
                sy = _presence_floor_scale(c_h, h_min, SITE_BODY_H_MAX_SCALE)
                if sy > 1.0:
                    _scale_contour(coords, c, scale_y=sy)
                    h_count += 1
                    glyph_touched = True
                continue

            if side_secondary:
                _scale_contour(
                    coords,
                    c,
                    scale_x=SITE_BODY_SECONDARY_SCALE,
                    scale_y=SITE_BODY_SECONDARY_SCALE,
                )
                secondary_count += 1
                glyph_touched = True

        if glyph_touched:
            glyph.recalcBounds(glyf)
            touched.append(char)

    if touched:
        print(
            f"[luo] guarded site body readability: {''.join(touched)} "
            f"(dots={dot_count}, h={h_count}, secondary={secondary_count}, "
            f"dot_min={SITE_BODY_DOT_MIN_EM}em, h_min={SITE_BODY_H_MIN_EM}em)"
        )


def _refine_problem_liang(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    contours = _contour_info(glyph, coords)
    touched = False

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed <= 0:
            continue
        ccy = float(c["cy"])
        y_t = (ccy - y_min) / max(1.0, glyph_h)
        if y_t > 0.62:
            _scale_contour(coords, c, 1.050, 1.035, 0.004 * upm, -0.003 * upm)
        else:
            _scale_contour(coords, c, 1.065, 1.040, -0.004 * upm, 0.002 * upm)
        touched = True

    for c in contours:
        if float(c["area"]) < glyph_w * glyph_h * 0.40:
            continue
        for i in range(int(c["start"]), int(c["end"]) + 1):
            x, y = coords[i]
            yn = (y - y_min) / max(1.0, glyph_h)
            if yn >= 0.24 or x <= cx:
                continue
            t = (0.24 - yn) / 0.24 * min(1.0, (x - cx) / max(1.0, glyph_w * 0.38))
            new_x = cx + (x - cx) * (1.0 - 0.020 * t)
            new_y = y + 0.008 * upm * t
            coords[i] = (int(round(new_x)), int(round(new_y)))
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_moon(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    _x_min, _x_max, y_min, _y_max, _glyph_w, glyph_h, _cx, _cy = box
    touched = False

    for c in _contour_info(glyph, coords):
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed <= 0:
            continue
        y_t = (float(c["cy"]) - y_min) / max(1.0, glyph_h)
        shift_y = 0.002 * upm if y_t > 0.58 else -0.002 * upm
        _scale_contour(coords, c, 1.020, 1.010, -0.004 * upm, shift_y)
        touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_huo(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    contours = _contour_info(glyph, coords)
    max_area = max(float(c["area"]) for c in contours)
    touched = False

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
        ccx = float(c["cx"])
        ccy = float(c["cy"])
        aspect = c_w / c_h
        if signed > 0:
            _scale_contour(coords, c, 1.100, 1.080)
            touched = True
            continue
        if float(c["area"]) > max_area * 0.25:
            continue
        if ccx < cx and ccy < y_min + glyph_h * 0.62:
            sy = 0.955 if aspect > 2.0 else 0.965
            _scale_contour(coords, c, 0.975, sy, 0.0, 0.005 * upm)
            touched = True
        elif ccx > cx and ccy > y_min + glyph_h * 0.72:
            _scale_contour(coords, c, 0.960, 0.960, 0.0, -0.002 * upm)
            touched = True

    for c in contours:
        if float(c["area"]) < max_area * 0.80:
            continue
        for i in range(int(c["start"]), int(c["end"]) + 1):
            x, y = coords[i]
            xn = (x - x_min) / max(1.0, glyph_w)
            yn = (y - y_min) / max(1.0, glyph_h)
            if xn <= 0.58 or yn >= 0.25:
                continue
            t = (xn - 0.58) / 0.42 * (0.25 - yn) / 0.25
            new_x = cx + (x - cx) * (1.0 - 0.035 * t)
            new_y = y + 0.007 * upm * t
            coords[i] = (int(round(new_x)), int(round(new_y)))
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_ze(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    _x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    contours = _contour_info(glyph, coords)
    touched = False

    for c in contours:
        c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
        ccx = float(c["cx"])
        ccy = float(c["cy"])
        aspect = c_w / c_h
        if ccx > cx + glyph_w * 0.10 and aspect < 0.42:
            _scale_contour(coords, c, 0.920, 0.995, 0.004 * upm, 0.0)
            touched = True
            continue
        if ccx < cx and ccy < y_min + glyph_h * 0.35:
            _scale_contour(coords, c, 0.982, 0.960, 0.0, 0.006 * upm)
            touched = True
        elif ccx < cx and c_h > glyph_h * 0.45:
            _scale_contour(coords, c, 0.988, 0.990)
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_mo(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    contours = _contour_info(glyph, coords)
    max_area = max(float(c["area"]) for c in contours)
    touched = False

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed <= 0:
            continue
        c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
        aspect = c_w / c_h
        ccy = float(c["cy"])
        area = float(c["area"])
        if area > max_area * 0.050:
            sx, sy = 1.075, 1.055
        elif aspect > 2.0:
            sx, sy = 1.120, 1.080
        else:
            sx, sy = 1.080, 1.060
        y_t = (ccy - y_min) / max(1.0, glyph_h)
        shift_y = 0.004 * upm if y_t > 0.54 else -0.004 * upm if y_t < 0.30 else 0.0
        _scale_contour(coords, c, sx, sy, 0.0, shift_y)
        touched = True

    for c in contours:
        if float(c["area"]) < max_area * 0.80:
            continue
        for i in range(int(c["start"]), int(c["end"]) + 1):
            x, y = coords[i]
            xn = (x - x_min) / max(1.0, glyph_w)
            yn = (y - y_min) / max(1.0, glyph_h)
            new_x = float(x)
            new_y = float(y)
            if xn < 0.25 and yn < 0.58:
                t = (0.25 - xn) / 0.25 * (0.58 - yn) / 0.58
                new_x += 0.022 * upm * t
                new_y += 0.012 * upm * t
            if xn > 0.66 and yn < 0.24:
                t = (xn - 0.66) / 0.34 * (0.24 - yn) / 0.24
                new_x = cx + (new_x - cx) * (1.0 - 0.050 * t)
                new_y += 0.010 * upm * t
            if yn > 0.68 and 0.30 < xn < 0.88:
                t = (yn - 0.68) / 0.32
                new_x = cx + (new_x - cx) * (1.0 - 0.010 * t)
            if int(round(new_x)) != x or int(round(new_y)) != y:
                coords[i] = (int(round(new_x)), int(round(new_y)))
                touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def refine_visible_problem_glyphs(font: TTFont) -> None:
    """Final correction pass for the glyphs surfaced in the visual audit."""
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    refiners = {
        "两": _refine_problem_liang,
        "月": _refine_problem_moon,
        "或": _refine_problem_huo,
        "则": _refine_problem_ze,
        "魔": _refine_problem_mo,
    }
    touched: list[str] = []
    for char in VISIBLE_PROBLEM_GLYPHS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        if refiners[char](glyph, glyf, upm):
            touched.append(char)
    if touched:
        print(f"[luo] refined visible problem glyphs: {''.join(touched)}")


def _identity_core_glyph_bounds(coords) -> tuple[float, float, float, float, float, float]:
    """Backwards-compatible wrapper around `_glyph_box` without cx/cy."""
    box = _glyph_box(coords)
    if box is None:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    x_min, x_max, y_min, y_max, x_range, y_range, _cx, _cy = box
    return x_min, x_max, y_min, y_max, x_range, y_range


def _identity_core_is_dot_like(c, glyph_w: float, glyph_h: float, glyph_area: float) -> bool:
    if glyph_area <= 0:
        return False
    c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
    c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
    return (
        int(c["n"]) <= DOT_MAX_POINTS
        and c_w < glyph_w * 0.32
        and c_h < glyph_h * 0.32
        and c_w * c_h < glyph_area * 0.060
    )


def _identity_core_open_counters(glyph, glyf) -> int:
    if glyph.numberOfContours < 2:
        return 0
    coords = glyph.coordinates
    if len(coords) == 0:
        return 0
    x_min, x_max, y_min, y_max, glyph_w, glyph_h = _identity_core_glyph_bounds(coords)
    if glyph_w <= 0 or glyph_h <= 0:
        return 0
    contours = _contour_info(glyph, coords)
    if not contours:
        return 0
    max_area = max(float(c["area"]) for c in contours)
    if max_area <= 0:
        return 0

    touched = 0
    for c in contours:
        c_xmin = float(c["xmin"])
        c_xmax = float(c["xmax"])
        c_ymin = float(c["ymin"])
        c_ymax = float(c["ymax"])
        c_w = max(1.0, c_xmax - c_xmin)
        c_h = max(1.0, c_ymax - c_ymin)
        inset = (
            c_xmin > x_min + glyph_w * 0.055
            and c_xmax < x_max - glyph_w * 0.055
            and c_ymin > y_min + glyph_h * 0.045
            and c_ymax < y_max - glyph_h * 0.045
            and c_w > glyph_w * 0.10
            and c_h > glyph_h * 0.05
            and float(c["area"]) < max_area * 0.72
        )
        if not inset:
            continue
        _scale_contour(
            coords,
            c,
            IDENTITY_CORE_COUNTER_EXPAND_X,
            IDENTITY_CORE_COUNTER_EXPAND_Y,
        )
        touched += 1
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _identity_core_lighten_secondary(glyph, glyf) -> int:
    coords = glyph.coordinates
    if len(coords) == 0 or glyph.numberOfContours < 2:
        return 0
    x_min, x_max, y_min, y_max, glyph_w, glyph_h = _identity_core_glyph_bounds(coords)
    if glyph_w <= 0 or glyph_h <= 0:
        return 0
    contours = _contour_info(glyph, coords)
    if not contours:
        return 0
    max_area = max(float(c["area"]) for c in contours)
    if max_area <= 0:
        return 0

    touched = 0
    glyph_area = glyph_w * glyph_h
    for c in contours:
        c_xmin = float(c["xmin"])
        c_xmax = float(c["xmax"])
        c_ymin = float(c["ymin"])
        c_ymax = float(c["ymax"])
        c_w = max(1.0, c_xmax - c_xmin)
        c_h = max(1.0, c_ymax - c_ymin)
        aspect = c_w / c_h
        area = float(c["area"])
        if _identity_core_is_dot_like(c, glyph_w, glyph_h, glyph_area):
            continue
        inset_counter = (
            c_xmin > x_min + glyph_w * 0.055
            and c_xmax < x_max - glyph_w * 0.055
            and c_ymin > y_min + glyph_h * 0.045
            and c_ymax < y_max - glyph_h * 0.045
            and area < max_area * 0.72
        )
        if inset_counter:
            continue
        horizontal_layer = aspect > 1.85 and c_h < glyph_h * 0.22
        small_secondary = (
            area < max_area * 0.24
            and c_w > glyph_w * 0.10
            and c_h > glyph_h * 0.045
        )
        if not horizontal_layer and not small_secondary:
            continue
        if horizontal_layer:
            _scale_contour(coords, c, 0.982, IDENTITY_CORE_HORIZ_Y_SCALE)
        else:
            _scale_contour(coords, c, IDENTITY_CORE_SECONDARY_SCALE, IDENTITY_CORE_SECONDARY_SCALE)
        touched += 1
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _identity_core_layer_gap(glyph, glyf, upm: int) -> int:
    if glyph.numberOfContours < 2:
        return 0
    coords = glyph.coordinates
    if len(coords) == 0:
        return 0
    x_min, x_max, y_min, y_max, glyph_w, glyph_h = _identity_core_glyph_bounds(coords)
    if glyph_w <= 0 or glyph_h <= 0:
        return 0
    cy = (y_min + y_max) / 2.0
    gap = IDENTITY_CORE_LAYER_GAP_EM * upm
    touched = 0
    for c in _contour_info(glyph, coords):
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
        if c_h > glyph_h * 0.68:
            continue
        shift = 0.0
        if float(c["cy"]) > cy + glyph_h * 0.14:
            shift = gap
        elif float(c["cy"]) < cy - glyph_h * 0.18:
            shift = -gap * 0.70
        if shift == 0.0:
            continue
        _scale_contour(coords, c, 1.0, 1.0, 0.0, shift)
        touched += 1
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _identity_core_frame_posture(glyph, glyf) -> int:
    coords = glyph.coordinates
    if len(coords) == 0:
        return 0
    x_min, x_max, y_min, y_max, glyph_w, glyph_h = _identity_core_glyph_bounds(coords)
    if glyph_w <= 0 or glyph_h <= 0:
        return 0
    cx = (x_min + x_max) / 2.0
    touched = 0
    for c in _contour_info(glyph, coords):
        c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
        aspect = c_w / c_h
        if aspect < 0.62 and c_h > glyph_h * 0.34:
            _scale_contour(coords, c, IDENTITY_CORE_FRAME_STEM_X, 1.0)
            touched += 1
            continue
        # Monolithic frame contours get a tiny waist containment so the outer
        # frame reads more upright without making the character narrow.
        if c_w > glyph_w * 0.70 and c_h > glyph_h * 0.70:
            for i in range(int(c["start"]), int(c["end"]) + 1):
                x, y = coords[i]
                y_t = max(0.0, 1.0 - abs(y - (y_min + y_max) / 2.0) / max(1.0, glyph_h * 0.50))
                edge_t = min(1.0, abs(x - cx) / max(1.0, glyph_w * 0.50))
                contain = 1.0 - (1.0 - IDENTITY_CORE_FRAME_STEM_X) * y_t * edge_t
                new_x = cx + (x - cx) * contain
                coords[i] = (int(round(new_x)), y)
            touched += 1
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _identity_core_diag_tension(glyph, glyf, upm: int) -> int:
    coords = glyph.coordinates
    if len(coords) == 0:
        return 0
    x_min, x_max, y_min, y_max, glyph_w, glyph_h = _identity_core_glyph_bounds(coords)
    if glyph_w <= 0 or glyph_h <= 0:
        return 0
    cx = (x_min + x_max) / 2.0
    cy = (y_min + y_max) / 2.0
    edge_shift = IDENTITY_CORE_DIAG_EDGE_EM * upm
    tail_pull = IDENTITY_CORE_DIAG_TAIL_CONTAIN
    touched = 0
    for i in range(len(coords)):
        x, y = coords[i]
        yn = (y - y_min) / glyph_h
        edge_t = min(1.0, abs(x - cx) / max(1.0, glyph_w * 0.50))
        vertical_t = min(1.0, abs(y - cy) / max(1.0, glyph_h * 0.50))
        new_x = float(x)
        new_y = float(y)
        if yn > 0.60:
            contain = 1.0 - (1.0 - IDENTITY_CORE_DIAG_TOP_CONTAIN) * (yn - 0.60) / 0.40
            new_x = cx + (new_x - cx) * contain
        if yn < 0.42 and edge_t > 0.18:
            t = (0.42 - yn) / 0.42 * edge_t
            new_x += math.copysign(edge_shift * t, x - cx if x != cx else 1)
            new_y -= edge_shift * 0.18 * t
        if yn < 0.16 and edge_t > 0.35:
            t = (0.16 - yn) / 0.16 * edge_t
            new_x = cx + (new_x - cx) * (1.0 - tail_pull * t)
        if int(round(new_x)) != x or int(round(new_y)) != y:
            coords[i] = (int(round(new_x)), int(round(new_y)))
            touched += 1
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_identity_core_v2_glyph(char: str, glyph, glyf, upm: int) -> dict[str, int]:
    """Run the core_v2 refinements, but skip whatever the upstream FRAME /
    FRAME_RISK / LAYER_RISK / DIAG passes already did for this glyph.

    Without this guard, frame chars in `日目月` get three counter expansions
    stacked (FRAME + FRAME_RISK + CORE) and the outer stems read as too thin;
    `兰集` get two layer-counter expansions; `文` gets two diagonal tensions.
    Each unique-purpose core sub-pass (frame_posture stem, layer_gap, the
    diag-specific top/tail containment) still runs.
    """
    stats = {"counter": 0, "secondary": 0, "layer": 0, "frame": 0, "diag": 0}
    if char in IDENTITY_CORE_FRAME_CHARS:
        stats["frame"] += _identity_core_frame_posture(glyph, glyf)
        # FRAME / FRAME_RISK already opened this glyph's counter via the
        # IDENTITY_FRAME / IDENTITY_RISK_FRAME counter-expand parameters.
        if char not in IDENTITY_FRAME_CHARS and char not in IDENTITY_FRAME_RISK_CHARS:
            stats["counter"] += _identity_core_open_counters(glyph, glyf)
    if char in IDENTITY_CORE_LAYER_CHARS:
        stats["layer"] += _identity_core_layer_gap(glyph, glyf, upm)
        if char not in IDENTITY_LAYER_RISK_CHARS:
            stats["counter"] += _identity_core_open_counters(glyph, glyf)
        if char not in IDENTITY_LAYER_RISK_CHARS:
            stats["secondary"] += _identity_core_lighten_secondary(glyph, glyf)
    if char in IDENTITY_CORE_DIAG_CHARS and char not in IDENTITY_DIAG_CHARS:
        stats["diag"] += _identity_core_diag_tension(glyph, glyf, upm)
    return stats


def _refine_identity_all_glyph(glyph, glyf, upm: int) -> None:
    """Apply subtle Luo-specific structure language to every covered CJK glyph.

    This is intentionally not a whole-glyph move. It changes internal rhythm:
    upper strokes sit a little higher and narrower, lower strokes settle and
    open, middle layers breathe, counters open, and small components separate
    from the main body. The goal is to make covered glyphs stop inheriting the
    source outline posture while keeping the quiet print texture.
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None:
        return
    x_min, x_max, y_min, y_max, x_range, y_range, cx, cy = box

    if glyph.numberOfContours <= COMPLEXITY_SIMPLE_MAX:
        face_x = IDENTITY_SIMPLE_FACE_X
        face_y = IDENTITY_SIMPLE_FACE_Y
    elif glyph.numberOfContours >= COMPLEXITY_COMPLEX_MIN:
        face_x = IDENTITY_COMPLEX_FACE_X
        face_y = IDENTITY_COMPLEX_FACE_Y
    else:
        face_x = IDENTITY_REGULAR_FACE_X
        face_y = IDENTITY_REGULAR_FACE_Y

    if face_x != 1.0 or face_y != 1.0:
        for i in range(len(coords)):
            x, y = coords[i]
            new_x = cx + (x - cx) * face_x
            new_y = cy + (y - cy) * face_y
            coords[i] = (int(round(new_x)), int(round(new_y)))
        rebox = _glyph_box(coords)
        if rebox is None:
            return
        x_min, x_max, y_min, y_max, x_range, y_range, cx, cy = rebox

    top_start = y_min + y_range * 0.58
    bottom_end = y_min + y_range * 0.24
    top_raise = IDENTITY_ALL_TOP_RAISE_EM * upm
    bottom_settle = IDENTITY_ALL_BOTTOM_SETTLE_EM * upm
    edge_shift = IDENTITY_ALL_EDGE_TENSION_EM * upm

    for i in range(len(coords)):
        x, y = coords[i]
        new_x = float(x)
        new_y = float(y)
        yn = (y - y_min) / y_range
        x_edge = min(1.0, abs(x - cx) / max(1.0, x_range * 0.5))

        # A slight middle containment gives long horizontal stacks a Luo waist
        # without narrowing the whole glyph advance.
        waist = max(0.0, 1.0 - abs(yn - 0.50) / 0.28)
        if waist > 0:
            factor = 1.0 - (1.0 - IDENTITY_ALL_WAIST_CONTAIN) * waist
            new_x = cx + (new_x - cx) * factor

        if y > top_start and y_max > top_start:
            t = (y - top_start) / (y_max - top_start)
            factor = 1.0 - (1.0 - IDENTITY_ALL_TOP_CONTAIN) * t
            new_x = cx + (new_x - cx) * factor
            new_y += top_raise * t
        elif y < bottom_end and bottom_end > y_min:
            t = (bottom_end - y) / (bottom_end - y_min)
            factor = 1.0 + (IDENTITY_ALL_BOTTOM_EXPAND - 1.0) * t
            new_x = cx + (new_x - cx) * factor
            new_y -= bottom_settle * t

        # Edge tension is symmetric and tiny; it changes terminal direction
        # distribution without making the glyph slant.
        tension = math.sin((yn - 0.5) * math.pi) * x_edge
        if tension:
            new_x += math.copysign(abs(tension) * edge_shift, x - cx if x != cx else 1)

        coords[i] = (int(round(new_x)), int(round(new_y)))

    contours = _contour_info(glyph, coords)
    if contours:
        max_area = max(float(c["area"]) for c in contours)
        glyph_w = x_range
        glyph_h = y_range
        component_dx = IDENTITY_ALL_COMPONENT_SHIFT_EM * upm
        component_dy = IDENTITY_ALL_COMPONENT_Y_EM * upm
        side_component_dx = IDENTITY_ALL_SIDE_COMPONENT_X_EM * upm
        side_component_dy = IDENTITY_ALL_SIDE_COMPONENT_Y_EM * upm
        simple_glyph = glyph.numberOfContours <= COMPLEXITY_SIMPLE_MAX
        h_layer_x = IDENTITY_SIMPLE_H_LAYER_X if simple_glyph else IDENTITY_ALL_H_LAYER_X
        h_angle = math.radians(IDENTITY_ALL_H_LAYER_ROTATE_DEG)
        cos_h = math.cos(h_angle)
        sin_h = math.sin(h_angle)
        for c in contours:
            area = float(c["area"])
            if area <= 0:
                continue
            c_xmin = float(c["xmin"])
            c_xmax = float(c["xmax"])
            c_ymin = float(c["ymin"])
            c_ymax = float(c["ymax"])
            ccx = float(c["cx"])
            ccy = float(c["cy"])
            c_w = max(1.0, c_xmax - c_xmin)
            c_h = max(1.0, c_ymax - c_ymin)
            aspect = c_w / c_h
            n_pts = int(c["n"])
            dot_like = (
                n_pts <= DOT_MAX_POINTS
                and c_w < glyph_w * 0.32
                and c_h < glyph_h * 0.32
                and area < glyph_w * glyph_h * 0.055
            )
            horizontal_layer = (
                not dot_like
                and aspect > 2.0
                and c_h < glyph_h * 0.24
            )
            vertical_stem = (
                not dot_like
                and aspect < 0.55
                and c_w < glyph_w * 0.24
            )
            diagonal_piece = (
                not dot_like
                and not horizontal_layer
                and not vertical_stem
                and 0.55 <= aspect <= 1.90
                and area < max_area * 0.50
            )
            side_strength = min(1.0, abs(ccx - cx) / max(1.0, glyph_w * 0.30))
            side_component = (
                glyph.numberOfContours >= 2
                and not dot_like
                and side_strength > 0.22
                and c_w < glyph_w * 0.72
                and area < max_area * 1.02
            )

            inset = (
                glyph.numberOfContours >= 2
                and c_xmin > x_min + glyph_w * 0.08
                and c_xmax < x_max - glyph_w * 0.08
                and c_ymin > y_min + glyph_h * 0.08
                and c_ymax < y_max - glyph_h * 0.08
                and area < max_area * 0.70
            )
            small_component = (
                glyph.numberOfContours >= 3
                and area < max_area * 0.22
                and area > max_area * 0.010
            )

            for i in range(int(c["start"]), int(c["end"]) + 1):
                x, y = coords[i]
                new_x = float(x)
                new_y = float(y)
                local_x = new_x - ccx
                local_y = new_y - ccy
                if horizontal_layer:
                    local_x *= h_layer_x
                    rot_x = local_x * cos_h - local_y * sin_h
                    rot_y = local_x * sin_h + local_y * cos_h
                    new_x = ccx + rot_x
                    new_y = ccy + rot_y
                elif vertical_stem:
                    new_x = ccx + local_x * IDENTITY_ALL_V_STEM_X
                    new_y = ccy + local_y * IDENTITY_ALL_V_STEM_Y
                elif diagonal_piece:
                    new_x = ccx + local_x * IDENTITY_ALL_DIAG_EXPAND
                    new_y = ccy + local_y * IDENTITY_ALL_DIAG_EXPAND
                if inset:
                    new_x = ccx + (new_x - ccx) * IDENTITY_ALL_COUNTER_EXPAND_X
                    new_y = ccy + (new_y - ccy) * IDENTITY_ALL_COUNTER_EXPAND_Y
                if small_component:
                    new_x = ccx + (new_x - ccx) * IDENTITY_ALL_SECONDARY_SCALE
                    new_y = ccy + (new_y - ccy) * IDENTITY_ALL_SECONDARY_SCALE
                    side = 1.0 if ccx >= cx else -1.0
                    vertical = 1.0 if ccy >= cy else -1.0
                    new_x += component_dx * side
                    new_y += component_dy * vertical
                if side_component:
                    side = 1.0 if ccx >= cx else -1.0
                    vertical = 1.0 if ccy >= cy else -1.0
                    new_x += side_component_dx * side * side_strength
                    new_y += side_component_dy * vertical * side_strength
                coords[i] = (int(round(new_x)), int(round(new_y)))

    glyph.recalcBounds(glyf)


def _refine_identity_source_separation(glyph, glyf, upm: int) -> None:
    coords = glyph.coordinates
    if len(coords) == 0:
        return

    dx = int(round(IDENTITY_SOURCE_SHIFT_X_EM * upm))
    dy = int(round(IDENTITY_SOURCE_SHIFT_Y_EM * upm))
    if dx == 0 and dy == 0:
        return

    for i in range(len(coords)):
        x, y = coords[i]
        coords[i] = (x + dx, y + dy)

    glyph.recalcBounds(glyf)


def _identity_target_chars(requested_chars: str = "") -> str:
    chunks = [IDENTITY_HIGH_RISK_CHARS, PRIORITY_CHARS]
    chunks.append(chars_from_files(STARTER_FILES))
    chunks.append(requested_chars)
    return "".join(dict.fromkeys("".join(chunks)))


def refine_identity_chars(font: TTFont, requested_chars: str = "") -> None:
    """Pull high-overlap starter anchors away from the source outline."""
    glyf = font["glyf"]
    cmap = font.getBestCmap() or {}
    upm = font["head"].unitsPerEm
    touched = []
    core_touched = []
    core_stats: dict[str, int] = {}
    target_chars = _identity_target_chars(requested_chars)

    for char in target_chars:
        cp = ord(char)
        if not (0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF):
            continue
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue

        _refine_identity_all_glyph(glyph, glyf, upm)
        if char in IDENTITY_POSTURE_CHARS:
            _refine_identity_posture(glyph, glyf, upm)
        # FRAME and FRAME_RISK both open inset counters; they were meant to
        # be alternative treatments, not stacked. 日/目/月 sit in both lists,
        # so without this guard the inner counter gets expanded ~12% (1.05
        # × 1.065) and the outer frame stems read as too thin in body text.
        # FRAME_RISK is the dedicated stronger version for high-overlap
        # chars, so let it own those glyphs.
        if char in IDENTITY_FRAME_RISK_CHARS:
            _refine_identity_frame_risk(glyph, glyf)
        elif char in IDENTITY_FRAME_CHARS:
            _refine_identity_frame(glyph, glyf, upm)
        if char in IDENTITY_MULTI_HORIZ_CHARS:
            _refine_identity_multi_horiz(glyph, glyf)
        if char in IDENTITY_LAYER_RISK_CHARS:
            _refine_identity_layer_risk(glyph, glyf, upm)
        if char in IDENTITY_DIAG_CHARS:
            _refine_identity_diagonal(glyph, glyf, upm)
        _refine_identity_source_separation(glyph, glyf, upm)
        if char in IDENTITY_CORE_V2_CHARS:
            stats = _refine_identity_core_v2_glyph(char, glyph, glyf, upm)
            if any(stats.values()):
                core_touched.append(char)
                for key, value in stats.items():
                    core_stats[key] = core_stats.get(key, 0) + value
        touched.append(char)

    if touched:
        print(
            f"[luo] refined identity anchors: {len(touched)} glyphs "
            f"(top={IDENTITY_POSTURE_TOP_RAISE_EM}em, "
            f"bottom={IDENTITY_POSTURE_BOTTOM_SETTLE_EM}em, "
            f"frame_counter={IDENTITY_FRAME_COUNTER_EXPAND_X}×/"
            f"{IDENTITY_FRAME_COUNTER_EXPAND_Y}×, "
            f"multi_mid={IDENTITY_MULTI_MID_CONTAIN}, "
            f"risk_frame={IDENTITY_RISK_FRAME_COUNTER_EXPAND_X}×/"
            f"{IDENTITY_RISK_FRAME_COUNTER_EXPAND_Y}×, "
            f"risk_layer={IDENTITY_LAYER_COUNTER_EXPAND_X}×/"
            f"{IDENTITY_LAYER_COUNTER_EXPAND_Y}×, "
            f"all_top={IDENTITY_ALL_TOP_RAISE_EM}em, "
            f"all_waist={IDENTITY_ALL_WAIST_CONTAIN}, "
            f"face={IDENTITY_SIMPLE_FACE_X}×/{IDENTITY_REGULAR_FACE_X}×/"
            f"{IDENTITY_COMPLEX_FACE_X}×, "
            f"source_shift={IDENTITY_SOURCE_SHIFT_X_EM}em/"
            f"{IDENTITY_SOURCE_SHIFT_Y_EM}em)"
        )
    if core_touched:
        detail = " ".join(f"{key}={value}" for key, value in sorted(core_stats.items()) if value)
        print(
            f"[luo] refined identity core v2: {''.join(core_touched)} "
            f"({detail}, secondary={IDENTITY_CORE_SECONDARY_SCALE}, "
            f"horiz_y={IDENTITY_CORE_HORIZ_Y_SCALE})"
        )


# --- Pass A: Dot contour refinement ---

HEART_CHARS = (
    "心思意念想感悲惠慨悟您志必恩愁惊慎"
    "忠忽怠恨恐恭忙忆忍忘"
    # v0.4 audit additions: common 心字底 chars from GB2312 level-1 that the
    # generic dot pass would otherwise fragment. The heart pass treats the 心
    # bottom as one unit (hook + 3 sorted dots), giving consistent rhythm
    # across this group. Verify visually in proof/gb2312.html before relying
    # on these for level-1 expansion.
    "慈慧慰愈怒怎急慕愿恋"
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
    # v0.4.1: explicit web-body anchors that need the curved-hook protection
    # so 弯钩/竖弯钩 keep a continuous tail at body sizes.
    "笔览无东亦起"
)

TURN_FINAL_CHARS = "".join(dict.fromkeys(
    "落纸风骨短版排印集章源雅舒服规则"
    "国回图园日目用月田间问阅品亭曾会"
    "章言书骨兰量重墨春青善美黄宇宙寒暑律吕"
))

TURN_FINAL_FRAME_CHARS = "国回图园日目用月田间问阅品"


_CMAP_CACHE_ATTR = "_luo_cmap_cache"
_RCMAP_CACHE_ATTR = "_luo_rcmap_cache"


def _build_cmap(font: TTFont) -> dict[int, str]:
    """Memoised codepoint -> glyph-name map for one font instance.

    Cache is invalidated by `clear_cmap_cache(font)` after passes that touch
    the cmap table (e.g. subsetting). All shaping passes leave it intact.
    """
    cached = getattr(font, _CMAP_CACHE_ATTR, None)
    if cached is not None:
        return cached
    cmap: dict[int, str] = {}
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                cmap.update(table.cmap)
    setattr(font, _CMAP_CACHE_ATTR, cmap)
    return cmap


def clear_cmap_cache(font: TTFont) -> None:
    if hasattr(font, _CMAP_CACHE_ATTR):
        delattr(font, _CMAP_CACHE_ATTR)
    if hasattr(font, _RCMAP_CACHE_ATTR):
        delattr(font, _RCMAP_CACHE_ATTR)


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
            axis = _dot_long_axis(c_xs, c_ys)
            if axis is None:
                start = end + 1
                continue
            long_ax, long_ay = axis

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
            pt_xs = [p[0] for p in pts]
            pt_ys = [p[1] for p in pts]
            cx = sum(pt_xs) / n_pts
            cy = sum(pt_ys) / n_pts

            axis = _dot_long_axis(pt_xs, pt_ys)
            if axis is None:
                start = end + 1
                continue
            long_ax, long_ay = axis

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
                    # 弯钩/竖弯钩 keep their off-curve handle on the perpendicular
                    # so the tail still reads as a curve. Only the tip on-curve
                    # gets the perpendicular pull, and at a softer factor.
                    curved_hook = angle >= HOOK_FINAL_CURVED_ANGLE
                    if curved_hook:
                        sharpen = HOOK_FINAL_TIP_SHARPEN_CURVED
                        sharpen_targets = (i_next,)
                    else:
                        sharpen = HOOK_FINAL_TIP_SHARPEN
                        sharpen_targets = (i_next, i_next2)
                    for tip_idx in sharpen_targets:
                        pt = new_coords[tip_idx]
                        proj = (pt[0] - p1[0]) * perp_x + (pt[1] - p1[1]) * perp_y
                        new_coords[tip_idx] = (
                            int(round(pt[0] - sharpen * proj * perp_x)),
                            int(round(pt[1] - sharpen * proj * perp_y)),
                        )
                    tip = new_coords[i_next2]
                    axial = (tip[0] - p1[0]) * axis_ux + (tip[1] - p1[1]) * axis_uy
                    tail_factor = HOOK_FINAL_TAIL_CONTAIN * (0.5 if curved_hook else 1.0)
                    if axial > 0 and tail_factor > 0:
                        new_coords[i_next2] = (
                            int(round(tip[0] - tail_factor * axial * axis_ux)),
                            int(round(tip[1] - tail_factor * axial * axis_uy)),
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
        f"curved_sharpen={HOOK_FINAL_TIP_SHARPEN_CURVED}, "
        f"curved_angle>={HOOK_FINAL_CURVED_ANGLE}°, "
        f"tail={HOOK_FINAL_TAIL_CONTAIN}, contained={tail_count})"
    )


def _opposite_outline_perp(
    coords,
    idx: int,
    contour_start: int,
    contour_end: int,
    axis: tuple[float, float],
    perp: tuple[float, float],
    skip_neighborhood: int = 5,
    along_band: float = 18.0,
    min_perp: float = 6.0,
):
    """Find the closest contour point on the opposite stroke edge.

    Walks every other point in the same contour, projects (k - idx) onto
    `axis` (along the stroke) and `perp` (perpendicular to it), and returns
    the candidate with the smallest Euclidean distance whose perpendicular
    projection magnitude is at least `min_perp` and whose along projection
    magnitude is at most `along_band`. Points within `skip_neighborhood`
    contour indices (modular) are skipped so we never match the same edge.

    Returns ``(signed_perp, opposite_idx)`` or ``None``. The signed perp is
    the projection onto `perp`, so ``abs(signed_perp)`` is the local outline
    width along that ray.
    """
    n = contour_end - contour_start + 1
    if n < skip_neighborhood * 2 + 1:
        return None
    px, py = coords[idx]
    ax, ay = axis
    pxn, pyn = perp
    best = None
    for k in range(contour_start, contour_end + 1):
        if k == idx:
            continue
        delta = abs(k - idx)
        if delta > n // 2:
            delta = n - delta
        if delta < skip_neighborhood:
            continue
        kx, ky = coords[k]
        vx = kx - px
        vy = ky - py
        along_proj = vx * ax + vy * ay
        if abs(along_proj) > along_band:
            continue
        perp_proj = vx * pxn + vy * pyn
        if abs(perp_proj) < min_perp:
            continue
        d = math.hypot(vx, vy)
        if best is None or d < best[0]:
            best = (d, k, perp_proj)
    if best is None:
        return None
    return (best[2], best[1])


def cap_hook_tail_widths(font: TTFont) -> None:
    """Geometric cap: the local outline width along each hook tail must not
    exceed the perpendicular stem width measured at the hook root.

    Whitelist-free. Uses the same hook detection as refine_hooks_final
    (60-130° angle, asymmetric stem/tail lengths) so it acts on the real
    hooks regardless of which characters were touched by the prior pass.
    For each detected hook:

      1. Estimate stem width at the knee p1 by ray-casting perpendicular to
         the in-direction d_in to the opposite stroke edge.
      2. Walk forward HOOK_TAIL_CAP_SAMPLES points along the contour. For
         each sample point, ray-cast perpendicular to the tail axis (d_out)
         to find the opposite outline.
      3. If the local outline width (the absolute perpendicular projection
         of that opposite point) exceeds stem_width × (1 + tolerance), push
         both the sample and the opposite point inward symmetrically by half
         the excess, capped at HOOK_TAIL_CAP_MAX_PUSH.

    Fixes 无-style 头轻脚重 where the 竖弯钩 tail visibly outweighs the
    main vertical stem after refine_hooks_final without re-shaping the hook
    geometry itself.
    """
    if not HOOK_TAIL_CAP_ENABLED:
        print("[luo] hook tail width cap: skipped (LUO_HOOK_TAIL_CAP_ENABLED=0)")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)

    cap_count = 0
    glyph_count = 0
    hook_seen = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if not cp or not (0x3400 <= cp <= 0x9FFF):
            continue
        char = chr(cp)
        if char in STRAIGHTEN_SKIP_CHARS:
            continue

        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue

        coords = list(glyph.coordinates)
        ends = glyph.endPtsOfContours
        glyph_touched = False

        start = 0
        for end in ends:
            n = end - start + 1
            if n < 12:
                start = end + 1
                continue

            for j in range(n):
                idx = start + j
                i_prev = start + (j - 1) % n
                i_next = start + (j + 1) % n

                p0x, p0y = coords[i_prev]
                p1x, p1y = coords[idx]
                p2x, p2y = coords[i_next]

                d_in_x = p1x - p0x
                d_in_y = p1y - p0y
                d_out_x = p2x - p1x
                d_out_y = p2y - p1y

                len_in = math.hypot(d_in_x, d_in_y)
                len_out = math.hypot(d_out_x, d_out_y)
                if len_in < 8 or len_out < 5:
                    continue
                if len_out <= 20 or len_out > 90:
                    continue
                if len_in < len_out * 1.5:
                    continue

                cos_a = (d_in_x * d_out_x + d_in_y * d_out_y) / (len_in * len_out)
                cos_a = max(-1.0, min(1.0, cos_a))
                angle = math.degrees(math.acos(cos_a))
                if angle < 60 or angle > 130:
                    continue

                hook_seen += 1

                stem_axis = (d_in_x / len_in, d_in_y / len_in)
                stem_perp = (-stem_axis[1], stem_axis[0])
                stem_op = _opposite_outline_perp(
                    coords, idx, start, end, stem_axis, stem_perp,
                    skip_neighborhood=4, along_band=18.0, min_perp=8.0,
                )
                if stem_op is None:
                    continue
                stem_width = abs(stem_op[0])
                if stem_width < 20 or stem_width > 280:
                    continue

                tail_axis = (d_out_x / len_out, d_out_y / len_out)
                tail_perp = (-tail_axis[1], tail_axis[0])

                cap_threshold = stem_width * (1.0 + HOOK_TAIL_CAP_TOLERANCE)

                hook_capped_here = False
                for k in range(1, HOOK_TAIL_CAP_SAMPLES + 1):
                    sample_j = (j + k) % n
                    sample_idx = start + sample_j

                    op = _opposite_outline_perp(
                        coords, sample_idx, start, end, tail_axis, tail_perp,
                        skip_neighborhood=4, along_band=14.0, min_perp=5.0,
                    )
                    if op is None:
                        continue
                    opp_perp, opp_idx = op
                    local_width = abs(opp_perp)
                    if local_width <= cap_threshold:
                        continue

                    excess = local_width - stem_width
                    push = min(excess / 2.0, HOOK_TAIL_CAP_MAX_PUSH)
                    if push < 1.0:
                        continue
                    if push * 2.0 >= local_width - 4.0:
                        # Don't fold the stroke onto itself.
                        continue

                    sign = 1.0 if opp_perp > 0 else -1.0
                    sx, sy = coords[sample_idx]
                    coords[sample_idx] = (
                        int(round(sx + sign * push * tail_perp[0])),
                        int(round(sy + sign * push * tail_perp[1])),
                    )
                    ox, oy = coords[opp_idx]
                    coords[opp_idx] = (
                        int(round(ox - sign * push * tail_perp[0])),
                        int(round(oy - sign * push * tail_perp[1])),
                    )
                    cap_count += 1
                    hook_capped_here = True

                if hook_capped_here:
                    glyph_touched = True

            start = end + 1

        if glyph_touched:
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] hook tail width cap: {cap_count} hooks adjusted across "
        f"{glyph_count} glyphs (seen={hook_seen}, "
        f"tol={HOOK_TAIL_CAP_TOLERANCE}, max_push={HOOK_TAIL_CAP_MAX_PUSH})"
    )


def _contour_signed_area(coords, start: int, end: int) -> float:
    """Shoelace signed area for a TT contour. Outer (CCW) > 0, inner (CW) < 0."""
    n = end - start + 1
    s = 0.0
    for j in range(n):
        x0, y0 = coords[start + j]
        x1, y1 = coords[start + (j + 1) % n]
        s += x0 * y1 - x1 * y0
    return s * 0.5


def luo_horiz_end_emphasis(font: TTFont) -> None:
    """v0.4.4 signature: small downward "stop" at the right end of long horizontals.

    Geometry-only, no character whitelist. For each outer CCW contour, walk
    consecutive on-curve pairs (P_a, P_b). When the chord PaPb is long and
    near horizontal AND has dx > 0 (top edge of the horizontal stroke for
    a CCW outer contour), find the descending side of the cap that follows
    in contour order and push those points DOWN by a small amount that
    decays with distance, creating a quiet print-kai 顿 (stop) at the
    right end. LXGW caps curl UP a few units before turning DOWN, so we
    walk forward past the cap top first.

    Skips:
      - inner contours (holes / counters) so the stop appears only on the
        actual outer top edge of strokes.
      - chords whose follow-on on-curve drops more than ~20% of glyph
        height (a 横折/钩 root, not a free 横画 ending).
      - characters in STRAIGHTEN_SKIP_CHARS (心字底/忄旁/走之底 already have
        their own dedicated geometry passes downstream).
    """
    if LUO_HORIZ_END_EMPHASIS_PUSH_EM <= 0:
        print("[luo] long-h end emphasis: skipped (push=0)")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    push_units = LUO_HORIZ_END_EMPHASIS_PUSH_EM * upm
    n_steps = LUO_HORIZ_END_EMPHASIS_SAMPLES

    seg_count = 0
    glyph_count = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF):
            continue
        char = chr(cp)
        if char in STRAIGHTEN_SKIP_CHARS:
            continue

        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue

        coords = list(glyph.coordinates)
        flags = glyph.flags
        ends = glyph.endPtsOfContours

        all_xs = [c[0] for c in coords]
        all_ys = [c[1] for c in coords]
        glyph_w = max(all_xs) - min(all_xs)
        glyph_h = max(all_ys) - min(all_ys)
        if glyph_w <= 0 or glyph_h <= 0:
            continue
        glyph_max = max(glyph_w, glyph_h)
        min_chord_len = LUO_HORIZ_END_EMPHASIS_MIN_RATIO * glyph_max
        glyph_touched = False

        start = 0
        for end in ends:
            n = end - start + 1
            if n < 8:
                start = end + 1
                continue
            if _contour_signed_area(coords, start, end) >= 0:
                start = end + 1
                continue

            on_curve = [start + j for j in range(n) if flags[start + j] & 1]
            num_oc = len(on_curve)
            if num_oc < 2:
                start = end + 1
                continue

            for k in range(num_oc):
                ia = on_curve[k]
                ib = on_curve[(k + 1) % num_oc]
                ax, ay = coords[ia]
                bx, by = coords[ib]
                dx = bx - ax
                dy = by - ay
                length = math.hypot(dx, dy)
                if length < min_chord_len:
                    continue
                angle_off_h = math.degrees(math.atan2(abs(dy), abs(dx)))
                if angle_off_h > LUO_HORIZ_END_EMPHASIS_ANGLE_DEG:
                    continue
                if dx <= 0:
                    continue

                right_end = ib
                right_oc_pos = (k + 1) % num_oc
                rex, rey = coords[right_end]

                next_oc = on_curve[(right_oc_pos + 1) % num_oc]
                follow_dy = coords[next_oc][1] - rey
                if follow_dy < -0.20 * glyph_h:
                    continue

                push_count = 0
                cap_walked = False
                for offset in range(1, 12):
                    target_pos = right_end + offset
                    if target_pos > end:
                        target_pos = start + (target_pos - end - 1)
                    if target_pos < start or target_pos > end:
                        break
                    px, py = coords[target_pos]
                    if py >= rey - 1:
                        cap_walked = True
                        continue
                    if not cap_walked:
                        break
                    if py < rey - 0.30 * glyph_h:
                        break
                    push_count += 1
                    decay = (n_steps + 1 - push_count) / float(n_steps + 1)
                    if decay <= 0:
                        break
                    new_y = py - push_units * decay
                    coords[target_pos] = (px, int(round(new_y)))
                    if push_count >= n_steps:
                        break

                if push_count > 0:
                    seg_count += 1
                    glyph_touched = True

            start = end + 1

        if glyph_touched:
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] long-h end emphasis: {seg_count} segments across "
        f"{glyph_count} glyphs (push={LUO_HORIZ_END_EMPHASIS_PUSH_EM}em, "
        f"tail_ratio={LUO_HORIZ_END_EMPHASIS_LEN_RATIO}, "
        f"min_ratio={LUO_HORIZ_END_EMPHASIS_MIN_RATIO}, "
        f"angle<={LUO_HORIZ_END_EMPHASIS_ANGLE_DEG}°)"
    )


def luo_hook_root_inward_handle(font: TTFont) -> None:
    """v0.4.4 signature: small inward push on the off-curve handle just before each hook root.

    Detects hooks the same way refine_hooks_final / cap_hook_tail_widths do
    (60-130° angle at p1, asymmetric stem/tail, len_in >= 1.5 × len_out).
    Walks backward from the hook root on-curve to the nearest off-curve
    handle, and pushes that handle a few units toward the glyph centroid.
    Pulling the off-curve toward the centre creates a slight inward bulge
    on the stem just above the knee, a "knuckle" gesture LXGW does not
    have. Push is small (~3 units at 1000 upm) so dense glyphs do not feel
    twisted.
    """
    if LUO_HOOK_ROOT_HANDLE_PUSH_EM <= 0:
        print("[luo] hook-root inward handle: skipped (push=0)")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    push_units = LUO_HOOK_ROOT_HANDLE_PUSH_EM * upm

    hook_count = 0
    glyph_count = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF):
            continue
        char = chr(cp)
        if char in STRAIGHTEN_SKIP_CHARS:
            continue

        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue

        coords = list(glyph.coordinates)
        flags = glyph.flags
        ends = glyph.endPtsOfContours
        all_xs = [c[0] for c in coords]
        all_ys = [c[1] for c in coords]
        cx = (min(all_xs) + max(all_xs)) / 2.0
        cy = (min(all_ys) + max(all_ys)) / 2.0
        glyph_touched = False

        start = 0
        for end in ends:
            n = end - start + 1
            if n < 12:
                start = end + 1
                continue

            for j in range(n):
                idx = start + j
                if not (flags[idx] & 1):
                    continue

                i_prev = start + (j - 1) % n
                i_next = start + (j + 1) % n
                p0x, p0y = coords[i_prev]
                p1x, p1y = coords[idx]
                p2x, p2y = coords[i_next]

                d_in_x = p1x - p0x
                d_in_y = p1y - p0y
                d_out_x = p2x - p1x
                d_out_y = p2y - p1y
                len_in = math.hypot(d_in_x, d_in_y)
                len_out = math.hypot(d_out_x, d_out_y)
                if len_in < 8 or len_out < 5:
                    continue
                if len_out <= 20 or len_out > 90:
                    continue
                if len_in < len_out * 1.5:
                    continue
                cos_a = (d_in_x * d_out_x + d_in_y * d_out_y) / (len_in * len_out)
                cos_a = max(-1.0, min(1.0, cos_a))
                angle = math.degrees(math.acos(cos_a))
                if angle < 60 or angle > 130:
                    continue

                handle_idx = None
                for back in range(1, 5):
                    ti = start + (j - back) % n
                    if not (flags[ti] & 1):
                        handle_idx = ti
                        break
                if handle_idx is None:
                    continue

                hx, hy = coords[handle_idx]
                dirx = cx - hx
                diry = cy - hy
                dist = math.hypot(dirx, diry)
                if dist < 1e-6:
                    continue
                ux = dirx / dist
                uy = diry / dist
                coords[handle_idx] = (
                    int(round(hx + push_units * ux)),
                    int(round(hy + push_units * uy)),
                )
                hook_count += 1
                glyph_touched = True

            start = end + 1

        if glyph_touched:
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] hook-root inward handle: {hook_count} hooks across "
        f"{glyph_count} glyphs (push={LUO_HOOK_ROOT_HANDLE_PUSH_EM}em)"
    )


# --- v0.4.6 Typographic-kai abstractions ---
# Four small geometry-only refinement passes that learn a typographic-kai
# component hierarchy without copying outlines or character whitelists.
# Each detects a topology (signed area, centroid position, aspect, area
# ratio) instead of a name list, so they generalise to the whole CJK set.

def luo_bottom_anchor_settle(font: TTFont) -> None:
    """v0.4.5: lift the lower-stroke layer so a glyph reads less foot-heavy.

    Detection (per outer contour, signed_area <= 0):
      - centroid Y in the lower LUO_BOTTOM_ANCHOR_BAND fraction of glyph height
      - area >= LUO_BOTTOM_ANCHOR_MIN_AREA fraction of glyph bbox area
      - aspect (w/h) >= LUO_BOTTOM_ANCHOR_MIN_ASPECT, OR width >=
        LUO_BOTTOM_ANCHOR_MIN_WIDTH fraction of glyph width (a wide foot block)
    The glyph must have at least one OTHER outer contour above the bottom
    band so a single-stroke 一 / 乙 is not touched. Frame chars and the
    fragile straighten-skip categories (心 / 忄 / 走之底) are skipped because
    they have dedicated geometry passes downstream. KAI_BALANCE roof / stack
    chars also skip so we do not double-compress glyphs that already received
    a tuned per-category bottom-pass. The Y compression is presence-floor
    guarded against `WEB_PRESENCE_H_MIN_EM` so 12-19px body text never loses
    a base horizontal.
    """
    if LUO_BOTTOM_ANCHOR_SCALE_Y >= 1.0 and LUO_BOTTOM_ANCHOR_LIFT_EM <= 0:
        print("[luo] bottom-anchor settle: skipped (identity)")
        return
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    h_min = WEB_PRESENCE_H_MIN_EM * upm
    lift_units = LUO_BOTTOM_ANCHOR_LIFT_EM * upm
    skip = (
        set(STRAIGHTEN_SKIP_CHARS)
        | set(IDENTITY_FRAME_CHARS)
        | set(KAI_BALANCE_ROOF_CHARS)
        | set(KAI_BALANCE_STACK_CHARS)
    )
    seg_count = 0
    glyph_count = 0
    for cp, gname in cmap.items():
        if not (0x3400 <= cp <= 0x9FFF):
            continue
        ch = chr(cp)
        if ch in skip:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours < 2:
            continue
        coords = glyph.coordinates
        box = _glyph_box(coords)
        if box is None:
            continue
        _x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
        glyph_area = glyph_w * glyph_h
        contours = _contour_info(glyph, coords)
        outer = [
            c for c in contours
            if _contour_signed_area(coords, int(c["start"]), int(c["end"])) <= 0
        ]
        if len(outer) < 2:
            continue
        band_top = y_min + glyph_h * LUO_BOTTOM_ANCHOR_BAND
        glyph_touched = False
        for c in outer:
            c_cy = float(c["cy"])
            if c_cy >= band_top:
                continue
            c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
            c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
            area = float(c["area"])
            if area < glyph_area * LUO_BOTTOM_ANCHOR_MIN_AREA:
                continue
            if area > glyph_area * LUO_BOTTOM_ANCHOR_MAX_AREA:
                continue
            wide_foot = c_w >= glyph_w * LUO_BOTTOM_ANCHOR_MIN_WIDTH
            flat_foot = (c_w / c_h) >= LUO_BOTTOM_ANCHOR_MIN_ASPECT
            if not (wide_foot or flat_foot):
                continue
            if not any(other["cy"] > c_cy + glyph_h * 0.18 for other in outer if other is not c):
                continue
            scale_y = _presence_guarded_scale(LUO_BOTTOM_ANCHOR_SCALE_Y, c_h, h_min)
            _scale_contour(coords, c, scale_y=scale_y, shift_y=lift_units)
            seg_count += 1
            glyph_touched = True
        if glyph_touched:
            glyph.recalcBounds(glyf)
            glyph_count += 1
    print(
        f"[luo] bottom-anchor settle: {seg_count} contours across "
        f"{glyph_count} glyphs (scale_y={LUO_BOTTOM_ANCHOR_SCALE_Y}, "
        f"lift={LUO_BOTTOM_ANCHOR_LIFT_EM}em)"
    )


def luo_left_radical_contain(font: TTFont) -> None:
    """v0.4.5: contain a self-contained left radical so it stops bulging.

    Detection (per outer contour, signed_area <= 0):
      - the contour's right edge sits within LUO_LEFT_RADICAL_SPLIT * glyph_w
        of glyph_x_min (i.e. the contour is fully on the left side)
    Aggregate area in [LUO_LEFT_RADICAL_MIN_AREA, LUO_LEFT_RADICAL_MAX_AREA]
    fraction of glyph area, so the rule fires on real left radicals
    (彳/纟/木/扌/木 type) but ignores tiny side dots and full-glyph shapes.

    Skips glyphs already handled by dedicated passes (water / speech /
    side_split whitelist / frame / walk / heart) so we do not double-stack
    on those characters; the new pass picks up everything else with the
    same topology.
    """
    if LUO_LEFT_RADICAL_X >= 1.0 and LUO_LEFT_RADICAL_Y >= 1.0 and LUO_LEFT_RADICAL_GAP_EM <= 0:
        print("[luo] left-radical contain: skipped (identity)")
        return
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    h_min = WEB_PRESENCE_DOT_MIN_EM * upm
    gap_units = LUO_LEFT_RADICAL_GAP_EM * upm
    skip = (
        set(STRAIGHTEN_SKIP_CHARS)
        | set(KAI_BALANCE_SIDE_SPLIT_CHARS)
        | set(KAI_BALANCE_SPEECH_CHARS)
        | set(KAI_BALANCE_WATER_CHARS)
        | set(IDENTITY_FRAME_CHARS)
    )
    seg_count = 0
    glyph_count = 0
    for cp, gname in cmap.items():
        if not (0x3400 <= cp <= 0x9FFF):
            continue
        ch = chr(cp)
        if ch in skip:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours < 3:
            continue
        coords = glyph.coordinates
        box = _glyph_box(coords)
        if box is None:
            continue
        x_min, _x_max, _y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
        glyph_area = glyph_w * glyph_h
        split_x = x_min + glyph_w * LUO_LEFT_RADICAL_SPLIT
        contours = _contour_info(glyph, coords)
        left_outer = [
            c for c in contours
            if float(c["xmax"]) <= split_x
            and _contour_signed_area(coords, int(c["start"]), int(c["end"])) <= 0
        ]
        if not left_outer:
            continue
        total_left_area = sum(float(c["area"]) for c in left_outer)
        if not (
            glyph_area * LUO_LEFT_RADICAL_MIN_AREA
            <= total_left_area
            <= glyph_area * LUO_LEFT_RADICAL_MAX_AREA
        ):
            continue
        glyph_touched = False
        for c in left_outer:
            c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
            c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
            sx = _presence_guarded_scale(LUO_LEFT_RADICAL_X, c_w, h_min)
            sy = _presence_guarded_scale(LUO_LEFT_RADICAL_Y, c_h, h_min)
            _scale_contour(coords, c, scale_x=sx, scale_y=sy, shift_x=gap_units)
            seg_count += 1
            glyph_touched = True
        if glyph_touched:
            glyph.recalcBounds(glyf)
            glyph_count += 1
    print(
        f"[luo] left-radical contain: {seg_count} contours across "
        f"{glyph_count} glyphs (x={LUO_LEFT_RADICAL_X}, y={LUO_LEFT_RADICAL_Y}, "
        f"gap={LUO_LEFT_RADICAL_GAP_EM}em)"
    )


def luo_inner_counter_open(font: TTFont) -> None:
    """v0.4.6: open inner counters, with an extra dense-glyph tier.

    Detection (per inner counter, signed_area > 0):
      - centroid X in [LUO_INNER_COUNTER_BAND_LO, LUO_INNER_COUNTER_BAND_HI]
        fraction of glyph width (the middle column)
      - area in [LUO_INNER_COUNTER_MIN_AREA, LUO_INNER_COUNTER_MAX_AREA]
        fraction of glyph area, so the rule ignores tiny pinholes and the
        whole-glyph counter on frame characters
    Skips frame chars (国/回/...) which already get a stronger counter
    expansion via identity_core_v2; skips fragile straighten categories.
    """
    if LUO_INNER_COUNTER_X <= 1.0 and LUO_INNER_COUNTER_Y <= 1.0:
        print("[luo] inner-counter open: skipped (identity)")
        return
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    seg_count = 0
    dense_seg_count = 0
    dense_glyph_count = 0
    glyph_count = 0
    for cp, gname in cmap.items():
        if not (0x3400 <= cp <= 0x9FFF):
            continue
        ch = chr(cp)
        if ch in STRAIGHTEN_SKIP_CHARS or ch in IDENTITY_FRAME_CHARS:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours < 4:
            continue
        coords = glyph.coordinates
        box = _glyph_box(coords)
        if box is None:
            continue
        x_min, _x_max, _y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
        glyph_area = glyph_w * glyph_h
        band_lo = x_min + glyph_w * LUO_INNER_COUNTER_BAND_LO
        band_hi = x_min + glyph_w * LUO_INNER_COUNTER_BAND_HI
        contours = _contour_info(glyph, coords)
        eligible_counters = []
        dot_like_count = 0
        for c in contours:
            c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
            c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
            area = float(c["area"])
            if (
                int(c["n"]) <= DOT_MAX_POINTS
                and c_w < glyph_w * 0.34
                and c_h < glyph_h * 0.34
                and area < glyph_area * 0.070
            ):
                dot_like_count += 1
            signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
            if signed <= 0:
                continue
            cc_x = float(c["cx"])
            if cc_x < band_lo or cc_x > band_hi:
                continue
            if area < glyph_area * LUO_INNER_COUNTER_MIN_AREA:
                continue
            if area > glyph_area * LUO_INNER_COUNTER_MAX_AREA:
                continue
            eligible_counters.append(c)

        dense_tier = (
            glyph.numberOfContours >= LUO_DENSE_COUNTER_MIN_CONTOURS
            and len(eligible_counters) >= LUO_DENSE_COUNTER_MIN_INNERS
            and (
                len(eligible_counters) >= 2
                or dot_like_count >= LUO_DENSE_COUNTER_DOT_MIN
            )
        )

        glyph_touched = False
        glyph_dense_touched = False
        for c in eligible_counters:
            _scale_contour(coords, c, scale_x=LUO_INNER_COUNTER_X, scale_y=LUO_INNER_COUNTER_Y)
            seg_count += 1
            glyph_touched = True
            if dense_tier:
                _scale_contour(coords, c, scale_x=LUO_DENSE_COUNTER_X, scale_y=LUO_DENSE_COUNTER_Y)
                dense_seg_count += 1
                glyph_dense_touched = True
        if glyph_touched:
            glyph.recalcBounds(glyf)
            glyph_count += 1
            if glyph_dense_touched:
                dense_glyph_count += 1
    print(
        f"[luo] inner-counter open: {seg_count} counters across "
        f"{glyph_count} glyphs (x={LUO_INNER_COUNTER_X}, y={LUO_INNER_COUNTER_Y}, "
        f"band=[{LUO_INNER_COUNTER_BAND_LO},{LUO_INNER_COUNTER_BAND_HI}], "
        f"dense_extra={dense_seg_count}/{dense_glyph_count} "
        f"x={LUO_DENSE_COUNTER_X} y={LUO_DENSE_COUNTER_Y})"
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

    # v0.4 print-kai pivot: turn refinement runs on every CJK glyph so the
    # typographic-kai gesture is consistent across the font. v0.4.1 reduces
    # the default displace to 1.6 to stop creating sharp 折点 on body text
    # hooks and short-stroke joints; the original v0.4 displace (2.2) is kept
    # only for the priority anchor / multi-horiz set so display words still
    # show explicit骨节. Frame chars use their own dedicated knobs.
    priority_count = 0
    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if not cp:
            continue
        if not (0x3400 <= cp <= 0x9FFF):
            continue
        char = chr(cp)
        # Skip the same fragile categories as the straighten pass to avoid
        # breaking 心字底 / 走之底 dedicated geometry.
        if char in STRAIGHTEN_SKIP_CHARS:
            continue
        is_frame_turn = char in TURN_FINAL_FRAME_CHARS
        is_priority_turn = char in TURN_FINAL_CHARS and not is_frame_turn
        seg_max = TURN_FINAL_FRAME_SEG_MAX if is_frame_turn else TURN_FINAL_SEG_MAX
        if is_frame_turn:
            displace = TURN_FINAL_FRAME_DISPLACE
            inner = TURN_FINAL_FRAME_INNER
        elif is_priority_turn:
            displace = TURN_FINAL_PRIORITY_DISPLACE
            inner = TURN_FINAL_PRIORITY_INNER
            priority_count += 1
        else:
            displace = TURN_FINAL_DISPLACE
            inner = TURN_FINAL_INNER

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
        f"inner={TURN_FINAL_INNER}, priority_displace={TURN_FINAL_PRIORITY_DISPLACE}, "
        f"priority_glyphs={priority_count}, frame_displace={TURN_FINAL_FRAME_DISPLACE}, "
        f"frame_inner={TURN_FINAL_FRAME_INNER}, frame_seg_max={TURN_FINAL_FRAME_SEG_MAX}, "
        f"frame_turns={frame_turn_count})"
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
            axis = _dot_long_axis(d_xs, d_ys)
            if axis is None:
                continue
            long_ax, long_ay = axis

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
    cmap = _build_cmap(font)

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
    cmap = _build_cmap(font)

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
    cmap = _build_cmap(font)

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

    ttf_path = DIST_DIR / f"{OUTPUT_PREFIX}.ttf"
    woff2_path = DIST_DIR / f"{OUTPUT_PREFIX}.woff2"

    # Drop the misleading TrueType-outline-in-OpenType-sfnt .otf. We ship a
    # real .ttf for desktop installs and .woff2 for the web. A genuine CFF
    # .otf would need cu2qu reversal + compreffor and a separate visual
    # regression pass, so it lives outside this builder.
    legacy_otf = DIST_DIR / f"{OUTPUT_PREFIX}.otf"
    if legacy_otf.exists():
        try:
            legacy_otf.unlink(missing_ok=True)
            print(f"[luo] removed legacy {legacy_otf.relative_to(ROOT)}")
        except OSError:
            pass

    font.flavor = None
    font.save(str(ttf_path))
    print(f"[luo] wrote {ttf_path.relative_to(ROOT)}")

    font.flavor = "woff2"
    font.save(str(woff2_path))
    print(f"[luo] wrote {woff2_path.relative_to(ROOT)}")


# Files that embed a `?v=<asset-version>` query string against the woff2 or
# luo.css URL. Patched in-place after each successful build so the cache-bust
# token always tracks the actual font binary content.
ASSET_VERSION_FILES = (
    ROOT / "assets" / "styles" / "luo.css",
    ROOT / "assets" / "styles" / "print.css",
    ROOT / "index.html",
)
ASSET_VERSION_PATH = ROOT / "assets" / "asset_version.txt"
ASSET_VERSION_PATTERN = re.compile(
    r"(Luo-Regular\.woff2\?v=|luo\.css\?v=)([^\"'\s)]+)"
)


def compute_asset_version() -> str:
    """Stable cache-bust token derived from font version + woff2 content.

    Falls back to VERSION-only when the woff2 isn't built yet, so callers
    that read the token before the first build still see something useful.
    """
    import hashlib

    woff2_path = DIST_DIR / f"{OUTPUT_PREFIX}.woff2"
    if woff2_path.exists():
        digest = hashlib.sha256(woff2_path.read_bytes()).hexdigest()[:8]
        return f"{VERSION}-{digest}"
    return VERSION


def write_asset_version(version: str) -> None:
    ASSET_VERSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    ASSET_VERSION_PATH.write_text(version + "\n", encoding="utf-8")


def update_asset_versions(version: str) -> None:
    """Rewrite cache-bust query strings in static page/CSS files."""
    write_asset_version(version)
    replacement = lambda m: f"{m.group(1)}{version}"
    updated: list[str] = []
    for path in ASSET_VERSION_FILES:
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        patched, count = ASSET_VERSION_PATTERN.subn(replacement, original)
        if count and patched != original:
            path.write_text(patched, encoding="utf-8")
            updated.append(f"{path.relative_to(ROOT)}({count})")
    if updated:
        print(f"[luo] asset version -> {version} (patched {', '.join(updated)})")
    else:
        print(f"[luo] asset version -> {version}")


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
    clear_cmap_cache(font)
    print(f"[luo] subset to {len(chars)} requested chars")


def font_codepoints(font: TTFont) -> set[int]:
    return set(_build_cmap(font).keys())


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
    # v0.4 print-kai pivot: flatten LXGW's quadratic bow on long near-axis
    # spans. Has to run before narrow/refine so subsequent passes see the
    # already-straighter outline.
    straighten_strokes(font)

    # Narrowing: legacy single-value or complexity-aware
    if NARROW_X is not None:
        nx = float(NARROW_X)
        narrow_and_scale(font, nx, nx, nx, SCALE_Y)
    else:
        narrow_and_scale(font, NARROW_SIMPLE, NARROW_REGULAR, NARROW_COMPLEX, SCALE_Y)

    refine_by_category(font)
    refine_heart_chars(font)
    refine_dot_contours(font)
    refine_kai_component_balance(font)
    luo_bottom_anchor_settle(font)
    luo_left_radical_contain(font)
    luo_inner_counter_open(font)
    refine_turns_final(font)
    luo_horiz_end_emphasis(font)
    refine_black_dot_cluster(font)
    refine_hooks_final(font)
    cap_hook_tail_widths(font)
    luo_hook_root_inward_handle(font)
    refine_walk_final(font)
    refine_display_anchor_chars(font)
    refine_identity_chars(font, requested_chars)
    refine_site_body_readability(font)
    refine_visible_problem_glyphs(font)
    fit_punctuation_width(font, PUNCT_WIDTH_RATIO)
    adjust_space_width(font, SPACE_WIDTH_RATIO)
    adjust_cjk_spacing(font)
    rewrite_names(font)
    validate_required_chars(font, required_chars, BUILD_CHARS)
    write_debug_reports(font, requested_chars)
    save_outputs(font)
    update_asset_versions(compute_asset_version())
    print("[luo] done.")


if __name__ == "__main__":
    main()
