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
  9a. v0.4.6/v0.4.7 typographic-kai abstractions (6 generic component refiners):
       bottom_anchor_settle, left_radical_contain, inner_counter_open,
       dense_counter_tier, top_bottom_separate, frame_inner_open.
 10. Targeted turn refinement (priority frames/endpoints/multi-horiz).
 10b. Luo signature: long-h end micro-emphasis (luo_horiz_end_emphasis).
 11. Dense dot-cluster protection (墨).
 12. Hook refinement on whitelist (refine_hooks_final).
 12b. Geometric cap: hook tail width <= stem width at hook root (cap_hook_tail_widths).
 12c. Luo signature: hook-root inward handle (luo_hook_root_inward_handle).
 13. Walk-radical final containment (透/道/遇/etc.).
 14. Display anchor refinement (落/笔/见).
 15. Identity refinement (anchor + all-covered guardrails + core_v2).
 15b. Visible-problem glyph correction (reported fixes + homepage/proof P0/P1 risk queues).
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
BOLDEN_H = float(os.environ.get("LUO_BOLDEN_H", "1"))   # v0.4.12 round 11: 0 -> 1. Multi-horizontal chars (言/重/量/章) read thin at 20-34px at 0; +2 (maintainer's first pick) pushed the level-1 set to d_dens +0.0311 / over_w05 17.3%, +1 lands on the band edge (+0.0289 / 15.0%) and was chosen. Graduating +H by contour count or source ink ratio did not help: the rise is population-wide. Round 2 history: 6 -> 4 -> 0 after a five-font probe found Luo the heaviest.
BOLDEN_V = float(os.environ.get("LUO_BOLDEN_V", "14"))  # v0.4.2 回补: 13 在补偿参数被撤后主竖发虚，回到 v0.3 档
# Diagonal bonus: linear interpolation gives 撇/捺 about 10.5 at 45° — visually
# too thin next to 15-unit verticals. Add a parabolic bonus that peaks at
# horiz_ratio=0.5 so 撇/捺 carry more weight without disturbing pure
# horizontals/verticals.
BOLDEN_DIAG_BONUS = float(os.environ.get("LUO_BOLDEN_DIAG", "5.0"))  # v0.4.12: 7.0 → 5.0 (two audit-driven steps: 5.5 fixed the display-anchor H/V, then the over_w05 queue showed the residual heavy set was diagonal-dominated 人/切/观/风/流 — one more 0.5 notch). Guard anchors: 代黑点述游清流 diagonal dots must not chip (WEB_PRESENCE_DOT_MIN_EM floor + visual check).
# Legacy single-value override.
BOLDEN_DELTA = os.environ.get("LUO_BOLDEN")
# Graduated boldening: reduce delta as contour count rises.
BOLDEN_GRAD_STEP = float(os.environ.get("LUO_BOLDEN_GRAD_STEP", "0.06"))
BOLDEN_GRAD_FLOOR = float(os.environ.get("LUO_BOLDEN_GRAD_FLOOR", "0.85"))
BOLDEN_DENSE_ONSET = int(os.environ.get("LUO_BOLDEN_DENSE_ONSET", "6"))
BOLDEN_DENSE_STEP = float(os.environ.get("LUO_BOLDEN_DENSE_STEP", "0.04"))
BOLDEN_DENSE_FLOOR = float(os.environ.get("LUO_BOLDEN_DENSE_FLOOR", "0.55"))
BOLDEN_GRAD_ONSET = int(os.environ.get("LUO_BOLDEN_GRAD_ONSET", "3"))

# Endpoint softening (软切角): round sharp corners after boldening.
SOFTEN_ANGLE = float(os.environ.get("LUO_SOFTEN_ANGLE", "120"))
SOFTEN_BLEND = float(os.environ.get("LUO_SOFTEN_BLEND", "0.05"))
SOFTEN_SEG_MAX = float(os.environ.get("LUO_SOFTEN_SEG_MAX", "80"))
# Endpoint subtypes keep one Luo temperament without stamping every terminal
# with the same soft-cut geometry.
ENDPOINT_H_BLEND = float(os.environ.get("LUO_ENDPOINT_H_BLEND", "0.015"))   # v0.4.10 polish: 0.025 → 0.015. Tsanger Print Kai shows nearly cut-flat horizontal endpoints; 0.025 left visible LXGW-style soft round on 正/晋. The remaining 0.015 keeps endpoints from reading as machine-Hei but sits much closer to Tsanger's print-kai cap.
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
STRAIGHTEN_H_BLEND = float(os.environ.get("LUO_STRAIGHTEN_H_BLEND", "0.65"))  # v0.4.10 polish: tried 0.72 to chase Tsanger's flat horizontal but it pulled cap off-curves BELOW the leftmost top on-curve (bolden raises corners, straighten flattens cap controls — net inverted step on 正/晋 at heading sizes). 0.65 keeps cap geometry slightly above the leftmost top corner so the top edge reads as a smooth subtle cap, not a notch. Tsanger's truly-flat top would require redoing the cap geometry at the bolden stage, not over-straightening.
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
STRAIGHTEN_MAX_TURN_DEG = float(os.environ.get("LUO_STRAIGHTEN_MAX_TURN_DEG", "45.0"))  # v0.4.12 round 3: horizontal spans whose control polygon turns more than this are real curves (起/己 bowl), not stroke bows. Horizontal only: on diag spans the same gate re-curved every 撇 back toward LXGW (1088 glyphs moved, LXGW IoU +0.011).
STRAIGHTEN_MAX_TURN_DEG_VD = float(os.environ.get("LUO_STRAIGHTEN_MAX_TURN_DEG_VD", "75.0"))  # round 8: vertical/diag spans turning more than this are real bends (风 横斜弯钩 belly, 游 子 竖钩); 45 here re-curved every 撇 toward LXGW
STRAIGHTEN_BOWL_DIP_EM = float(os.environ.get("LUO_STRAIGHTEN_BOWL_DIP_EM", "0.015"))
STRAIGHTEN_DIAG_NO_THIN = os.environ.get("LUO_STRAIGHTEN_DIAG_NO_THIN", "1") not in ("0", "false")
STRAIGHTEN_DIAG_INWARD_SCALE = float(os.environ.get("LUO_STRAIGHTEN_DIAG_INWARD_SCALE", "0.4"))  # round 9: share of the inward (thinning) diag move that is kept
STRAIGHTEN_V_END_KEEP = float(os.environ.get("LUO_STRAIGHTEN_V_END_KEEP", "0.0"))  # round 13: share of a vertical span at each end left unstraightened (corner shoulders)
STRAIGHTEN_MAX_SAG_RATIO = float(os.environ.get("LUO_STRAIGHTEN_MAX_SAG_RATIO", "0.18"))
STRAIGHTEN_V_CURVY_SAG = float(os.environ.get("LUO_STRAIGHTEN_V_CURVY_SAG", "0.08"))
STRAIGHTEN_MAX_PERP_RATIO = float(os.environ.get("LUO_STRAIGHTEN_MAX_PERP_RATIO", "0.20"))  # v0.4.3 audit fix: 0.18 仍在长横右端拉出三角下尖，放宽到 0.20 让更多 corner controls 被识别保护
# Glyph categories where straightening is known to interfere with a
# dedicated downstream pass; left alone here and shaped by their own
# refiners later in the pipeline.
STRAIGHTEN_SKIP_CHARS = (
    # Single-stroke radicals: the sweep IS the glyph (丿 snapped when straightened).
    "丿乀乁"
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
HOOK_FINAL_TIP_SHARPEN = float(os.environ.get("LUO_HOOK_FINAL_TIP_SHARPEN", "0.13"))  # v0.4.8 refinement: soften residual hook-tip kinks without lengthening hooks
HOOK_FINAL_TIP_SHARPEN_CURVED = float(os.environ.get("LUO_HOOK_FINAL_TIP_SHARPEN_CURVED", "0.08"))
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
HOOK_TAIL_MIN_RISE = float(os.environ.get("LUO_HOOK_TAIL_MIN_RISE", "0.3"))
HOOK_TAIL_MIN_CONTOUR_EM = float(os.environ.get("LUO_HOOK_TAIL_MIN_CONTOUR_EM", "0.25"))
HOOK_TAIL_CAP_SAMPLES = int(os.environ.get("LUO_HOOK_TAIL_CAP_SAMPLES", "7"))  # v0.4.12: 4 → 7 so the tail taper reaches the 竖弯钩 sweep (气/尤/几), not just the first points past the knee.

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
LUO_HORIZ_END_EMPHASIS_PUSH_EM = float(os.environ.get("LUO_HORIZ_END_EMPHASIS_PUSH_EM", "0.0"))  # v0.4.10 polish: was 0.005 → 0.002 → 0. The 顿笔 step at right cap was reading as visible台阶/凹陷 at heading sizes on 正/晋/章/书. Tsanger Print Kai (the private style reference) has no 顿 — its horizontal cap is a clean angular cut. After Phase 1A+B+C brought 90+ high-frequency chars into CORE_V2 structural rewrite, the signature's "geometric distance from LXGW" job is now carried by CORE_V2 + straighten + endpoint blends, and the signature itself was producing visible artifacts that Tsanger does NOT have. Killing it. The pass remains in code (push=0 → return early) so it can be re-enabled by env var if a future regression diagnosis points back at it.
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

# v0.4.11 luo_horiz_cap_flatten: residual cap arc on long horizontal top
# edges. After bolden raises the leftmost top-cap on-curve (~+28u) and
# straighten only partially flattens the off-curve cap arc, the cap apex
# sits a few units above the leftmost top-cap on-curve. At heading sizes
# (≥200px) this reads as a small visible knob/notch on 正 / 晋 / 章 / 书 /
# 觉 / 风 / 章 (and most chars with long horizontals). Tsanger Print Kai's
# print-kai design has a flat top edge and an angular cap drop, no upward
# arc. This pass walks each outer CCW contour, finds horizontal top-edge
# chords (long, near-horizontal, dx > 0), and clamps any off-curve point
# between the two on-curves whose y exceeds the leftmost on-curve y down
# to that y. Skips frozen-glyph 月, STRAIGHTEN_SKIP_CHARS, and inner
# (CCW signed_area > 0) contours.
LUO_HORIZ_CAP_FLATTEN_MIN_RATIO = float(os.environ.get("LUO_HORIZ_CAP_FLATTEN_MIN_RATIO", "0.25"))
LUO_HORIZ_CAP_FLATTEN_MAX_LIFT_EM = float(os.environ.get("LUO_HORIZ_CAP_FLATTEN_MAX_LIFT_EM", "0.04"))  # v0.4.12: real cap lumps rise <= 48u; 贫's dot head rose ~150u above its top chord and got clamped into a wedge.
LUO_HORIZ_CAP_FLATTEN_ANGLE_DEG = float(os.environ.get("LUO_HORIZ_CAP_FLATTEN_ANGLE_DEG", "10.0"))
LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS = "月"

# A2: hook root inward handle. After refine_hooks_final and the geometric
# hook tail width cap, find the off-curve handle just before each detected
# hook root (p1) and push it slightly toward the glyph centroid. The off-
# curve sits on the stem just above the knee, and a small inward push pulls
# the stem-to-hook transition into a slightly inward-curving "knuckle"
# instead of LXGW's straight-into-the-hook geometry.
LUO_HOOK_ROOT_HANDLE_PUSH_EM = float(os.environ.get("LUO_HOOK_ROOT_HANDLE_PUSH_EM", "0.0"))  # v0.4.10 polish: was 0.002 → 0.001 → 0. The inward knuckle was reading as visible kink at heading sizes on 书/字/魏 横折钩 root. Tsanger Print Kai has clean hook-root corners with no inward "knuckle" — the off-curve handle sits on the natural turn arc. Killing the signature (same reasoning as horiz_end_emphasis above). Pass remains in code as a no-op return.

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
LUO_DENSE_COUNTER_X = float(os.environ.get("LUO_DENSE_COUNTER_X", "1.020"))
LUO_DENSE_COUNTER_Y = float(os.environ.get("LUO_DENSE_COUNTER_Y", "1.012"))

# --- v0.4.7 typographic-kai abstractions (2 generic component refiners) ---
# These extend the v0.4.5 / v0.4.6 topology-driven family to the broader
# generic body of glyphs that did not match any earlier specialised pass.
# The site-wide audit on 1,118 page glyphs showed the "generic" bucket
# (no special whitelist) sits at avg raw IoU ≈ 0.84 against LXGW while
# the various special buckets sit at 0.71-0.84 thanks to dedicated
# geometry. The two new passes target the two largest residual topology
# clusters in that generic bucket (≈33% top-bottom + ≈31% frame-with-
# inner) without touching glyphs already shaped by a dedicated pass.
#
# Magnitudes are deliberately small (≤0.005em / ≤2% scale) and respect
# the WEB_PRESENCE_* floor so 12-19px body text never loses an inner
# white or a base horizontal. Both passes skip every existing whitelist
# they could plausibly double-stack with (frame / roof / stack / heart /
# walk / straighten-skip / core_v2). See HANDOFF.md v0.4.7 for the full
# audit log.

# Pass C1 -- top-bottom separation. Detects two outer contours: one with
# centroid in the upper LUO_TOP_BOTTOM_TOP_BAND of glyph height and one
# with centroid in the lower LUO_TOP_BOTTOM_BOT_BAND, each with area
# >= LUO_TOP_BOTTOM_MIN_AREA fraction of the glyph's bbox. The upper
# layer is shifted up by LUO_TOP_BOTTOM_LIFT_EM and the lower layer is
# shifted down by LUO_TOP_BOTTOM_SETTLE_EM and y-scaled by
# LUO_TOP_BOTTOM_BOT_SCALE_Y around its own centroid. Skipped on glyphs
# with two or more "middle outers" (centroid in the band between the two
# bands and area >= LUO_TOP_BOTTOM_MID_BLOCK_AREA) so 三-style stacked
# layouts and densely-middle glyphs are left alone.
LUO_TOP_BOTTOM_TOP_BAND = float(os.environ.get("LUO_TOP_BOTTOM_TOP_BAND", "0.62"))
LUO_TOP_BOTTOM_BOT_BAND = float(os.environ.get("LUO_TOP_BOTTOM_BOT_BAND", "0.38"))
LUO_TOP_BOTTOM_MIN_AREA = float(os.environ.get("LUO_TOP_BOTTOM_MIN_AREA", "0.04"))
LUO_TOP_BOTTOM_MID_BLOCK_AREA = float(os.environ.get("LUO_TOP_BOTTOM_MID_BLOCK_AREA", "0.10"))
LUO_TOP_BOTTOM_LIFT_EM = float(os.environ.get("LUO_TOP_BOTTOM_LIFT_EM", "0.004"))
LUO_TOP_BOTTOM_SETTLE_EM = float(os.environ.get("LUO_TOP_BOTTOM_SETTLE_EM", "0.003"))
LUO_TOP_BOTTOM_BOT_SCALE_Y = float(os.environ.get("LUO_TOP_BOTTOM_BOT_SCALE_Y", "0.992"))
LUO_TOP_BOTTOM_TOP_SCALE_X = float(os.environ.get("LUO_TOP_BOTTOM_TOP_SCALE_X", "0.995"))

# Pass C2 -- frame-with-inner counter open. Detects the largest outer
# contour occupying at least LUO_FRAME_INNER_OUTER_W and
# LUO_FRAME_INNER_OUTER_H of the glyph bbox (the "frame" hull) along
# with at least one inner counter sitting inside it. Off-center inner
# counters (centroid X outside the [LUO_INNER_COUNTER_BAND_LO,
# LUO_INNER_COUNTER_BAND_HI] middle band already handled by
# luo_inner_counter_open) get a small expansion around their own
# centroid. The middle-band counters that luo_inner_counter_open already
# handles are deliberately left to that pass.
LUO_FRAME_INNER_OUTER_W = float(os.environ.get("LUO_FRAME_INNER_OUTER_W", "0.55"))
LUO_FRAME_INNER_OUTER_H = float(os.environ.get("LUO_FRAME_INNER_OUTER_H", "0.55"))
LUO_FRAME_INNER_MIN_AREA = float(os.environ.get("LUO_FRAME_INNER_MIN_AREA", "0.008"))
LUO_FRAME_INNER_MAX_AREA = float(os.environ.get("LUO_FRAME_INNER_MAX_AREA", "0.20"))
LUO_FRAME_INNER_X = float(os.environ.get("LUO_FRAME_INNER_X", "1.010"))
LUO_FRAME_INNER_Y = float(os.environ.get("LUO_FRAME_INNER_Y", "1.006"))

# --- v0.4.12 global vertical posture (luo_posture_contain) ---
# 740-char triple measurement (Luo / private W04 reference / LXGW, 300px em)
# showed Luo's vertical posture is byte-identical to LXGW and ~0.03em lower
# than the print-kai reference on 98-99% of homepage glyphs: ink centroid
# 0.356em vs 0.385em, bottom edge -0.095em vs -0.063em, bbox height 0.916em
# vs 0.896em. No existing pass models this dimension. The fix is a single
# uniform affine y' = pivot + s * (y - pivot) applied to every CJK glyph as
# the LAST outline pass, so every upstream pass keeps working in the
# original coordinate system. Pure affine = no local displacement artifacts
# (the 台阶/折点/two-segment-hook failure classes all came from local
# non-linear moves). Side effect: horizontals thin by (1-s) as a bonus
# toward the W04 stroke-contrast target.
# Do NOT push scale below 0.97: past that the posture shift stops reading
# as "contained print-kai" and starts reading as a squashed face.
# Scale 1.0 = no-op early return (same kill-switch pattern as the v0.4.10
# retired signature passes).
LUO_POSTURE_PIVOT_EM = float(os.environ.get("LUO_POSTURE_PIVOT_EM", "0.80"))
LUO_POSTURE_SCALE_Y = float(os.environ.get("LUO_POSTURE_SCALE_Y", "0.978"))

# --- v0.4.12 long-horizontal thinning (luo_long_horiz_thin) ---
# LXGW's substrate already carries long horizontals thicker than the W04
# print-kai reference (文 H/V 0.89 native vs 0.77 reference), so even after
# BOLDEN_H dropped to 4 the display anchors 文/书/正 kept a weak 横细竖重
# contrast. This pass thins only LONG near-horizontal strokes symmetrically:
# top-edge chords (dx>0 on CCW outers) move down by half the delta, bottom
# edge chords (dx<0) move up by half, so the stroke keeps its own midline.
# Interior off-curves between the chord endpoints move with the chord.
# Long chords are main strokes by definition; secondary horizontals are
# shorter than the MIN_RATIO gate and keep their v0.4.3 readability weight.
# Delta 0 = no-op early return (kill-switch pattern).
LUO_LONG_HORIZ_THIN_EM = float(os.environ.get("LUO_LONG_HORIZ_THIN_EM", "0.006"))
LUO_LONG_HORIZ_THIN_MIN_RATIO = float(os.environ.get("LUO_LONG_HORIZ_THIN_MIN_RATIO", "0.35"))
LUO_LONG_HORIZ_THIN_ANGLE_DEG = float(os.environ.get("LUO_LONG_HORIZ_THIN_ANGLE_DEG", "10.0"))
# Tang-flagged 玄云两来清: long-H thin stacks with gesture free-end taper into
# needle terminals. Skip long-H thin only (do NOT invent free-end geometry —
# free-end blunt / weight-rescue / 清 hard-cut were tried and made shapes worse).
LUO_LONG_HORIZ_THIN_SKIP_CHARS = "玄云两来清"
# Killed after visual regression (Tang: 更丑了). Pass remains as no-op.
LUO_HORIZ_WEIGHT_RESCUE_CHARS = ""
LUO_HORIZ_WEIGHT_RESCUE_EM = float(os.environ.get("LUO_HORIZ_WEIGHT_RESCUE_EM", "0.0"))
LUO_HORIZ_WEIGHT_RESCUE_MIN_RATIO = float(
    os.environ.get("LUO_HORIZ_WEIGHT_RESCUE_MIN_RATIO", "0.22")
)
# Killed after visual regression. Soft/hard free-end rewrites distorted 玄/清.
LUO_FREE_END_BLUNT_CHARS = ""
LUO_FREE_END_BLUNT_ZONE_EM = float(os.environ.get("LUO_FREE_END_BLUNT_ZONE_EM", "0.13"))
LUO_FREE_END_BLUNT_PULL_EM = float(os.environ.get("LUO_FREE_END_BLUNT_PULL_EM", "0.0"))
LUO_FREE_END_BLUNT_PLUMP_EM = float(os.environ.get("LUO_FREE_END_BLUNT_PLUMP_EM", "0.0"))
LUO_FREE_END_BLUNT_THICK_FLOOR_EM = float(
    os.environ.get("LUO_FREE_END_BLUNT_THICK_FLOOR_EM", "0.045")
)

# --- v0.4.12 frame foot tuck (luo_frame_foot_tuck) ---
# Tang's 380px screenshots of 田/晋 flagged the LXGW brush-exit foot at the
# bottom-left of closed frames: the left wall's tip descends ~0.09em below
# the bottom bar's underside with a leftward splay, where the W04 reference
# keeps a small flush tuck. Geometry: find long near-horizontal BOTTOM-edge
# chords (dx<0 on CCW outers) that sit near the GLYPH bottom (nothing in the
# glyph descends more than MAX_DEPTH below them — this single gate rejects
# 于/寺-style glyphs where a 竖钩 legitimately passes below a mid横), then
# clamp same-contour points inside the chord's extended x-band up to
# KEEP_EM below the chord line. KEEP_EM preserves the quiet kai foot.
LUO_FRAME_FOOT_KEEP_EM = float(os.environ.get("LUO_FRAME_FOOT_KEEP_EM", "0.030"))
LUO_FRAME_FOOT_MAX_DEPTH_EM = float(os.environ.get("LUO_FRAME_FOOT_MAX_DEPTH_EM", "0.10"))
LUO_FRAME_FOOT_X_EXTEND_EM = float(os.environ.get("LUO_FRAME_FOOT_X_EXTEND_EM", "0.12"))
LUO_FRAME_FOOT_MIN_RATIO = float(os.environ.get("LUO_FRAME_FOOT_MIN_RATIO", "0.30"))

# --- v0.4.12 frame wall uprighting (luo_frame_upright) ---
# Tang's 380px screenshots of 田/用 flagged the LXGW handwriting tilt on
# frame walls (the right wall leans inward toward the bottom) where W04
# keeps walls upright (竖画稳直). Scope is deliberately the curated
# IDENTITY_CORE_FRAME_CHARS whitelist (minus frozen 月), NOT all CJK: the
# frame chars are where the tilt reads as a defect; on freeform glyphs the
# slant is stroke identity. Geometry: long near-vertical on-curve chords
# (any contour — counters must follow their walls so thickness holds)
# rotate toward vertical about their own midpoint by BLEND; interior
# points shift with the chord line at their own y.
# Round 4: bottom-日 compounds show the same inward-leaning left wall that
# turns 日 into a trapezoid (晋 against W04's upright rectangle).
LUO_FRAME_UPRIGHT_EXTRA_CHARS = "晋普智暂暑春替曾昔皆香音昏晨"
# Round 8: bottom-口 compounds (the 口 in 言 leaned into a trapezoid). The 口
# walls are only ~0.15-0.2 of glyph height, so they get their own lower gate.
LUO_FRAME_UPRIGHT_KOU_CHARS = "言吉告名各右石古合台否兄员占句呈启哥"
LUO_FRAME_UPRIGHT_BLEND = float(os.environ.get("LUO_FRAME_UPRIGHT_BLEND", "0.65"))
LUO_FRAME_UPRIGHT_MAX_SLOPE = float(os.environ.get("LUO_FRAME_UPRIGHT_MAX_SLOPE", "0.14"))
LUO_FRAME_UPRIGHT_MIN_LEN_RATIO = float(os.environ.get("LUO_FRAME_UPRIGHT_MIN_LEN_RATIO", "0.30"))

# --- v0.4.12 long-diagonal thinning (luo_long_diag_thin) ---
# Tang's 48-char overlay round vs W04: Luo's 撇/捺 measured HEAVIER than
# even the LXGW source on simple glyphs (人 35px vs LXGW 29 vs W04 27 at
# 300px) because bolden's 45° interpolation carries half of BOLDEN_V=14
# into diagonal edges. Symmetric inward-normal thinning of LONG diagonal
# chords only: length >= MIN_RATIO x glyph-max and angle inside
# [ANGLE_LO, ANGLE_HI] off horizontal. Short diagonal dots/短撇 never pass
# the length gate, so the 代黑点述游清流 guard set is structurally safe.
LUO_LONG_DIAG_THIN_EM = float(os.environ.get("LUO_LONG_DIAG_THIN_EM", "0.011"))  # simple-glyph delta; graduated down to _EM_COMPLEX as contour count rises (engineering principle #1: lerp toward identity as the input grows). First cut used a flat 0.009 and left curved-substroke 人/入 under-thinned while nudging complex 便 past W04.
LUO_LONG_DIAG_THIN_EM_COMPLEX = float(os.environ.get("LUO_LONG_DIAG_THIN_EM_COMPLEX", "0.005"))
LUO_LONG_DIAG_THIN_TIP_FADE_EM = float(os.environ.get("LUO_LONG_DIAG_THIN_TIP_FADE_EM", "0.20"))  # round 7: shift fades to 0 over this distance toward free ends
LUO_LONG_DIAG_THIN_MIN_WIDTH_EM = float(os.environ.get("LUO_LONG_DIAG_THIN_MIN_WIDTH_EM", "0.068"))  # round 9: never thin a diagonal below this (W04 撇 body ~0.072-0.080em)
LUO_LONG_DIAG_THIN_MIN_RATIO = float(os.environ.get("LUO_LONG_DIAG_THIN_MIN_RATIO", "0.20"))
# v0.4.12 residual round: straight-chord 撇/捺 take the full simple-glyph
# delta while curved ones resist (the 人/入 asymmetry, but inverted) — on
# these Tang-flagged chars the main diagonal measured 6-8px THINNER than
# W04 at 300px after thinning (发 26 vs 34). Exempt rather than re-tune the
# global delta; 人/入 stay in (still +3-5px over W04, documented).
LUO_LONG_DIAG_THIN_SKIP_CHARS = "发校体后声"
LUO_LONG_DIAG_THIN_ANGLE_LO = float(os.environ.get("LUO_LONG_DIAG_THIN_ANGLE_LO", "18.0"))
LUO_LONG_DIAG_THIN_ANGLE_HI = float(os.environ.get("LUO_LONG_DIAG_THIN_ANGLE_HI", "75.0"))

# --- v0.4.12 gesture prototype (luo_gesture_body_contract) ---
# Tang's verdict on the overlay round: the residual "不好看" gap vs W04 is
# skeletal — the reference keeps a tight body (short horizontals, compact
# 中宫) while letting main strokes (撇/捺/钩) extend, producing a
# tension Luo's LXGW substrate lacks (every stroke uniformly wide).
# This pass shortens FREE horizontal stroke ends only: a free end is a cap
# whose contour walk descends by roughly one stroke thickness from the top
# edge to the bottom edge within a narrow x-window; junctions with 竖/折
# descend much further and are skipped automatically. The shift is tapered
# over TAPER_EM so no kinks appear. Main strokes are untouched, so the
# body tightens while 撇捺钩 keep their reach.
# PROTOTYPE: gated to an explicit char list until visually validated.
LUO_GESTURE_H_SHORTEN_EM = float(os.environ.get("LUO_GESTURE_H_SHORTEN_EM", "0.035"))
LUO_GESTURE_TAPER_EM = float(os.environ.get("LUO_GESTURE_TAPER_EM", "0.10"))
LUO_GESTURE_CAP_MAX_DROP_EM = float(os.environ.get("LUO_GESTURE_CAP_MAX_DROP_EM", "0.12"))
LUO_GESTURE_CAP_MIN_DROP_EM = float(os.environ.get("LUO_GESTURE_CAP_MIN_DROP_EM", "0.025"))
LUO_GESTURE_CAP_X_WINDOW_EM = float(os.environ.get("LUO_GESTURE_CAP_X_WINDOW_EM", "0.09"))
LUO_GESTURE_MIN_CHORD_RATIO = float(os.environ.get("LUO_GESTURE_MIN_CHORD_RATIO", "0.28"))
# "all" = every CJK glyph (v0.4.12 rollout after the 文来觉里 prototype
# passed visual review); an explicit char string restricts the pass.
LUO_GESTURE_BODY_CHARS = os.environ.get("LUO_GESTURE_BODY_CHARS", "all")
# v0.4.12 residual round: chars whose W04 counterpart keeps WIDE layered
# horizontals — the 0.035em free-end shorten cost them 10-21px of face
# width at 300px (书 -11 / 晋 -10 / 整 -17 / 声 -21 measured against the
# pre-gesture baseline) and Tang re-flagged all four. Skip, don't rescale.
# +玄云两来清: skip free-end shorten so tip taper does not stack with BOLDEN_H.
LUO_GESTURE_SKIP_CHARS = "书整声晋玄云两来清"
# Main-stroke protection: bottom main 横 (王/里/且 bottom bar, or 一-style
# flat single-stroke glyphs) act as 主笔 in kai and keep their reach.
LUO_GESTURE_MAIN_H_MIN_W = float(os.environ.get("LUO_GESTURE_MAIN_H_MIN_W", "0.70"))
LUO_GESTURE_MAIN_H_BAND = float(os.environ.get("LUO_GESTURE_MAIN_H_BAND", "0.30"))
LUO_GESTURE_FLAT_GLYPH_RATIO = float(os.environ.get("LUO_GESTURE_FLAT_GLYPH_RATIO", "0.35"))

# --- v0.4.12 shallow kink join (luo_horiz_kink_join) ---
# straighten_strokes flattens each on-curve span on its own, so a long
# bowl bottom (绝/色/儿/电 竖弯钩) whose LXGW outline carries a mid on-curve
# comes out as two straight halves meeting in a V. When two consecutive
# near-horizontal spans meet at a shallow downward kink, lift the middle
# on-curve onto the outer chord and carry its span's controls with a hat
# weight so the edge reads as one line. Real junctions turn far more than
# MAX_TURN and are left alone.
LUO_KINK_JOIN_MAX_TURN_DEG = float(os.environ.get("LUO_KINK_JOIN_MAX_TURN_DEG", "28.0"))
LUO_KINK_JOIN_MIN_SAG = float(os.environ.get("LUO_KINK_JOIN_MIN_SAG", "3.0"))
LUO_KINK_JOIN_MAX_SAG_EM = float(os.environ.get("LUO_KINK_JOIN_MAX_SAG_EM", "0.05"))
LUO_KINK_JOIN_MIN_LOCAL_TURN_DEG = float(os.environ.get("LUO_KINK_JOIN_MIN_LOCAL_TURN_DEG", "4.0"))
LUO_KINK_JOIN_ANGLE_DEG = float(os.environ.get("LUO_KINK_JOIN_ANGLE_DEG", "14.0"))

# --- v0.4.12 shallow corner smoothing (luo_smooth_shallow_corners) ---
# The same bowl-bottom V also shows where an on-curve sits between two
# off-curves with a small tangent break (儿/元 outer and inner edges), a
# shape the on-curve span test above never sees. Put such an on-curve back
# on the line through its two handles (G1) when both handles run within
# ANGLE_DEG of horizontal and the break is under MAX_TURN_DEG.
LUO_SMOOTH_CORNER_MAX_TURN_DEG = float(os.environ.get("LUO_SMOOTH_CORNER_MAX_TURN_DEG", "28.0"))
LUO_SMOOTH_CORNER_ANGLE_DEG = float(os.environ.get("LUO_SMOOTH_CORNER_ANGLE_DEG", "20.0"))
LUO_SMOOTH_CORNER_MAX_MOVE_EM = float(os.environ.get("LUO_SMOOTH_CORNER_MAX_MOVE_EM", "0.02"))

# --- v0.4.12 na modulation (luo_na_modulate) ---
# Five-font round 2: every reference kai (W04 / Hanyi / STKaiti) writes 捺
# thin at the entry and swelling into the foot; Luo's 捺 inherited a
# uniform LXGW bar. Geometry: find down-right foot tips on outer contours,
# walk both sides up-left by arc length, and narrow (never widen) the part
# above FOOT_EM toward foot_width * ENTRY at REGION_EM. Points whose local
# width jumps past JOINT_RATIO x foot width sit at a junction and stay put.
LUO_NA_REGION_EM = float(os.environ.get("LUO_NA_REGION_EM", "0.42"))
LUO_NA_FOOT_EM = float(os.environ.get("LUO_NA_FOOT_EM", "0.12"))
LUO_NA_ENTRY = float(os.environ.get("LUO_NA_ENTRY", "0.62"))
LUO_NA_MAX_PUSH_EM = float(os.environ.get("LUO_NA_MAX_PUSH_EM", "0.014"))
LUO_NA_JOINT_RATIO = float(os.environ.get("LUO_NA_JOINT_RATIO", "1.5"))
LUO_NA_ANGLE_MIN = float(os.environ.get("LUO_NA_ANGLE_MIN", "20.0"))
# 平捺 (辶/廴/走/之/处/是 bottoms) runs at 12-19°, the same band as sloped
# horizontal right ends (且/五/会/国), which geometry alone cannot separate.
# The low band is therefore opened only for glyphs that carry a 平捺.
LUO_NA_FLAT_ANGLE_MIN = float(os.environ.get("LUO_NA_FLAT_ANGLE_MIN", "3.0"))
LUO_NA_FLAT_REGION_EM = float(os.environ.get("LUO_NA_FLAT_REGION_EM", "0.70"))
LUO_NA_FLAT_ENTRY = float(os.environ.get("LUO_NA_FLAT_ENTRY", "0.55"))
LUO_NA_FLAT_CHARS = (
    "边达迁过迎运近还这进远违连述迷迹追退适选透途通逝速造遂遇遐遑道遗遥遨避邀遍送逢"
    "走赴赶起越趁超趋趣赵建廷延之乏处是题匙堤提"
)
LUO_NA_ANGLE_MAX = float(os.environ.get("LUO_NA_ANGLE_MAX", "60.0"))

# --- v0.4.12 round 5 na foot swell (luo_na_foot_swell) ---
# W04 捺 (人大文来徐这 at 600px, per-mille em from the tip) peaks 92-105 about
# 0.03-0.05em up; Luo's 捺 was a flat 63-88 bar. Grow-only bump.
LUO_NA_SWELL_PEAK_EM = float(os.environ.get("LUO_NA_SWELL_PEAK_EM", "0.090"))
LUO_NA_SWELL_RISE_EM = float(os.environ.get("LUO_NA_SWELL_RISE_EM", "0.045"))
LUO_NA_SWELL_HOLD_EM = float(os.environ.get("LUO_NA_SWELL_HOLD_EM", "0.08"))
LUO_NA_SWELL_FADE_EM = float(os.environ.get("LUO_NA_SWELL_FADE_EM", "0.22"))
LUO_NA_SWELL_MAX_PUSH_EM = float(os.environ.get("LUO_NA_SWELL_MAX_PUSH_EM", "0.020"))
LUO_NA_SWELL_REL = float(os.environ.get("LUO_NA_SWELL_REL", "0.12"))
LUO_NA_SWELL_KEEP_TIP_EM = float(os.environ.get("LUO_NA_SWELL_KEEP_TIP_EM", "0.045"))
LUO_NA_SWELL_STEP_EM = float(os.environ.get("LUO_NA_SWELL_STEP_EM", "0.08"))

# --- v0.4.12 round 6 stem width normalize (luo_stem_normalize) ---
# Homepage review against W04: vertical stems/walls were uneven, not simply
# heavy (per-mille em at 512px: 口 92-94, 四 94-96, 门 92-96, 川 96, but
# 目 64-66 and 白's right wall 57), while W04 keeps every wall within 76-90.
# BOLDEN_V stays at its red line; this pass only pulls outliers into the
# band. A stem is a pair of long near-vertical on-curve chords: an upward
# chord (left edge, ink to its right) and the nearest downward chord to its
# right that overlaps it vertically. Both edges move symmetrically.
LUO_STEM_NORM_HI_EM = float(os.environ.get("LUO_STEM_NORM_HI_EM", "0.080"))
LUO_STEM_NORM_LO_EM = float(os.environ.get("LUO_STEM_NORM_LO_EM", "0.068"))
LUO_STEM_NORM_MIN_LEN_RATIO = float(os.environ.get("LUO_STEM_NORM_MIN_LEN_RATIO", "0.18"))
LUO_STEM_NORM_BULGE_MAX_EM = float(os.environ.get("LUO_STEM_NORM_BULGE_MAX_EM", "0.050"))  # round 10: how far an outward-bowed stem edge (书 竖钩 belly) is pulled back to its chord
LUO_STEM_NORM_WALL_TARGET_EM = float(os.environ.get("LUO_STEM_NORM_WALL_TARGET_EM", "0.074"))  # round 13: thin outer frame walls (典 right wall was 0.045em, W04 0.08em)
LUO_STEM_NORM_WALL_MAX_PUSH_EM = float(os.environ.get("LUO_STEM_NORM_WALL_MAX_PUSH_EM", "0.035"))  # outer edge only, counters untouched
LUO_STEM_NORM_MAX_SHIFT_EM = float(os.environ.get("LUO_STEM_NORM_MAX_SHIFT_EM", "0.008"))

# --- v0.4.12 round 8 upward flick taper (luo_flick_taper) ---
# 横斜弯钩 / 竖弯钩 end in an upward flick (风几九气飞机飘). LXGW leaves a
# round finger-tip there; W04 tapers it to a point. Find upward tips in the
# lower-right of the glyph, walk both sides down by arc length, and narrow
# (never widen) toward TIP x the full width at REGION_EM below the tip.
LUO_FLICK_REGION_EM = float(os.environ.get("LUO_FLICK_REGION_EM", "0.10"))
LUO_FLICK_TIP = float(os.environ.get("LUO_FLICK_TIP", "0.40"))
LUO_FLICK_MAX_PUSH_EM = float(os.environ.get("LUO_FLICK_MAX_PUSH_EM", "0.014"))

# --- small stroke plump floor (luo_small_stroke_plump) ---
# Round 8: 式/游 top dots still read as slashes: Luo's 式 dot was 0.048em thick
# and 0.18em long (aspect 3.75) vs W04 0.092em / 0.20em (aspect 2.2).
LUO_SMALL_PLUMP_FLOOR_EM = float(os.environ.get("LUO_SMALL_PLUMP_FLOOR_EM", "0.070"))  # was a hard-coded 0.050
LUO_SMALL_PLUMP_MAX_SCALE = float(os.environ.get("LUO_SMALL_PLUMP_MAX_SCALE", "1.6"))  # was 1.35

# --- v0.4.12 pie tail fill (luo_pie_tail_fill) ---
# Full-glyph sweep against W04: long left-falling 撇 (厂/广/疒/尸 heads,
# 儿/成/片/后) inherit LXGW's needle taper and read as a hairline next to
# the reference, whose 撇 keeps flesh down to a blunt point. Geometry: find
# down-left tips on outer contours whose two sides climb up-right steeply
# (>= ANGLE_MIN from horizontal, which excludes 提), measure the body width
# REGION_EM above the tip, and grow (never shrink) each side toward a
# half-width profile body/2 * (TIP + (1-TIP) * x**POW), x = s/REGION.
LUO_PIE_FILL_REGION_EM = float(os.environ.get("LUO_PIE_FILL_REGION_EM", "0.36"))
LUO_PIE_FILL_TIP = float(os.environ.get("LUO_PIE_FILL_TIP", "0.35"))
LUO_PIE_FILL_POW = float(os.environ.get("LUO_PIE_FILL_POW", "0.5"))
LUO_PIE_FILL_MAX_PUSH_EM = float(os.environ.get("LUO_PIE_FILL_MAX_PUSH_EM", "0.020"))
LUO_PIE_FILL_TIP_RAMP_EM = float(os.environ.get("LUO_PIE_FILL_TIP_RAMP_EM", "0.06"))
LUO_PIE_FILL_BODY_MIN_EM = float(os.environ.get("LUO_PIE_FILL_BODY_MIN_EM", "0.080"))
LUO_PIE_FILL_ANGLE_MIN = float(os.environ.get("LUO_PIE_FILL_ANGLE_MIN", "48.0"))
LUO_PIE_FILL_ANGLE_MAX = float(os.environ.get("LUO_PIE_FILL_ANGLE_MAX", "84.0"))

# --- v0.4.12 face-narrow queue (luo_face_narrow) ---
# Same overlay round: a curated set of homepage chars reads clearly wider
# than the W04 aspect (red bbox spilling both sides of the gray reference).
# Global NARROW_* stays frozen ("字面偏大，不做窄体" is design intent);
# this queue narrows only the flagged chars, per char, around the bbox
# centre. Screenshot-driven bottom channel, same spirit as
# refine_visible_problem_glyphs.
LUO_FACE_NARROW_CHARS = {
    # v0.4.12 ugly-queue: 里 was over-narrowed (Δw −19px vs W04 at 300px);
    # relax 0.960 → 0.988 so layered 横 regain print-kai face width.
    "里": 0.988, "两": 0.975, "风": 0.995, "字": 0.985,
    "直": 0.968, "声": 0.968, "套": 0.970, "觉": 0.970, "整": 0.995,
    "瓶": 0.968, "正": 0.972, "云": 0.990, "体": 0.960,
    # residual3 + ugly-queue (bbox-measured vs W04, not overlay impression)
    "文": 0.960, "天": 0.960, "代": 0.935, "印": 0.965,
    # 来: 0.940 over-squeezed mid 横 into a thin bar; settle near 0.97
    "来": 0.968, "点": 0.952, "兮": 0.968, "病": 0.975,
}

# --- v0.4.12 dense-ink relief (audit-driven, per-char) ---
# The six-dim audit's over_w05 tail is dominated by glyphs whose strokes
# fuse into 1-4 contours (而/切/枕/川...), so bolden's contour-count
# complexity proxy grades them "simple" and they carry full BOLDEN_V=14.
# The global V dial stays untouched (Do NOT); instead every audit density
# breach (over_w05 or d_dens >= +0.06 vs the reference) lands in a static
# tier list and only long near-vertical chords thin, chord-shift style like
# luo_long_diag_thin. 辶 sweeps and 忄 joins never qualify (angle + length
# gates), so the STRAIGHTEN_SKIP protection is not re-needed here. Hole
# contours participate: ink also sits right of travel on the reversed
# winding, so the same shift widens counters (密字开内白).
# v0.4.12 residual3: refresh membership from the live audit queue; escalate
# still-over_w05 chars one tier (never demote; never raise the global EM).
LUO_DENSE_INK_RELIEF_EM = float(os.environ.get("LUO_DENSE_INK_RELIEF_EM", "0.0085"))
LUO_DENSE_INK_AUTO_CONTOURS = int(os.environ.get("LUO_DENSE_INK_AUTO_CONTOURS", "9"))
LUO_DENSE_INK_AUTO_TIER = float(os.environ.get("LUO_DENSE_INK_AUTO_TIER", "1.0"))
LUO_DENSE_INK_RELIEF_TIERS = {
    # ugly-queue escalate: 字/风/赢/魔 dens +0.04~0.06 and still over_w05 or
    # visibly blacker than W04 at 200px; 书/套/肿/流 dens +0.03~0.04.
    1.00: "丽幽明骤网遇慨麟愀瞬字风赢魔套书",
    0.75: "而骨切岖枕景前酾透违惮这靡愧命感述酒川方杂道怀襟选部陶翳接耕撇适悦排惆刚抢徘览刺情赋遐飘肿流清气荒",
    0.55: "溯山聊匏然期还疏版慷崎见",
}

# --- v0.4.12 per-char posture lift (audit residual outliers) ---
# After the global posture affine, a sparse-glyph tail still sits 0.035em+
# lower than the reference (一/人/入/立...: the print kai lifts simple chars
# off the baseline further than LXGW does). Whole-glyph vertical translate,
# value in em (+ = up). 晋 is negative: the v0.4.12 per-char slim + face
# narrow left it floating 0.037em above the reference bottom edge.
# v0.4.12 residual3: only severe homepage-visible residuals (|d_bot|≥0.033
# or |d_cy|≥0.050, or floating-high score outliers). Do NOT bulk-extend
# this into a general similarity-by-translation channel.
LUO_CHAR_POSTURE_LIFT = {
    "一": 0.030, "江": 0.030, "正": 0.042, "入": 0.030, "立": 0.030,
    "两": 0.020,
    "人": 0.028, "性": 0.028, "征": 0.026, "玉": 0.026, "如": 0.026,
    "悟": 0.026, "乙": 0.024, "又": 0.024, "文": 0.024, "温": 0.024,
    "主": 0.024, "空": 0.022, "洞": 0.022, "到": 0.022, "止": 0.022,
    "壬": 0.022, "迎": 0.022, "万": 0.024, "晋": -0.018,
    # residual3 low-posture dense frames / multi-horiz (lift up)
    "丽": 0.035, "而": 0.026, "切": 0.028, "明": 0.026,
    # residual3 floating-high (push down toward reference baseline)
    # 帝: first cut -0.028 fixed d_bot but overshot d_cy; settle at -0.018
    "帝": -0.018, "密": -0.030, "幽": -0.024,
    # ugly-queue posture: 源 cy too low; 里 bot low; 意 floating high
    "源": 0.022, "里": 0.016, "意": -0.014,
    # round 6 homepage review: closed frames sat 0.050-0.067em below the
    # reference bottom edge; lift about half of it to avoid the 帝 d_cy overshoot
    "日": 0.030, "巨": 0.030, "田": 0.026, "吕": 0.030, "回": 0.030,
}

# --- v0.4.12 hook tail taper (inside cap_hook_tail_widths) ---
# The same screenshot round flagged club-foot hook tails on 用/饥/荒: the
# tail keeps full stem width to its blunt end, where W04 tapers toward the
# tip. The cap pass already walks tail samples with symmetric push
# machinery; the taper reuses it with a per-sample width target that
# narrows linearly from stem width at the knee to TIP_FACTOR × stem at the
# last sample. 1.0 disables the taper (cap-only, pre-v0.4.12 behaviour).
LUO_HOOK_TAIL_TAPER_TIP = float(os.environ.get("LUO_HOOK_TAIL_TAPER_TIP", "0.55"))  # v0.4.12 second notch: 0.60 left the 气/尤/几 sweep still club-ish; paired with SAMPLES 4→7 so the taper reaches the sweep, not just the knee.

# --- Targeted turn refinement (Pass C, full CJK with priority bump) ---
# v0.4.1 reduction: the v0.4 default DISPLACE=2.5 ran on every CJK glyph and
# created sharp 折点 at hook roots and short-stroke joints, contributing to
# the 笔/书/览/无 two-segment look. The new default keeps a quieter bone-node
# globally and reserves the v0.4 displacement only for the curated priority
# anchor / frame / multi-horiz characters that benefit from explicit骨节.
TURN_FINAL_ANGLE_MAX = 105.0
TURN_FINAL_DISPLACE = float(os.environ.get("LUO_TURN_FINAL_DISPLACE", "1.6"))
TURN_FINAL_INNER = float(os.environ.get("LUO_TURN_FINAL_INNER", "0.955"))
TURN_FINAL_PRIORITY_DISPLACE = float(os.environ.get("LUO_TURN_FINAL_PRIORITY_DISPLACE", "1.75"))  # v0.4.8 refinement: keep display bone nodes but soften residual 钩根/折点 roughness
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
# v0.4.9 Phase 1A: 由/自/田/曲/直/电/用 enter the FRAME_RISK channel so the
# upstream pass owns counter opening at 1.065/1.040 and the core_v2
# frame_posture pass narrows stems at 0.988 without double-stacking the
# counter expand. The earlier guardrail-only treatment kept these chars in
# the homepage generic bucket at raw IoU 0.86-0.88 vs LXGW; site_grouped
# audit identified them as the dominant "first-glance LXGW" cluster.
IDENTITY_FRAME_RISK_CHARS = "目日月且由田曲直电用"  # v0.4.12: 自 demoted (Tang flagged as ugly — stem 11% each side vs Tsanger 17%; the FRAME_RISK 1.065/1.040 counter expand stacked with core_v2 0.988 stem narrow over-narrowed 自's vertical stems. Other 6 chars stems 30-38% are fine.)
# v0.4.10 Phase 1B: +重事算第章 (喜基真 already covered) so the layer extension
# fires only `_identity_core_layer_gap` and skips `_identity_core_open_counters`
# / `_identity_core_lighten_secondary`. 重 also runs through TURN_FINAL_PRIORITY,
# 章 through MULTI_HORIZ, 第 through HOOK_FINAL — adding them to LAYER_RISK
# keeps core_v2's contribution to a single quiet layer-gap shift instead of
# triple-stacking on already-treated chars.
IDENTITY_LAYER_RISK_CHARS = "昔音喜甚基真备审省革其重事算第章"
IDENTITY_CORE_V2_CHARS = (
    "落文字书心清骨风纸印永和九年兰亭集序国回日目用月团透道遇墨点游流黑"
    "前赤壁赋归去来兮辞春暮山用壁年之来癸在于稽赤丑阴"
    "由自田曲直电"
    "重事算基真章第喜大太夫又关"
)  # v0.4.9 Phase 1A: +由自田曲直电 / v0.4.10 Phase 1B: +重事算基真章第喜 / Phase 1C: +大太夫又关
IDENTITY_CORE_FRAME_CHARS = "国回日目用月团由自田曲直电"  # v0.4.9 Phase 1A
IDENTITY_CORE_LAYER_CHARS = "春暮壁前墨黑兰亭集序重事算基真章第喜"  # v0.4.10 Phase 1B
IDENTITY_CORE_DIAG_CHARS = "文永之来去归兮辞大太夫又关"  # v0.4.10 Phase 1C
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
IDENTITY_ALL_BOTTOM_EXPAND = float(os.environ.get("LUO_IDENTITY_ALL_BOTTOM_EXPAND", "1.004"))  # v0.4.12: 1.012 → 1.004 (v0.3 value). The 740-char posture audit showed the print-kai reference sits HIGHER than LXGW (bottom edge -0.063em vs -0.089em) while this knob was actively pushing bottoms further down on 99% of glyphs. Reverting to the v0.3 magnitude keeps a small grounding cue without fighting luo_posture_contain.
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
IDENTITY_CORE_LAYER_GAP_EM = float(os.environ.get("LUO_IDENTITY_CORE_LAYER_GAP_EM", "0.007"))  # v0.4.10: was 0.010 (tuned for 10 Lanting-Xu display anchors); after Phase 1B added 8 body-frequency chars (重事算基真章第喜) the original 0.010em over-spread 章/喜 vertically. 0.007 keeps the print-kai layer signal on display anchors while pulling body 章 into a comfortable spread.
IDENTITY_CORE_FRAME_STEM_X = float(os.environ.get("LUO_IDENTITY_CORE_FRAME_STEM_X", "0.988"))
IDENTITY_CORE_DIAG_EDGE_EM = float(os.environ.get("LUO_IDENTITY_CORE_DIAG_EDGE_EM", "0.020"))
IDENTITY_CORE_DIAG_TOP_CONTAIN = float(os.environ.get("LUO_IDENTITY_CORE_DIAG_TOP_CONTAIN", "0.990"))
IDENTITY_CORE_DIAG_TAIL_CONTAIN = float(os.environ.get("LUO_IDENTITY_CORE_DIAG_TAIL_CONTAIN", "0.012"))

BUILD_CHARS = os.environ.get("LUO_BUILD_CHARS", "gb2312-full")  # v0.4.12: shipped font covers all of GB2312 (6763 chars + starter extras)
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
VERSION = "0.4.12"

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
    base = max(BOLDEN_GRAD_FLOOR, 1.0 - (n - BOLDEN_GRAD_ONSET) * BOLDEN_GRAD_STEP)
    # Round 16: very dense glyphs (鬣/齉/馨, 8+ contours, mostly GB2312 level 2)
    # filled their counters at the 0.85 floor. Keep thinning past it.
    if n > BOLDEN_DENSE_ONSET:
        base = max(BOLDEN_DENSE_FLOOR, BOLDEN_GRAD_FLOOR - (n - BOLDEN_DENSE_ONSET) * BOLDEN_DENSE_STEP)
    return base


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
            # Ink side of travel: right for outer contours (negative area in
            # this pipeline), left for counters.
            ink_sign = 1.0 if _contour_signed_area(coords, start, end) < 0 else -1.0
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

                # Real curves are not bowed straight strokes: a stroke bow
                # turns a few degrees along its control polygon, a bowl or
                # rounded corner (起/己 bottom, 走 平捺 belly) turns 60-90°.
                # Pulling those controls to the chord flattened each half on
                # its own and left a wavy edge, so skip high-turn spans.
                turn_limit = STRAIGHTEN_MAX_TURN_DEG if kind == "h" else STRAIGHTEN_MAX_TURN_DEG_VD
                if turn_limit > 0:
                    poly = [coords[i_a]] + [coords[i] for i in interior] + [coords[i_b]]
                    turn = 0.0
                    for (x0, y0), (x1, y1), (x2, y2) in zip(poly, poly[1:], poly[2:]):
                        u = (x1 - x0, y1 - y0)
                        v = (x2 - x1, y2 - y1)
                        if (u[0] == 0 and u[1] == 0) or (v[0] == 0 and v[1] == 0):
                            continue
                        turn += abs(math.degrees(math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])))
                    # v/diag spans only count as a bend when they also dip
                    # below both endpoints (a bowl bottom: 风 横斜弯钩, 游 子
                    # 竖钩). Plain turn counting re-curved every 撇 toward
                    # LXGW (1079 glyphs moved, LXGW IoU 0.656 -> 0.662).
                    is_bend = turn > turn_limit
                    if is_bend and kind == "v":
                        # Round 9: vertical spans straighten (a 竖钩 bowl let
                        # through re-curved 子 in 好/游 back to LXGW).
                        is_bend = False
                    if is_bend and kind == "diag":
                        dip = min(ay, by) - min(py for _, py in poly[1:-1])
                        is_bend = dip > STRAIGHTEN_BOWL_DIP_EM * font["head"].unitsPerEm
                    if is_bend:
                        stats["curve_skip"] = stats.get("curve_skip", 0) + 1
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
                # Round 14: a span whose interior sags far from its chord is a
                # real sweep (竖撇 in 介/丛/丿), not a hand-drawn bow; pulling
                # it to the chord snapped the stroke at the seam.
                _pl = [coords[i] for i in interior]
                _sag = max(abs((qx - ax) * dy - (qy - ay) * dx) / length for qx, qy in _pl)
                # Round 15: a steep 竖撇 (柳/卯) classifies as "v"; treat a
                # visibly curved one like a diagonal so it is not thinned.
                _curvy = _sag > STRAIGHTEN_V_CURVY_SAG * length
                if STRAIGHTEN_MAX_SAG_RATIO > 0:
                    if _sag > STRAIGHTEN_MAX_SAG_RATIO * length:
                        stats["curve_skip"] = stats.get("curve_skip", 0) + 1
                        continue
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
                    # Round 13: keep the shoulder where a vertical meets its
                    # 横折 corner (典's right wall looked sliced off).
                    if kind == "v" and STRAIGHTEN_V_END_KEEP > 0 and (t < STRAIGHTEN_V_END_KEEP or t > 1.0 - STRAIGHTEN_V_END_KEEP):
                        continue
                    proj_x = ax + t * dx
                    proj_y = ay + t * dy
                    # Round 9: on diagonals, never pull a point into the ink.
                    # Straightening both edges of a curved 撇 toward their own
                    # chords thinned 岁's long 撇 by ~0.016em; only the
                    # outward (sag-removing) half of the move is kept.
                    if (kind == "diag" or (kind == "v" and _curvy)) and STRAIGHTEN_DIAG_NO_THIN:
                        mvx, mvy = proj_x - px, proj_y - py
                        # ink normal = right of travel (dy, -dx) for ink_sign 1
                        inward = (mvx * dy - mvy * dx) * ink_sign > 0
                    else:
                        inward = False
                    b_here = blend * STRAIGHTEN_DIAG_INWARD_SCALE if inward else blend
                    new_x = px + b_here * (proj_x - px)
                    new_y = py + b_here * (proj_y - py)
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
WALK_FINAL_BOTTOM_RAISE_EM = float(os.environ.get("LUO_WALK_FINAL_BOTTOM_RAISE_EM", "0.035"))  # v0.4.12: 0.050 → 0.035. The global luo_posture_contain affine already lifts bottoms by ~0.017em at the walk-radical band; stacked with 0.050 the walk chars overshot the W04 bottom edge by +0.02~+0.037em (透/道/远/造/选/述 flipped from below-reference to above-reference in the style audit). Net containment is preserved.
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
KAI_BALANCE_WATER_X_SCALE = float(os.environ.get("LUO_KAI_BALANCE_WATER_X_SCALE", "0.945"))  # v0.4.8 refinement: reduce 氵 mid-gray while keeping v0.4.3 presence floor
KAI_BALANCE_WATER_Y_SCALE = float(os.environ.get("LUO_KAI_BALANCE_WATER_Y_SCALE", "0.942"))  # v0.4.8 refinement: small identity-safe gray correction
KAI_BALANCE_WATER_BOTTOM_RAISE_EM = float(os.environ.get("LUO_KAI_BALANCE_WATER_BOTTOM_RAISE_EM", "0.024"))
KAI_BALANCE_WATER_TOP_RAISE_EM = float(os.environ.get("LUO_KAI_BALANCE_WATER_TOP_RAISE_EM", "0.006"))

KAI_BALANCE_DENSE_COUNTER_CHARS = "魔赢耀题额籍麟馈覆藏霜霞露感皆熹苦"
KAI_BALANCE_COUNTER_EXPAND_X = float(os.environ.get("LUO_KAI_BALANCE_COUNTER_EXPAND_X", "1.125"))
KAI_BALANCE_COUNTER_EXPAND_Y = float(os.environ.get("LUO_KAI_BALANCE_COUNTER_EXPAND_Y", "1.095"))
KAI_BALANCE_DENSE_LAYER_X = float(os.environ.get("LUO_KAI_BALANCE_DENSE_LAYER_X", "0.972"))
KAI_BALANCE_DENSE_LAYER_Y = float(os.environ.get("LUO_KAI_BALANCE_DENSE_LAYER_Y", "0.968"))
KAI_BALANCE_DENSE_LAYER_GAP_EM = float(os.environ.get("LUO_KAI_BALANCE_DENSE_LAYER_GAP_EM", "0.0035"))
KAI_BALANCE_DENSE_UPPER_X = float(os.environ.get("LUO_KAI_BALANCE_DENSE_UPPER_X", "0.988"))
KAI_BALANCE_DENSE_UPPER_Y = float(os.environ.get("LUO_KAI_BALANCE_DENSE_UPPER_Y", "0.975"))

KAI_BALANCE_BOOK_DOT_X_SCALE = float(os.environ.get("LUO_KAI_BALANCE_BOOK_DOT_X_SCALE", "0.940"))
KAI_BALANCE_BOOK_DOT_Y_SCALE = float(os.environ.get("LUO_KAI_BALANCE_BOOK_DOT_Y_SCALE", "0.880"))
KAI_BALANCE_BOOK_DOT_RAISE_EM = float(os.environ.get("LUO_KAI_BALANCE_BOOK_DOT_RAISE_EM", "0.006"))

KAI_BALANCE_SPEECH_CHARS = (
    "言计订讣认讥讦讧讨让讪讫训议讯记讲讳讴讵讶讷许讹论"
    "讼讽设访诀证评诅识诈诉诊诋诌词译试诗诚话诞诡询"
    "该详诧诫诬语误诱诲说诵请诸诺读课谁调谅谈谊谋谍"
    "谎谐谓谗谦谧谨"
)
KAI_BALANCE_SPEECH_SECONDARY_X = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_SECONDARY_X", "0.940"))
KAI_BALANCE_SPEECH_SECONDARY_Y = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_SECONDARY_Y", "0.958"))
KAI_BALANCE_SPEECH_DOT_X = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_DOT_X", "0.880"))  # v0.4.3 audit fix: 言/讠点 body size 偏小，放宽 X 让点不收成针
KAI_BALANCE_SPEECH_DOT_Y = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_DOT_Y", "0.860"))  # v0.4.3 audit fix: 同步放宽 Y
KAI_BALANCE_SPEECH_COUNTER_X = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_COUNTER_X", "1.125"))
KAI_BALANCE_SPEECH_COUNTER_Y = float(os.environ.get("LUO_KAI_BALANCE_SPEECH_COUNTER_Y", "1.065"))
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
KAI_BALANCE_SIDE_LEFT_X = float(os.environ.get("LUO_KAI_BALANCE_SIDE_LEFT_X", "0.965"))  # v0.4.8 refinement: contain 欢/给-style left radicals a touch more
KAI_BALANCE_SIDE_LEFT_Y = float(os.environ.get("LUO_KAI_BALANCE_SIDE_LEFT_Y", "0.978"))
KAI_BALANCE_SIDE_LEFT_GAP_EM = float(os.environ.get("LUO_KAI_BALANCE_SIDE_LEFT_GAP_EM", "0.000"))
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
HOMEPAGE_P0_GRID_GLYPHS = "曲重田首里用"  # v0.4.10 Phase 1A follow-up: 用 加进 grid 通道，补足 v0.4.9 漏的结构改写
HOMEPAGE_P0_HOOK_GLYPHS = "争色事第使"
HOMEPAGE_P0_COMPONENT_GLYPHS = "技盖准装输"
HOMEPAGE_P1_GRID_GLYPHS = "虽县单盘基算相官抽自堵盏革由吕审目"
HOMEPAGE_P1_HOOK_GLYPHS = "求角走种值快强支别战同也持联继服"
HOMEPAGE_P1_COMPONENT_GLYPHS = "者邑棹斗身蓄考难每再维植徊岫鱼查扁主轼复建理具郁"
HOMEPAGE_P1_RADICAL_GLYPHS = "往轻给法浅"
HOMEPAGE_P1_ROOF_GLYPHS = "宙宇安定宿"
HOMEPAGE_P2_SOURCE_RISK_GLYPHS = "堆共皋其组要稚携净直粟独樽鹿古耳真距型律便更寓展虾仲朗果免雅暑腹窗柯蛟着看郎槊"
HOMEPAGE_P3_STRUCTURE_GLYPHS = "曲抽角重争盘者岫虽盏求种复基斗色相革事再棹堵难官县每植堆"
HOMEPAGE_P4_RESIDUAL_RISK_GLYPHS = "去要共朗型携考单技粟稚第樽便理鱼具邑仲皋独值律其身虾快看腹雅柯距展更鹿直扁耳槊由车帖强免建郎轼算走藉里净盛使组主真徘果暑畴路昌夫同较古关如寓追着蓄查眄眼撇详支嫠供境蛟疏旗象细窗娱绝诵根裳维挪别荆很狼输谢奇"
HOMEPAGE_P5_STUBBORN_RISK_GLYPHS = "曲去重抽种盘斗仲如堆考求律盏樽"
HOMEPAGE_P6_LEFT_RIGHT_GLYPHS = "抽独种技虾便雅柯携稚供堵朗难建邑仲快看腹距展更鹿鱼具皋值律其身"
# v0.4.11: luo_horiz_cap_flatten was a 8-char whitelist; v0.4.11 generalised
# it to a geometry-only pass (chord-line clamp) so every horizontal-with-cap
# benefits, not just the named anchors. The list below is kept as a
# back-compat reference for downstream callers that still import the symbol.
LUO_HORIZ_CAP_FLATTEN_CHARS = "正晋章书世西二南"
LUO_DIAG_ENDPOINT_CLEAN_CHARS = "从入人八为失"
LUO_CURVE_TAIL_POLISH_CHARS = "风气成饥荒"  # v0.4.12: +饥荒 (Tang's 380px screenshots: 几/竖弯钩 lower-right tails still club-blunt after the generic hook-tail taper; same defect class as the original 风气成 queue)
VISIBLE_PROBLEM_GLYPHS = "".join(dict.fromkeys(
    "两月或则魔答荒平刚晋书风字赢"  # v0.4.12 ugly-queue: +字赢
    + HOMEPAGE_P0_GRID_GLYPHS
    + HOMEPAGE_P0_HOOK_GLYPHS
    + HOMEPAGE_P0_COMPONENT_GLYPHS
    + HOMEPAGE_P1_GRID_GLYPHS
    + HOMEPAGE_P1_HOOK_GLYPHS
    + HOMEPAGE_P1_COMPONENT_GLYPHS
    + HOMEPAGE_P1_RADICAL_GLYPHS
    + HOMEPAGE_P1_ROOF_GLYPHS
    + HOMEPAGE_P2_SOURCE_RISK_GLYPHS
    + HOMEPAGE_P4_RESIDUAL_RISK_GLYPHS
    + HOMEPAGE_P5_STUBBORN_RISK_GLYPHS
))


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
KAI_BALANCE_STACK_BOTTOM_X = float(os.environ.get("LUO_KAI_BALANCE_STACK_BOTTOM_X", "0.925"))  # v0.4.8 refinement: reduce 实/库 bottom heaviness without returning to v0.4.1 crush
KAI_BALANCE_STACK_BOTTOM_Y = float(os.environ.get("LUO_KAI_BALANCE_STACK_BOTTOM_Y", "0.905"))
KAI_BALANCE_STACK_BOTTOM_RAISE_EM = float(os.environ.get("LUO_KAI_BALANCE_STACK_BOTTOM_RAISE_EM", "0.022"))

KAI_BALANCE_WIDE_DIAG_CHARS = "斗考兴今式气全分走去一而后层可"
KAI_BALANCE_WIDE_EDGE_CONTAIN = float(os.environ.get("LUO_KAI_BALANCE_WIDE_EDGE_CONTAIN", "0.034"))
KAI_BALANCE_WIDE_BOTTOM_CONTAIN = float(os.environ.get("LUO_KAI_BALANCE_WIDE_BOTTOM_CONTAIN", "0.050"))
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

    # v0.4.11-fix: reduce counter expansion to account for upstream
    # topology passes (inner_counter_open 1.040x on middle-band counters,
    # frame_inner_open 1.010x on off-band counters) that now fire before
    # this hand-craft. Old 1.050/1.065 stacked to 1.06-1.11x net,
    # thinning 人 strokes visibly. Keep shifts for positional refinement.
    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed <= 0:
            continue
        ccy = float(c["cy"])
        y_t = (ccy - y_min) / max(1.0, glyph_h)
        if y_t > 0.62:
            _scale_contour(coords, c, 1.005, 1.005, 0.004 * upm, -0.003 * upm)
        else:
            _scale_contour(coords, c, 1.010, 1.008, -0.004 * upm, 0.002 * upm)
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
    """Freeze 月 to the Luo v0.3 outline.

    v0.4.8 tried local frame/counter adjustments first, but the result mixed
    the v0.4 hook/root rhythm with a v0.3-like left sweep and looked unnatural.
    Keep this as an explicit point-lock exception; later generic frame/grid
    passes must not reinterpret 月 again.
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours != 3 or len(coords) != 50:
        return False
    moon_v03_coords = [
        (1485, -273), (1405, -277), (1199, -93), (1086, 14), (1083, 65),
        (1091, 98), (1126, 98), (1153, 102), (1324, -2), (1421, -53),
        (1414, 513), (697, 481), (620, 110), (266, -188), (183, -249),
        (150, -245), (112, -245), (104, -209), (106, -176), (145, -130),
        (398, 156), (567, 665), (573, 1152), (574, 1365), (570, 1486),
        (544, 1567), (549, 1592), (560, 1626), (601, 1626), (632, 1630),
        (736, 1566), (1476, 1616), (1526, 1620), (1589, 1544),
        (1594, 1506), (1579, 1453), (1611, -43), (1616, -117),
        (1620, -178), (1595, -217), (1547, -276), (736, 1088),
        (1422, 1132), (1415, 1450), (740, 1397), (712, 628),
        (1431, 662), (1427, 973), (733, 940), (746, 742),
    ]
    touched = False
    for i, (new_x, new_y) in enumerate(moon_v03_coords):
        if tuple(coords[i]) == (new_x, new_y):
            continue
        coords[i] = (new_x, new_y)
        touched = True
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_answer(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    _x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    contours = _contour_info(glyph, coords)
    touched = False

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed >= 0:
            continue
        c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
        cy_t = (float(c["cy"]) - y_min) / max(1.0, glyph_h)
        if cy_t > 0.35 or c_w < glyph_w * 0.45:
            continue
        band = 0.36
        max_drop = 0.0075 * upm
        c_ymin = float(c["ymin"])
        for i in range(int(c["start"]), int(c["end"]) + 1):
            x, y = coords[i]
            y_t = (y - c_ymin) / c_h
            if y_t >= band:
                continue
            t = (band - y_t) / band
            drop = max_drop * t
            if drop <= 0.1:
                continue
            coords[i] = (x, int(round(y - drop)))
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_homepage_p0_grid(glyph, glyf, upm: int) -> bool:
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
        c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
        aspect = c_w / c_h
        y_t = (float(c["cy"]) - y_min) / max(1.0, glyph_h)
        sx = 1.045 if aspect > 1.30 else 1.035
        sy = 1.030 if c_h > glyph_h * 0.16 else 1.020
        shift_y = 0.0
        if y_t > 0.62:
            shift_y = 0.002 * upm
        elif y_t < 0.36:
            shift_y = -0.002 * upm
        _scale_contour(coords, c, sx, sy, 0.0, shift_y)
        touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_homepage_p0_hook(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 1:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    contours = _contour_info(glyph, coords)
    touched = False

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed > 0:
            _scale_contour(coords, c, 1.025, 1.014)
            touched = True
            continue
        if float(c["area"]) < glyph_w * glyph_h * 0.12:
            continue
        for i in range(int(c["start"]), int(c["end"]) + 1):
            x, y = coords[i]
            xn = (x - x_min) / max(1.0, glyph_w)
            yn = (y - y_min) / max(1.0, glyph_h)
            if xn <= 0.54 or yn >= 0.34:
                continue
            t = (xn - 0.54) / 0.46 * (0.34 - yn) / 0.34
            new_x = cx + (x - cx) * (1.0 - 0.020 * t)
            new_y = y + 0.006 * upm * t
            coords[i] = (int(round(new_x)), int(round(new_y)))
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_homepage_p0_component(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    glyph_area = glyph_w * glyph_h
    contours = _contour_info(glyph, coords)
    touched = False

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        c_area = float(c["area"])
        ccx = float(c["cx"])
        ccy = float(c["cy"])
        if signed > 0:
            _scale_contour(coords, c, 1.035, 1.020)
            touched = True
            continue
        if c_area < glyph_area * 0.035:
            continue
        if ccx < cx - glyph_w * 0.12 and c_area < glyph_area * 0.45:
            _scale_contour(coords, c, 0.980, 0.988, 0.003 * upm, 0.0)
            touched = True
        elif ccy > y_min + glyph_h * 0.60 and c_area < glyph_area * 0.50:
            _scale_contour(coords, c, 0.988, 0.988, 0.0, 0.002 * upm)
            touched = True
        elif ccy < y_min + glyph_h * 0.35 and c_area > glyph_area * 0.16:
            _scale_contour(coords, c, 0.992, 0.990, 0.0, 0.001 * upm)
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_homepage_p2_source_risk(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    _x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    glyph_area = glyph_w * glyph_h
    contours = _contour_info(glyph, coords)
    touched = False

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        c_area = float(c["area"])
        ccx = float(c["cx"])
        ccy = float(c["cy"])
        area_ratio = c_area / max(1.0, glyph_area)

        if signed > 0:
            if 0.004 <= area_ratio <= 0.20:
                _scale_contour(coords, c, 1.025, 1.014)
                touched = True
            continue

        if area_ratio < 0.025:
            continue
        if ccx < cx - glyph_w * 0.14 and area_ratio < 0.45:
            _scale_contour(coords, c, 0.986, 0.992, 0.002 * upm, 0.0)
            touched = True
        elif ccx > cx + glyph_w * 0.18 and area_ratio < 0.35:
            _scale_contour(coords, c, 0.988, 0.996, -0.001 * upm, 0.0)
            touched = True
        elif ccy > y_min + glyph_h * 0.62 and area_ratio < 0.50:
            _scale_contour(coords, c, 0.994, 0.992, 0.0, 0.0015 * upm)
            touched = True
        elif ccy < y_min + glyph_h * 0.34 and area_ratio < 0.55:
            _scale_contour(coords, c, 0.996, 0.994, 0.0, -0.001 * upm)
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_homepage_p3_structure(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    glyph_area = glyph_w * glyph_h
    contours = _contour_info(glyph, coords)
    touched = False

    largest_outer = None
    largest_area = 0.0
    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed >= 0:
            continue
        if float(c["area"]) > largest_area:
            largest_outer = c
            largest_area = float(c["area"])

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        c_area = float(c["area"])
        area_ratio = c_area / max(1.0, glyph_area)
        ccx = float(c["cx"])
        ccy = float(c["cy"])

        if signed > 0:
            if not (0.004 <= area_ratio <= 0.22):
                continue
            c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
            c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
            aspect = c_w / c_h
            nx = (ccx - x_min) / max(1.0, glyph_w)
            ny = (ccy - y_min) / max(1.0, glyph_h)
            shift_x = (nx - 0.50) * 0.010 * upm
            if ny > 0.62:
                shift_y = 0.004 * upm
            elif ny < 0.34:
                shift_y = -0.004 * upm
            else:
                shift_y = -0.001 * upm
            sx = 1.075 if aspect > 1.35 else 1.055
            sy = 1.045 if aspect < 1.20 else 1.030
            _scale_contour(coords, c, sx, sy, shift_x, shift_y)
            touched = True
            continue

        if area_ratio < 0.025:
            continue
        if c is not largest_outer:
            if ccx < cx - glyph_w * 0.14 and area_ratio < 0.45:
                _scale_contour(coords, c, 0.982, 0.990, 0.004 * upm, 0.0)
                touched = True
            elif ccx > cx + glyph_w * 0.18 and area_ratio < 0.40:
                _scale_contour(coords, c, 0.986, 0.994, -0.003 * upm, 0.0)
                touched = True
            elif ccy > y_min + glyph_h * 0.62 and area_ratio < 0.50:
                _scale_contour(coords, c, 0.990, 0.990, 0.0, 0.003 * upm)
                touched = True
            elif ccy < y_min + glyph_h * 0.34 and area_ratio < 0.55:
                _scale_contour(coords, c, 0.994, 0.992, 0.0, -0.002 * upm)
                touched = True

    if largest_outer is not None and largest_area >= glyph_area * 0.36:
        for i in range(int(largest_outer["start"]), int(largest_outer["end"]) + 1):
            x, y = coords[i]
            xn = (x - x_min) / max(1.0, glyph_w)
            yn = (y - y_min) / max(1.0, glyph_h)
            new_x = float(x)
            new_y = float(y)
            if yn > 0.70:
                top_t = (yn - 0.70) / 0.30
                new_x = cx + (new_x - cx) * (1.0 - 0.006 * top_t)
                new_y += 0.003 * upm * top_t
            elif yn < 0.25:
                bot_t = (0.25 - yn) / 0.25
                new_x = cx + (new_x - cx) * (1.0 + 0.004 * bot_t)
                new_y -= 0.002 * upm * bot_t
            if xn > 0.58 and yn < 0.38:
                tail_t = (xn - 0.58) / 0.42 * (0.38 - yn) / 0.38
                new_x = cx + (new_x - cx) * (1.0 - 0.012 * tail_t)
                new_y += 0.004 * upm * tail_t
            new_xy = (int(round(new_x)), int(round(new_y)))
            if new_xy != tuple(coords[i]):
                coords[i] = new_xy
                touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_homepage_p4_residual(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    glyph_area = glyph_w * glyph_h
    contours = _contour_info(glyph, coords)
    touched = False

    largest_outer = None
    largest_area = 0.0
    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed >= 0:
            continue
        if float(c["area"]) > largest_area:
            largest_outer = c
            largest_area = float(c["area"])

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        c_area = float(c["area"])
        area_ratio = c_area / max(1.0, glyph_area)
        ccx = float(c["cx"])
        ccy = float(c["cy"])

        if signed > 0:
            if not (0.004 <= area_ratio <= 0.20):
                continue
            nx = (ccx - x_min) / max(1.0, glyph_w)
            ny = (ccy - y_min) / max(1.0, glyph_h)
            shift_x = (nx - 0.50) * 0.006 * upm
            if ny > 0.62:
                shift_y = 0.0025 * upm
            elif ny < 0.34:
                shift_y = -0.0025 * upm
            else:
                shift_y = 0.0
            _scale_contour(coords, c, 1.045, 1.024, shift_x, shift_y)
            touched = True
            continue

        if c is largest_outer or area_ratio < 0.025:
            continue
        if ccx < cx - glyph_w * 0.14 and area_ratio < 0.45:
            _scale_contour(coords, c, 0.988, 0.994, 0.002 * upm, 0.0)
            touched = True
        elif ccx > cx + glyph_w * 0.18 and area_ratio < 0.40:
            _scale_contour(coords, c, 0.990, 0.996, -0.0015 * upm, 0.0)
            touched = True
        elif ccy > y_min + glyph_h * 0.62 and area_ratio < 0.50:
            _scale_contour(coords, c, 0.994, 0.994, 0.0, 0.0015 * upm)
            touched = True
        elif ccy < y_min + glyph_h * 0.34 and area_ratio < 0.55:
            _scale_contour(coords, c, 0.996, 0.996, 0.0, -0.001 * upm)
            touched = True

    if largest_outer is not None and largest_area >= glyph_area * 0.36:
        for i in range(int(largest_outer["start"]), int(largest_outer["end"]) + 1):
            x, y = coords[i]
            xn = (x - x_min) / max(1.0, glyph_w)
            yn = (y - y_min) / max(1.0, glyph_h)
            new_x = float(x)
            new_y = float(y)
            if yn > 0.72:
                top_t = (yn - 0.72) / 0.28
                new_x = cx + (new_x - cx) * (1.0 - 0.004 * top_t)
                new_y += 0.002 * upm * top_t
            elif yn < 0.23:
                bot_t = (0.23 - yn) / 0.23
                new_x = cx + (new_x - cx) * (1.0 + 0.003 * bot_t)
                new_y -= 0.0015 * upm * bot_t
            if xn > 0.60 and yn < 0.34:
                tail_t = (xn - 0.60) / 0.40 * (0.34 - yn) / 0.34
                new_x = cx + (new_x - cx) * (1.0 - 0.008 * tail_t)
                new_y += 0.0025 * upm * tail_t
            new_xy = (int(round(new_x)), int(round(new_y)))
            if new_xy != tuple(coords[i]):
                coords[i] = new_xy
                touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_homepage_p5_stubborn(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    if glyph.numberOfContours < 1:
        return False
    glyph_area = glyph_w * glyph_h
    contours = _contour_info(glyph, coords)
    touched = False

    largest_outer = None
    largest_area = 0.0
    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed >= 0:
            continue
        if float(c["area"]) > largest_area:
            largest_outer = c
            largest_area = float(c["area"])

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        c_area = float(c["area"])
        area_ratio = c_area / max(1.0, glyph_area)
        ccx = float(c["cx"])
        ccy = float(c["cy"])

        if signed > 0:
            if not (0.004 <= area_ratio <= 0.24):
                continue
            nx = (ccx - x_min) / max(1.0, glyph_w)
            ny = (ccy - y_min) / max(1.0, glyph_h)
            shift_x = (nx - 0.50) * 0.018 * upm
            if ny > 0.62:
                shift_y = 0.006 * upm
            elif ny < 0.34:
                shift_y = -0.006 * upm
            else:
                shift_y = -0.002 * upm
            _scale_contour(coords, c, 1.100, 1.052, shift_x, shift_y)
            touched = True
            continue

        if c is largest_outer or area_ratio < 0.025:
            continue
        if ccx < cx - glyph_w * 0.14 and area_ratio < 0.45:
            _scale_contour(coords, c, 0.972, 0.984, 0.0045 * upm, 0.0)
            touched = True
        elif ccx > cx + glyph_w * 0.18 and area_ratio < 0.42:
            _scale_contour(coords, c, 0.976, 0.988, -0.0035 * upm, 0.0)
            touched = True
        elif ccy > y_min + glyph_h * 0.62 and area_ratio < 0.52:
            _scale_contour(coords, c, 0.982, 0.984, 0.0, 0.0035 * upm)
            touched = True
        elif ccy < y_min + glyph_h * 0.34 and area_ratio < 0.56:
            _scale_contour(coords, c, 0.990, 0.986, 0.0, -0.0025 * upm)
            touched = True

    if largest_outer is not None and largest_area >= glyph_area * 0.34:
        for i in range(int(largest_outer["start"]), int(largest_outer["end"]) + 1):
            x, y = coords[i]
            xn = (x - x_min) / max(1.0, glyph_w)
            yn = (y - y_min) / max(1.0, glyph_h)
            new_x = float(x)
            new_y = float(y)
            if yn > 0.70:
                top_t = (yn - 0.70) / 0.30
                new_x = cx + (new_x - cx) * (1.0 - 0.012 * top_t)
                new_y += 0.005 * upm * top_t
            elif yn < 0.24:
                bot_t = (0.24 - yn) / 0.24
                new_x = cx + (new_x - cx) * (1.0 + 0.007 * bot_t)
                new_y -= 0.0035 * upm * bot_t
            if xn > 0.58 and yn < 0.36:
                tail_t = (xn - 0.58) / 0.42 * (0.36 - yn) / 0.36
                new_x = cx + (new_x - cx) * (1.0 - 0.020 * tail_t)
                new_y += 0.006 * upm * tail_t
            new_xy = (int(round(new_x)), int(round(new_y)))
            if new_xy != tuple(coords[i]):
                coords[i] = new_xy
                touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_qu(glyph, glyf, upm: int) -> bool:
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    touched = False
    for i in range(len(coords)):
        x, y = coords[i]
        xn = (x - x_min) / max(1.0, glyph_w)
        yn = (y - y_min) / max(1.0, glyph_h)
        new_x = float(x)
        new_y = float(y)
        if yn > 0.68:
            t = (yn - 0.68) / 0.32
            new_x = cx + (new_x - cx) * (1.0 - 0.018 * t)
            new_y += 0.005 * upm * t
        elif yn < 0.30:
            t = (0.30 - yn) / 0.30
            new_x = cx + (new_x - cx) * (1.0 + 0.014 * t)
            new_y -= 0.004 * upm * t
            if yn < 0.26:
                foot_t = (0.26 - yn) / 0.26
                new_x = cx + (new_x - cx) * (1.0 + 0.012 * foot_t)
                new_y -= 0.003 * upm * foot_t
        if xn > 0.58 and yn < 0.42:
            t = (xn - 0.58) / 0.42 * (0.42 - yn) / 0.42
            new_x = cx + (new_x - cx) * (1.0 - 0.028 * t)
            new_y += 0.007 * upm * t
        new_xy = (int(round(new_x)), int(round(new_y)))
        if new_xy != tuple(coords[i]):
            coords[i] = new_xy
            touched = True
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_dou(glyph, glyf, upm: int) -> bool:
    # `斗` stays source-like if the two left dots keep LXGW's size/placement.
    # Apply the P5 skeleton polish first, then make the dots shorter and more
    # tucked like the Tsanger-style reference without starving body sizes.
    touched = _refine_homepage_p5_stubborn(glyph, glyf, upm)
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 3:
        return touched
    contours = _contour_info(glyph, coords)
    largest_outer = max(contours, key=lambda c: float(c["area"]))
    dot_touched = False
    for c in contours:
        if c is largest_outer:
            continue
        area_ratio = float(c["area"]) / max(1.0, box[4] * box[5])
        if not (0.015 <= area_ratio <= 0.11):
            continue
        _scale_contour(coords, c, 0.940, 0.940, 0.004 * upm, 0.004 * upm)
        dot_touched = True
    if dot_touched:
        glyph.recalcBounds(glyf)
    return touched or dot_touched


def _refine_problem_chong(glyph, glyf, upm: int) -> bool:
    touched = _refine_homepage_p5_stubborn(glyph, glyf, upm)
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return touched
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    contours = _contour_info(glyph, coords)
    counter_touched = False
    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed <= 0:
            continue
        nx = (float(c["cx"]) - x_min) / max(1.0, glyph_w)
        ny = (float(c["cy"]) - y_min) / max(1.0, glyph_h)
        _scale_contour(
            coords,
            c,
            1.020,
            1.010,
            (nx - 0.50) * 0.002 * upm,
            (ny - 0.50) * 0.0008 * upm,
        )
        counter_touched = True
    if counter_touched:
        glyph.recalcBounds(glyf)
    return touched or counter_touched


def _refine_problem_seed_zhong(glyph, glyf, upm: int) -> bool:
    touched = _refine_homepage_p5_stubborn(glyph, glyf, upm)
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return touched
    _x_min, _x_max, _y_min, _y_max, _glyph_w, _glyph_h, cx, _cy = box
    contours = _contour_info(glyph, coords)
    local_touched = False
    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed < 0 and float(c["cx"]) < cx:
            _scale_contour(coords, c, 0.995, 0.995, 0.001 * upm, 0.0)
            local_touched = True
        elif signed > 0:
            _scale_contour(coords, c, 1.010, 1.005, 0.0, 0.0)
            local_touched = True
    if local_touched:
        glyph.recalcBounds(glyf)
    return touched or local_touched


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
            # v0.4.11-fix: reduce from 1.100/1.080 to account for
            # upstream inner_counter_open (1.040x/1.020y). Old stacked
            # to 1.144x net, thinning 戈 strokes. Keep moderate delta.
            _scale_contour(coords, c, 1.020, 1.015)
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
            # Outer hull slightly wider: ugly-queue measured Δw −21px vs W04
            if float(c["area"]) >= max_area * 0.80:
                _scale_contour(coords, c, 1.030, 0.995)
                touched = True
            continue
        c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
        aspect = c_w / c_h
        ccy = float(c["cy"])
        area = float(c["area"])
        # Open counters so title sizes stop reading as blobs.
        if area > max_area * 0.050:
            sx, sy = 1.095, 1.070
        elif aspect > 2.0:
            sx, sy = 1.130, 1.090
        else:
            sx, sy = 1.100, 1.075
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


def _refine_problem_huang(glyph, glyf, upm: int) -> bool:
    """Restore middle 亡 connection + v0.4.12: taper bottom 川 tips.

    v0.4.11 baseline: strengthens middle 亡 component connection.
    v0.4.12 add: Tang flagged 川 (3 bottom strokes) as too thick/short. For
    each of the 3 bottom outer contours (cy < 30% glyph_h), find the
    lowest on-curve (the 撇/竖 endpoint) and pull adjacent off-curves 25%
    toward it, producing a tapered tip without changing stroke length.
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 3:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    glyph_area = glyph_w * glyph_h
    touched = False

    for c in _contour_info(glyph, coords):
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        cy_t = (float(c["cy"]) - y_min) / max(1.0, glyph_h)
        area_ratio = float(c["area"]) / max(1.0, glyph_area)
        if signed > 0 or not (0.46 <= cy_t <= 0.66) or area_ratio <= 0.18:
            continue

        # Dense/top-bottom/identity stacking leaves the middle 亡 component
        # optically under-connected at display sizes. Strengthen only this
        # contour so the center no longer reads as a missing chunk.
        _scale_contour(coords, c, 1.006, 1.018, 0.0, -0.0015 * upm)
        touched = True
        for i in range(int(c["start"]), int(c["end"]) + 1):
            x, y = coords[i]
            xn = (x - x_min) / max(1.0, glyph_w)
            yn = (y - y_min) / max(1.0, glyph_h)
            if not (0.34 < xn < 0.66 and 0.39 < yn < 0.58):
                continue
            t = (
                (1.0 - abs(xn - 0.50) / 0.16)
                * (1.0 - abs(yn - 0.485) / 0.095)
            )
            if t <= 0:
                continue
            coords[i] = (x, int(round(y - 0.003 * upm * t)))
            touched = True

    # v0.4.12: taper the 3 bottom 川 stroke tips. Each川 stroke is an outer
    # contour with cy in lower 30% of glyph. Find lowest on-curve (撇/竖 tip)
    # and pull adjacent off-curves toward it 25% to sharpen the endpoint.
    flags = glyph.flags
    for c in _contour_info(glyph, coords):
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        cy_t = (float(c["cy"]) - y_min) / max(1.0, glyph_h)
        if signed > 0 or cy_t > 0.30:
            continue
        s_c = int(c["start"])
        e_c = int(c["end"])
        # Find lowest on-curve in this contour (the stroke tip)
        tip_idx = -1
        tip_y = float("inf")
        for i in range(s_c, e_c + 1):
            if not (flags[i] & 1):
                continue
            if coords[i][1] < tip_y:
                tip_y = coords[i][1]
                tip_idx = i
        if tip_idx < 0:
            continue
        tx, ty = coords[tip_idx]
        for off_idx in (tip_idx - 1, tip_idx + 1):
            if off_idx < s_c:
                off_idx = e_c
            elif off_idx > e_c:
                off_idx = s_c
            if flags[off_idx] & 1:
                continue
            ox, oy = coords[off_idx]
            new_x = ox + (tx - ox) * 0.25
            new_y = oy + (ty - oy) * 0.25
            coords[off_idx] = (int(round(new_x)), int(round(new_y)))
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_self(glyph, glyf, upm: int) -> bool:
    """Frame/grid cleanup for 自. v0.4.12: REVERSED counter scaling.

    Tang flagged 自 as ugly — stems 11% each side vs Tsanger 17%. Diagnosis:
    triple-stack of (FRAME_RISK 1.065 counter expand) + (CORE_V2 0.988 stem
    narrow) + (this function's previous 1.012 inner expand) over-narrowed
    the vertical stems. v0.4.12 demotes 自 from FRAME_RISK and reverses
    inner scale here to actively SHRINK counters by 0.93× horizontally,
    bringing stems back toward Tsanger proportions.
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
    touched = False

    for c in _contour_info(glyph, coords):
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
        c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))

        if signed > 0:
            # Inner counter — actively shrink horizontally to thicken stems.
            _scale_contour(coords, c, 0.93, 1.00)
            touched = True
            continue

        # Skip the previous outer right-containment which made stems thinner.
        # Rationale: now that FRAME_RISK is off and counters are shrunk, the
        # outer hull doesn't need additional narrowing — let it sit at LXGW
        # native width.
        continue

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_ping(glyph, glyf, upm: int) -> bool:
    """v0.4.12 Tang hand-craft for 平.

    Defect: the two upper dots (丶 of 平) read as tall vertical tabs instead
    of wedge-shaped kai dots. Measurements: c1 rel 25%x36%, c2 rel 22%x29%
    — significantly taller than wide. Tsanger has them at 25%x26% / 27%x27%
    (roughly square). The dot pass's DOT_LONG_AXIS=0.92 / DOT_SHORT_AXIS=0.55
    wasn't catching these because their orientation didn't match the
    long-axis detection threshold.

    Fix: identify the two small outer contours in the upper half (cy > 60%
    of glyph_h, w < 30% of glyph_w) and compress them vertically (0.78×)
    while widening horizontally (1.05×) around their own centroids.
    Restores wedge-dot proportion.
    """
    coords = glyph.coordinates
    if glyph.numberOfContours < 3:
        return False
    ends = glyph.endPtsOfContours
    box = _glyph_box(coords)
    if box is None:
        return False
    _, _, y_min, _, glyph_w, glyph_h, _, _ = box

    touched = False
    s = 0
    for ci, e in enumerate(ends):
        signed = _contour_signed_area(coords, s, e)
        if signed >= 0:  # only outer dots
            s = e + 1
            continue
        xs = [coords[i][0] for i in range(s, e + 1)]
        ys = [coords[i][1] for i in range(s, e + 1)]
        cw = max(xs) - min(xs)
        ch = max(ys) - min(ys)
        ccx = (max(xs) + min(xs)) / 2.0
        ccy = (max(ys) + min(ys)) / 2.0
        ccy_n = (ccy - y_min) / max(1, glyph_h)
        # Upper-half small outer contour with too-tall aspect
        if (cw < glyph_w * 0.30 and ch < glyph_h * 0.45
                and ccy_n > 0.60 and ch > cw * 0.95):
            for i in range(s, e + 1):
                x, y = coords[i]
                new_x = ccx + (x - ccx) * 1.05
                new_y = ccy + (y - ccy) * 0.78
                coords[i] = (int(round(new_x)), int(round(new_y)))
            touched = True
        s = e + 1

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_gang(glyph, glyf, upm: int) -> bool:
    """v0.4.12 Tang hand-craft for 刚 (and 刂-radical sibling chars).

    Defect: 刂 (rightmost contour) reads chunky/wide. Measurement: 刂 c3
    rel_w 31% of glyph_w. Tsanger 刂 is 23% of glyph_w. The hook tail
    extends ~8% too far right.

    Fix: identify the rightmost outer contour (cx > 70%, full glyph height)
    and contract it horizontally by 0.85× around its own centroid.
    """
    coords = glyph.coordinates
    if glyph.numberOfContours < 2:
        return False
    ends = glyph.endPtsOfContours
    box = _glyph_box(coords)
    if box is None:
        return False
    x_min, _, _, _, glyph_w, glyph_h, _, _ = box

    # Find the rightmost outer contour spanning full height (the 刂)
    s = 0
    target_ci = -1
    target_bounds = None
    for ci, e in enumerate(ends):
        signed = _contour_signed_area(coords, s, e)
        if signed >= 0:
            s = e + 1
            continue
        xs = [coords[i][0] for i in range(s, e + 1)]
        ys = [coords[i][1] for i in range(s, e + 1)]
        cw = max(xs) - min(xs)
        ch = max(ys) - min(ys)
        ccx = (max(xs) + min(xs)) / 2.0
        ccx_n = (ccx - x_min) / max(1, glyph_w)
        # Full-height tall narrow rightmost outer (the 刂)
        if (ccx_n > 0.70 and ch > glyph_h * 0.85
                and cw < glyph_w * 0.40):
            target_ci = ci
            target_bounds = (s, e, ccx)
        s = e + 1

    if target_ci < 0:
        return False

    s_t, e_t, ccx = target_bounds
    for i in range(s_t, e_t + 1):
        x, y = coords[i]
        new_x = ccx + (x - ccx) * 0.85
        coords[i] = (int(round(new_x)), y)
    glyph.recalcBounds(glyf)
    return True


def _refine_problem_jin(glyph, glyf, upm: int) -> bool:
    """晋: lower 日 too wide/heavy (bolden 0.85 scale), upper 亚 horizontals heavy.

    Lower 日 outer: 0.930x/0.965y to strongly thin the frame walls.
    Lower 日 inner counters: 1.025x/1.015y (small delta over upstream 1.040x).
    Upper 亚 outer: mild 0.970x/0.980y to thin the heavy horizontals.
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 4:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    contours = _contour_info(glyph, coords)
    touched = False

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        cy_n = (float(c["cy"]) - y_min) / max(1.0, glyph_h)
        cw = float(c["xmax"]) - float(c["xmin"])
        ch = float(c["ymax"]) - float(c["ymin"])
        cw_ratio = cw / glyph_w if glyph_w else 0
        ch_ratio = ch / glyph_h if glyph_h else 0
        if signed <= 0 and cy_n < 0.45 and 0.35 < cw_ratio < 0.75 and ch_ratio > 0.25:
            # Lower 日 outer frame: widen toward the reference. The original
            # v0.4.12 contraction (0.930/0.965, anti-bolden) left the 日
            # 23px narrower than W04's broad base at 300px; Tang re-flagged.
            _scale_contour(coords, c, 1.060, 1.010)
            touched = True
        elif signed > 0 and cy_n < 0.45:
            # Lower 日 inner counters: open ahead of the outer widening so
            # stroke weight stays level while the frame grows.
            _scale_contour(coords, c, 1.095, 1.020)
            touched = True
        elif signed <= 0 and cy_n >= 0.45 and cw_ratio > 0.50:
            # Upper 亚 outer: mild thinning of heavy horizontals
            _scale_contour(coords, c, 0.970, 0.980)
            touched = True

    # v0.4.12: the right short stroke of the upper 亚 is a fat slanted wedge
    # (LXGW residue); W04's is a clean light stroke. Slim the wedge region
    # (right of the middle counter, between the long横 and the top横) around
    # its own centroid.
    region = [
        i
        for i in range(len(coords))
        if 0.56 < (coords[i][0] - x_min) / max(1.0, glyph_w) < 0.78
        and 0.57 < (coords[i][1] - y_min) / max(1.0, glyph_h) < 0.90
    ]
    if len(region) >= 4:
        rcx = sum(coords[i][0] for i in region) / len(region)
        rcy = sum(coords[i][1] for i in region) / len(region)
        for i in region:
            x, y = coords[i]
            coords[i] = (
                int(round(rcx + (x - rcx) * 0.88)),
                int(round(rcy + (y - rcy) * 0.94)),
            )
        touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_yong(glyph, glyf, upm: int) -> bool:
    """用: the centre vertical's bottom hook reads as a club-foot blob.

    Geometry (v0.4.12 Tang screenshot): the stem's flat bottom cap sits
    offset to the right at the lowest y, with a vestigial leftward sweep.
    W04 ends the centre stroke in a slender taper with a tiny tick. Fix:
    lift the sub-baseline hook region toward the stem end and narrow it
    around the stem axis, turning the blob into a short taper.
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 3:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    region = [
        i
        for i in range(len(coords))
        if 0.46 < (coords[i][0] - x_min) / max(1.0, glyph_w) < 0.64
        and (coords[i][1] - y_min) / max(1.0, glyph_h) <= 0.12
    ]
    if len(region) < 4:
        return False
    region_top = y_min + 0.12 * glyph_h
    mid_x = x_min + 0.555 * glyph_w
    for i in region:
        x, y = coords[i]
        coords[i] = (
            int(round(mid_x + (x - mid_x) * 0.80)),
            int(round(y + (region_top - y) * 0.45)),
        )
    glyph.recalcBounds(glyf)
    return True


def _refine_problem_shu(glyph, glyf, upm: int) -> bool:
    """书: 3 contours → full bolden, every stroke disproportionately heavy.

    v0.4.12 ugly-queue (vs W04 300px): dens +0.035, face −15px. Notch
    outer contract one step further and open the fold counter so the body
    reads lighter without collapsing the 横折钩 silhouette.
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    contours = _contour_info(glyph, coords)
    touched = False

    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        cw = float(c["xmax"]) - float(c["xmin"])
        cw_ratio = cw / glyph_w if glyph_w else 0

        if signed <= 0 and cw_ratio > 0.80:
            # Outer hull: keep x gentler (face already −16px) so dens cut
            # comes mostly from y-contract + dense-ink vertical thin.
            _scale_contour(coords, c, 0.955, 0.948)
            touched = True
        elif signed <= 0 and cw_ratio <= 0.80:
            # Dot contour: match the thinner body
            _scale_contour(coords, c, 0.955, 0.955)
            touched = True
        elif signed > 0:
            # Inner counter: open to compensate outer contraction
            _scale_contour(coords, c, 1.045, 1.032)
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_feng(glyph, glyf, upm: int) -> bool:
    """风: 2 contours (both outer!), full bolden → enclosure very heavy.

    v0.4.12 ugly-queue: dens +0.044 vs W04. Stronger outer hull contract
    plus proportional 乂 thin; dense-ink relief (tier 1.0) also thins the
    long vertical walls so this pass focuses on whole-contour mass.
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    contours = _contour_info(glyph, coords)
    touched = False

    outers = []
    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed <= 0:
            outers.append((abs(float(c["area"])), c))

    outers.sort(key=lambda x: -x[0])
    for idx, (area, c) in enumerate(outers):
        if idx == 0:
            # Outer 几 hull: dens cut without collapsing face (r2 0.925 over-narrowed)
            _scale_contour(coords, c, 0.945, 0.955)
            touched = True
        else:
            # Inner 乂 strokes: proportional thinning
            _scale_contour(coords, c, 0.962, 0.968)
            touched = True

    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_tian(glyph, glyf, upm: int) -> bool:
    """田: frame-risk stack crushed face height vs W04 (Δh −21px at 300px).

    Restore vertical extent on the outer hull and open the four quadrant
    counters so the print-kai 田 is taller and less ink-clogged, without
    undoing the upright wall / foot-tuck work.
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    contours = _contour_info(glyph, coords)
    touched = False
    outers = []
    inners = []
    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        if signed <= 0:
            outers.append((abs(float(c["area"])), c))
        else:
            inners.append(c)
    if not outers:
        return False
    outers.sort(key=lambda x: -x[0])
    # Outer frame: restore height, keep width near identity
    _scale_contour(coords, outers[0][1], 1.008, 1.055)
    touched = True
    for c in inners:
        _scale_contour(coords, c, 1.030, 1.040)
        touched = True
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_zi(glyph, glyf, upm: int) -> bool:
    """字: roof + 子, dens +0.048 / over_w05; hook root reads heavy at display.

    Lightly contain the outer roof hull and open the 子 counter so dense
    relief on verticals has room to read; do not touch the hook tip path
    (owned by refine_hooks_final + tail taper).
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    _x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
    contours = _contour_info(glyph, coords)
    touched = False
    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        cy_t = (float(c["cy"]) - y_min) / max(1.0, glyph_h)
        if signed <= 0 and cy_t > 0.55:
            # Upper roof only — r2 lower-body contain over-narrowed face −20px
            _scale_contour(coords, c, 0.972, 0.968)
            touched = True
        elif signed > 0:
            _scale_contour(coords, c, 1.040, 1.028)
            touched = True
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_qing(glyph, glyf, upm: int) -> bool:
    """清: blunt the long mid-height right needle on 青's free 横 tip.

    Tang circled a blade-like exit at mid-right. Soft free-end blunt is not
    enough when the taper runs >0.1em; clamp the last segment's x and expand
    y about the tip midline so the cut reads short and weighty like W04.
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 2:
        return False
    x_min, x_max, y_min, y_max, glyph_w, glyph_h, _cx, _cy = box
    if glyph_w <= 0 or glyph_h <= 0:
        return False
    flags = glyph.flags
    ends = glyph.endPtsOfContours
    # Find rightmost on-curve in mid band (青 横 tip, not 氵 bottom)
    tip_i = None
    tip_x = -1e18
    start = 0
    tip_start = tip_end = 0
    for end in ends:
        if _contour_signed_area(coords, start, end) >= 0:
            start = end + 1
            continue
        for i in range(start, end + 1):
            if not (flags[i] & 1):
                continue
            x, y = coords[i]
            yn = (y - y_min) / glyph_h
            if yn < 0.42 or yn > 0.78:
                continue
            if x > tip_x:
                tip_x = x
                tip_i = i
                tip_start, tip_end = start, end
        start = end + 1
    if tip_i is None:
        return False
    tx, ty = coords[tip_i]
    # Only act if this tip is near the glyph right edge (free end, not join)
    if (tx - x_min) / glyph_w < 0.82:
        return False
    zone = 0.11 * upm
    pull = 0.055 * upm  # ~half the residual blade length
    cut_x = tx - pull
    plump = 0.022 * upm
    touched = False
    for i in range(tip_start, tip_end + 1):
        x, y = coords[i]
        if x < cut_x - 0.02 * upm:
            continue
        # How deep into the needle past the cut
        if x <= cut_x:
            # near cut on body side: light plump only
            t = max(0.0, 1.0 - (cut_x - x) / (0.04 * upm))
            if t <= 0:
                continue
            dy = plump * 0.4 * t * (1.0 if y >= ty else -1.0)
            coords[i] = (x, int(round(y + dy)))
            touched = True
            continue
        # past cut: clamp x and expand y
        t = min(1.0, (x - cut_x) / max(tx - cut_x, 1.0))
        new_x = cut_x + (x - cut_x) * 0.12  # almost flat
        # expand away from tip y
        sign = 1.0 if y >= ty else -1.0
        if abs(y - ty) < 2:
            sign = 1.0 if (i % 2 == 0) else -1.0
        new_y = ty + (y - ty) * (1.0 - 0.35 * t) + sign * plump * (0.55 + 0.45 * t)
        coords[i] = (int(round(new_x)), int(round(new_y)))
        touched = True
    if touched:
        glyph.recalcBounds(glyf)
    return touched


def _refine_problem_ying(glyph, glyf, upm: int) -> bool:
    """赢: dens +0.05 / over_w05; multi-component stack stays ink-clogged.

    Open every inner counter harder and lightly contain secondary outer
    components so dense-ink vertical relief has room to read at title sizes.
    """
    coords = glyph.coordinates
    box = _glyph_box(coords)
    if box is None or glyph.numberOfContours < 3:
        return False
    contours = _contour_info(glyph, coords)
    max_area = max(float(c["area"]) for c in contours)
    touched = False
    for c in contours:
        signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
        area = float(c["area"])
        if signed > 0:
            _scale_contour(coords, c, 1.070, 1.045)
            touched = True
        elif area < max_area * 0.55:
            # Secondary outer components (贝/月/凡-like pieces)
            _scale_contour(coords, c, 0.970, 0.972)
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
        "答": _refine_problem_answer,
        **{ch: _refine_homepage_p0_grid for ch in HOMEPAGE_P0_GRID_GLYPHS},
        **{ch: _refine_homepage_p0_hook for ch in HOMEPAGE_P0_HOOK_GLYPHS},
        **{ch: _refine_homepage_p0_component for ch in HOMEPAGE_P0_COMPONENT_GLYPHS},
        **{ch: _refine_homepage_p0_grid for ch in HOMEPAGE_P1_GRID_GLYPHS},
        **{ch: _refine_homepage_p0_hook for ch in HOMEPAGE_P1_HOOK_GLYPHS},
        **{ch: _refine_homepage_p0_component for ch in HOMEPAGE_P1_COMPONENT_GLYPHS},
        **{ch: _refine_homepage_p0_component for ch in HOMEPAGE_P1_RADICAL_GLYPHS},
        **{ch: _refine_homepage_p0_component for ch in HOMEPAGE_P1_ROOF_GLYPHS},
        **{ch: _refine_homepage_p2_source_risk for ch in HOMEPAGE_P2_SOURCE_RISK_GLYPHS},
        **{ch: _refine_homepage_p4_residual for ch in HOMEPAGE_P4_RESIDUAL_RISK_GLYPHS},
        **{ch: _refine_homepage_p3_structure for ch in HOMEPAGE_P3_STRUCTURE_GLYPHS},
        **{ch: _refine_homepage_p5_stubborn for ch in HOMEPAGE_P5_STUBBORN_RISK_GLYPHS},
        # `去` is a single-contour residual where P4/P5 topology pushes are too blunt.
        # Keep its dedicated posture correction last so broader queues cannot override it.
        "去": _refine_problem_qu,
        "斗": _refine_problem_dou,
        "重": _refine_problem_chong,
        "种": _refine_problem_seed_zhong,
        "荒": _refine_problem_huang,
        "自": _refine_problem_self,
        "平": _refine_problem_ping,
        "刚": _refine_problem_gang,
        "晋": _refine_problem_jin,
        "用": _refine_problem_yong,
        "书": _refine_problem_shu,
        "风": _refine_problem_feng,
        "田": _refine_problem_tian,
        "字": _refine_problem_zi,
        "赢": _refine_problem_ying,
        # 清 tip hard-cut removed: Tang regression 更丑了
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


def luo_homepage_p6_left_right(font: TTFont) -> None:
    """v0.4.10 W04 follow-up: add hierarchy to left/right risk glyphs.

    This is deliberately a final, named queue rather than a broad topology
    pass. The remaining high-LXGW homepage cluster is mostly left/right
    composition (`抽/独/种/技/虾/便/雅/柯/...`): the source posture keeps the
    side component too even with the body, and the right-bottom tail stays
    long. Apply a small shared correction after the existing P4/P5 refiners:
    contain the left side, open eligible counters, and tuck the lower-right
    tail. It should not become a GB2312-wide rule until this queue is stable.
    """
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    h_min = WEB_PRESENCE_H_MIN_EM * upm
    touched: list[str] = []

    for char in dict.fromkeys(HOMEPAGE_P6_LEFT_RIGHT_GLYPHS):
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours < 2:
            continue
        coords = glyph.coordinates
        box = _glyph_box(coords)
        if box is None:
            continue
        x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
        glyph_area = glyph_w * glyph_h
        if glyph_area <= 0:
            continue
        contours = _contour_info(glyph, coords)
        outers = [
            c for c in contours
            if _contour_signed_area(coords, int(c["start"]), int(c["end"])) <= 0
        ]
        if len(outers) < 2:
            continue
        largest_outer = max(outers, key=lambda c: float(c["area"]))
        glyph_touched = False

        for c in contours:
            signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
            c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
            c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
            c_area = float(c["area"])
            area_ratio = c_area / glyph_area
            ccx = float(c["cx"])

            if signed > 0:
                if 0.004 <= area_ratio <= 0.22:
                    _scale_contour(coords, c, 1.055, 1.030)
                    glyph_touched = True
                continue

            if c is largest_outer or area_ratio < 0.018:
                continue
            if ccx < cx - glyph_w * 0.10 and area_ratio < 0.46:
                sx = _presence_guarded_scale(0.976, c_w, h_min)
                sy = _presence_guarded_scale(0.990, c_h, h_min)
                _scale_contour(coords, c, sx, sy, 0.004 * upm, 0.0)
                glyph_touched = True
            elif ccx > cx + glyph_w * 0.14 and area_ratio < 0.42:
                sx = _presence_guarded_scale(0.988, c_w, h_min)
                sy = _presence_guarded_scale(0.994, c_h, h_min)
                _scale_contour(coords, c, sx, sy, -0.002 * upm, 0.0)
                glyph_touched = True

        # Tuck lower-right overhangs after component scaling. This is the
        # first-glance W04 cue on high-risk left/right glyphs: shorter, cleaner
        # right-bottom exits without changing advance width or global weight.
        for c in outers:
            if float(c["area"]) < glyph_area * 0.08:
                continue
            for i in range(int(c["start"]), int(c["end"]) + 1):
                x, y = coords[i]
                xn = (x - x_min) / max(1.0, glyph_w)
                yn = (y - y_min) / max(1.0, glyph_h)
                if xn <= 0.58 or yn >= 0.36:
                    continue
                t = (xn - 0.58) / 0.42 * (0.36 - yn) / 0.36
                new_x = cx + (x - cx) * (1.0 - 0.010 * t)
                new_y = y + 0.0035 * upm * t
                new_xy = (int(round(new_x)), int(round(new_y)))
                if new_xy != tuple(coords[i]):
                    coords[i] = new_xy
                    glyph_touched = True

        if glyph_touched:
            glyph.recalcBounds(glyf)
            touched.append(char)

    if touched:
        print(f"[luo] P6 left-right W04 polish: {''.join(touched)}")


def luo_curve_tail_polish(font: TTFont) -> None:
    """Final screenshot-risk curve cleanup for 风/气/成 only.

    Existing hook final + hook-tail cap already protect the whole font. These
    three glyphs still show a first-glance fishhook/chunky lower-right curve
    at display size, so keep the fix in a named queue instead of raising any
    global HOOK/TURN parameter.
    """
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    touched: list[str] = []

    for char in LUO_CURVE_TAIL_POLISH_CHARS:
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
        x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
        glyph_area = glyph_w * glyph_h
        glyph_touched = False

        for c in _contour_info(glyph, coords):
            signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
            if signed > 0 or float(c["area"]) < glyph_area * 0.08:
                continue
            for i in range(int(c["start"]), int(c["end"]) + 1):
                x, y = coords[i]
                xn = (x - x_min) / max(1.0, glyph_w)
                yn = (y - y_min) / max(1.0, glyph_h)
                new_x = float(x)
                new_y = float(y)

                if xn > 0.58 and yn < 0.38:
                    t = (xn - 0.58) / 0.42 * (0.38 - yn) / 0.38
                    new_x = cx + (new_x - cx) * (1.0 - 0.030 * t)
                    new_y += 0.007 * upm * t
                if xn > 0.70 and 0.22 <= yn <= 0.54:
                    t = (xn - 0.70) / 0.30 * (1.0 - abs(yn - 0.38) / 0.16)
                    if t > 0:
                        new_x = cx + (new_x - cx) * (1.0 - 0.010 * t)

                new_xy = (int(round(new_x)), int(round(new_y)))
                if new_xy != tuple(coords[i]):
                    coords[i] = new_xy
                    glyph_touched = True

        if glyph_touched:
            glyph.recalcBounds(glyf)
            touched.append(char)

    if touched:
        print(f"[luo] curve-tail W04 polish: {''.join(touched)}")


def luo_horiz_cap_flatten(font: TTFont) -> None:
    """v0.4.11: chord-line clamp for residual horizontal cap arc.

    The Tang-reported '正 / 晋 / 章 / 书 / 觉 / 风 中横右端 lump' is caused by
    bolden raising the leftmost top-cap on-curve (~+28u in 正), while
    straighten only partially flattens off-curve cap arcs (perp-ratio
    threshold of 0.20 protects controls 9-10% off chord). Net: cap apex
    sits a few units above leftmost top-cap on-curve, reading at heading
    sizes (≥200px) as a small visible knob/notch on most chars with long
    horizontals.

    For each outer CCW contour (signed_area < 0), walk consecutive
    on-curve pairs (P_a, P_b). When the chord PaPb is:
      - long (>= LUO_HORIZ_CAP_FLATTEN_MIN_RATIO * glyph_max),
      - near-horizontal (angle <= LUO_HORIZ_CAP_FLATTEN_ANGLE_DEG),
      - left-to-right (dx > 0; for CCW outer this is a top-edge segment),
    every off-curve point STRICTLY BETWEEN P_a and P_b is clamped to the
    linearly-interpolated chord-line y at its x position when its actual
    y exceeds that chord-line y. The chord-line clamp (vs clamping to
    P_a.y) is critical for chords that tilt up (e.g., 正's bottom 横画
    with P_b higher than P_a): clamping to P_a.y would create an
    inverted bump at P_b. Chord-line clamping never produces such an
    inverted artifact.

    The clamping eliminates the upward bulge on cap top edges while
    leaving the angular drop into the right cap (P_b.y < P_a.y by
    design) untouched. Result: flat top → angular cap drop, matching
    Tsanger Print Kai's print-kai cap geometry.

    Skips:
      - inner contours (signed_area >= 0): cap_flatten only handles
        outer top edges. Inner counter geometry is owned by other passes.
      - characters in STRAIGHTEN_SKIP_CHARS (心字底/忄旁/走之底): they
        have dedicated curve geometry that should not be flattened.
      - characters in LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS (月): point-locked
        to v0.3 baseline by refine_visible_problem_glyphs upstream.
    """
    glyf = font["glyf"]
    cap_max_lift = LUO_HORIZ_CAP_FLATTEN_MAX_LIFT_EM * font["head"].unitsPerEm
    rcmap = _build_reverse_cmap(font)

    seg_count = 0
    glyph_count = 0
    skip_chars = set(STRAIGHTEN_SKIP_CHARS) | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF):
            continue
        char = chr(cp)
        if char in skip_chars:
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
        min_chord_len = LUO_HORIZ_CAP_FLATTEN_MIN_RATIO * glyph_max
        glyph_touched = False

        start = 0
        for end in ends:
            n = end - start + 1
            if n < 8:
                start = end + 1
                continue
            # Outer CCW contour only (signed_area < 0)
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
                if angle_off_h > LUO_HORIZ_CAP_FLATTEN_ANGLE_DEG:
                    continue
                if dx <= 0:
                    continue

                # Reference line: the stroke's own top edge, not the chord.
                # P_b is usually the cap TIP at mid stroke height, so the
                # chord slopes down into it and clamping to it shaved the
                # round cap into a needle (来/清 long bars). Fit the edge
                # slope from off-curves in the first 60% of the span and
                # never go below the chord, so lumps above the edge still
                # clamp while the cap's own downward curve is untouched.
                edge_slopes = []
                pos = ia + 1
                while True:
                    if pos > end:
                        pos = start
                    if pos == ib:
                        break
                    px, py = coords[pos]
                    if (flags[pos] & 1) == 0 and 0 < px - ax < 0.6 * dx:
                        edge_slopes.append((py - ay) / (px - ax))
                    pos += 1
                edge_slope = sorted(edge_slopes)[len(edge_slopes) // 2] if edge_slopes else 0.0
                edge_slope = max(-math.tan(math.radians(LUO_HORIZ_CAP_FLATTEN_ANGLE_DEG)),
                                 min(math.tan(math.radians(LUO_HORIZ_CAP_FLATTEN_ANGLE_DEG)), edge_slope))

                # Round 9: all or nothing per chord. When part of a cap rises
                # past MAX_LIFT (real shape), clamping only the lower part left
                # an isolated spike (量's middle bar right end).
                tall = False
                pos = ia + 1
                while True:
                    if pos > end:
                        pos = start
                    if pos == ib:
                        break
                    if (flags[pos] & 1) == 0:
                        qx, qy = coords[pos]
                        ref_y = max(ay + dy * ((qx - ax) / dx), ay + edge_slope * (qx - ax))
                        if qy > ref_y + cap_max_lift:
                            tall = True
                            break
                    pos += 1
                if tall:
                    continue

                pos = ia + 1
                while True:
                    if pos > end:
                        pos = start
                    if pos == ib:
                        break
                    if (flags[pos] & 1) == 0:  # off-curve
                        px, py = coords[pos]
                        # Chord line at x = px
                        t = (px - ax) / dx
                        chord_y = max(ay + dy * t, ay + edge_slope * (px - ax))
                        # A cap lump is a few units; a rise past MAX_LIFT
                        # is real shape (贫's round dot head), not a lump.
                        if chord_y + 0.5 < py <= chord_y + cap_max_lift:
                            coords[pos] = (px, int(round(chord_y)))
                            seg_count += 1
                            glyph_touched = True
                    pos += 1

            start = end + 1

        if glyph_touched:
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] horiz-cap flatten: {seg_count} cap off-curves clamped across "
        f"{glyph_count} glyphs (min_ratio={LUO_HORIZ_CAP_FLATTEN_MIN_RATIO}, "
        f"angle<={LUO_HORIZ_CAP_FLATTEN_ANGLE_DEG}°)"
    )


def luo_frame_upright(font: TTFont) -> None:
    """v0.4.12: upright the tilted walls of curated frame glyphs.

    See the LUO_FRAME_UPRIGHT_* constant block for design rationale. Runs
    only on IDENTITY_CORE_FRAME_CHARS (minus the frozen 月).
    """
    if LUO_FRAME_UPRIGHT_BLEND <= 0:
        print("[luo] frame upright: skipped (blend=0)")
        return
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    chars = [c for c in IDENTITY_CORE_FRAME_CHARS + LUO_FRAME_UPRIGHT_EXTRA_CHARS + LUO_FRAME_UPRIGHT_KOU_CHARS if c not in LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS]

    chord_count = 0
    touched_chars: list[str] = []

    for char in chars:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue

        coords = list(glyph.coordinates)
        flags = glyph.flags
        ends = glyph.endPtsOfContours
        all_ys = [c[1] for c in coords]
        glyph_h = max(all_ys) - min(all_ys)
        if glyph_h <= 0:
            continue
        # Compound walls (晋's 日 is ~half the glyph) are shorter relative
        # to the glyph than a standalone frame's.
        ratio = 0.14 if char in LUO_FRAME_UPRIGHT_KOU_CHARS else (0.25 if char in LUO_FRAME_UPRIGHT_EXTRA_CHARS else LUO_FRAME_UPRIGHT_MIN_LEN_RATIO)
        min_len = ratio * glyph_h
        moves: dict[int, float] = {}

        start = 0
        for end in ends:
            n = end - start + 1
            if n < 4:
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
                if abs(dy) < min_len or dy == 0:
                    continue
                if abs(dx) / abs(dy) > LUO_FRAME_UPRIGHT_MAX_SLOPE:
                    continue
                mid_x = (ax + bx) / 2.0

                idx = ia
                while True:
                    px, py = coords[idx]
                    t = (py - ay) / dy
                    t = max(0.0, min(1.0, t))
                    chord_x = ax + dx * t
                    shift = LUO_FRAME_UPRIGHT_BLEND * (mid_x - chord_x)
                    prev = moves.get(idx)
                    if prev is None or abs(shift) > abs(prev):
                        moves[idx] = shift
                    if idx == ib:
                        break
                    idx += 1
                    if idx > end:
                        idx = start
                chord_count += 1

            start = end + 1

        if moves:
            for idx, shift in moves.items():
                x, y = coords[idx]
                coords[idx] = (int(round(x + shift)), y)
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            touched_chars.append(char)

    print(
        f"[luo] frame upright: {chord_count} wall chords across "
        f"{''.join(touched_chars) or '(none)'} (blend={LUO_FRAME_UPRIGHT_BLEND})"
    )


def luo_frame_foot_tuck(font: TTFont) -> None:
    """v0.4.12: tuck the LXGW brush-exit foot under closed frame bottoms.

    See the LUO_FRAME_FOOT_* constant block for design rationale and gates.
    """
    if LUO_FRAME_FOOT_KEEP_EM >= LUO_FRAME_FOOT_MAX_DEPTH_EM:
        print("[luo] frame foot tuck: skipped (keep >= max depth)")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    keep = LUO_FRAME_FOOT_KEEP_EM * upm
    max_depth = LUO_FRAME_FOOT_MAX_DEPTH_EM * upm
    x_extend = LUO_FRAME_FOOT_X_EXTEND_EM * upm
    skip_chars = set(STRAIGHTEN_SKIP_CHARS) | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)

    tuck_count = 0
    glyph_count = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF):
            continue
        char = chr(cp)
        if char in skip_chars:
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
        glyph_ymin = min(all_ys)
        if glyph_w <= 0 or glyph_h <= 0:
            continue
        min_chord_len = LUO_FRAME_FOOT_MIN_RATIO * max(glyph_w, glyph_h)
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
                if math.degrees(math.atan2(abs(dy), abs(dx))) > 10.0:
                    continue
                if dx >= 0:  # bottom edge on a CCW outer runs right-to-left
                    continue
                chord_floor = min(ay, by)
                # The chord must sit near the glyph bottom: anything in the
                # glyph descending further than max_depth below it means the
                # chord is a mid-glyph bar with real structure below (于/寺
                # style) and must be left alone.
                if chord_floor - glyph_ymin > max_depth:
                    continue

                x_lo = min(ax, bx) - x_extend
                x_hi = max(ax, bx) + x_extend
                for i in range(start, end + 1):
                    px, py = coords[i]
                    if px < x_lo or px > x_hi:
                        continue
                    t = (px - ax) / dx
                    t = max(0.0, min(1.0, t))
                    floor_y = (ay + dy * t) - keep
                    if py < floor_y:
                        coords[i] = (px, int(round(floor_y)))
                        tuck_count += 1
                        glyph_touched = True

            start = end + 1

        if glyph_touched:
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] frame foot tuck: {tuck_count} points across {glyph_count} glyphs "
        f"(keep={LUO_FRAME_FOOT_KEEP_EM}em, max_depth={LUO_FRAME_FOOT_MAX_DEPTH_EM}em)"
    )


def luo_horiz_kink_join(font: TTFont) -> None:
    """v0.4.12: remove the shallow V that straighten_strokes leaves where two
    near-horizontal spans meet at a mid on-curve (see constant block)."""
    if LUO_KINK_JOIN_MAX_TURN_DEG <= 0:
        print("[luo] horiz kink join: skipped")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    max_sag = LUO_KINK_JOIN_MAX_SAG_EM * upm
    skip_chars = set(STRAIGHTEN_SKIP_CHARS) | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)
    kink_count = 0
    glyph_count = 0
    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF) or chr(cp) in skip_chars:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        coords = list(glyph.coordinates)
        flags = glyph.flags
        ends = glyph.endPtsOfContours
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        glyph_max = max(max(xs) - min(xs), max(ys) - min(ys))
        if glyph_max <= 0:
            continue
        min_len = max(STRAIGHTEN_MIN_LEN_ABS, STRAIGHTEN_MIN_LEN_RATIO * glyph_max)
        touched = False
        start = 0
        for end in ends:
            n = end - start + 1
            oc = [start + j for j in range(n) if flags[start + j] & 1]
            m_oc = len(oc)
            if n < 6 or m_oc < 3:
                start = end + 1
                continue

            def _between(i0, i1):
                if i1 > i0:
                    return list(range(i0 + 1, i1))
                return list(range(i0 + 1, end + 1)) + list(range(start, i1))

            for k in range(m_oc):
                ia, im, ib = oc[k - 1], oc[k], oc[(k + 1) % m_oc]
                if len({ia, im, ib}) < 3:
                    continue
                ax, ay = coords[ia]
                mx, my = coords[im]
                bx, by = coords[ib]
                d1 = (mx - ax, my - ay)
                d2 = (bx - mx, by - my)
                l1, l2 = math.hypot(*d1), math.hypot(*d2)
                if l1 < min_len or l2 < min_len:
                    continue
                # Both spans run the same horizontal direction.
                if d1[0] * d2[0] <= 0:
                    continue
                a1 = math.degrees(math.atan2(abs(d1[1]), abs(d1[0])))
                a2 = math.degrees(math.atan2(abs(d2[1]), abs(d2[0])))
                if a1 > LUO_KINK_JOIN_ANGLE_DEG or a2 > LUO_KINK_JOIN_ANGLE_DEG:
                    continue
                turn = abs(math.degrees(math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1])))
                if turn > LUO_KINK_JOIN_MAX_TURN_DEG:
                    continue
                # A smooth on-curve (its neighbouring points leave it on one
                # tangent line) is a natural curve, not a kink; lifting it
                # turned 己's gently sagging inner bottom into a tent.
                pvx, pvy = coords[start + (im - start - 1) % n]
                nvx, nvy = coords[start + (im - start + 1) % n]
                u1 = (mx - pvx, my - pvy)
                u2 = (nvx - mx, nvy - my)
                if (u1[0] or u1[1]) and (u2[0] or u2[1]):
                    local_turn = abs(math.degrees(math.atan2(u1[0] * u2[1] - u1[1] * u2[0], u1[0] * u2[0] + u1[1] * u2[1])))
                    if local_turn < LUO_KINK_JOIN_MIN_LOCAL_TURN_DEG:
                        continue
                t = (mx - ax) / (bx - ax)
                chord_y = ay + (by - ay) * t
                sag = chord_y - my  # > 0: middle point sits below the chord
                if sag < LUO_KINK_JOIN_MIN_SAG or sag > max_sag:
                    continue
                coords[im] = (mx, int(round(chord_y)))
                for idx, (p0, p1) in (
                    [(i, (ax, mx)) for i in _between(ia, im)]
                    + [(i, (mx, bx)) for i in _between(im, ib)]
                ):
                    px, py = coords[idx]
                    if p1 == p0:
                        continue
                    u = (px - p0) / (p1 - p0)
                    u = max(0.0, min(1.0, u))
                    w = u if p0 == ax else 1.0 - u
                    coords[idx] = (px, int(round(py + sag * w)))
                kink_count += 1
                touched = True
            start = end + 1
        if touched:
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1
    print(f"[luo] horiz kink join: {kink_count} kinks across {glyph_count} glyphs (max_turn={LUO_KINK_JOIN_MAX_TURN_DEG}°)")


def luo_smooth_shallow_corners(font: TTFont) -> None:
    """v0.4.12: make near-horizontal on-curves between two handles smooth
    (see constant block)."""
    if LUO_SMOOTH_CORNER_MAX_TURN_DEG <= 0:
        print("[luo] smooth shallow corners: skipped")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    max_move = LUO_SMOOTH_CORNER_MAX_MOVE_EM * font["head"].unitsPerEm
    skip_chars = set(STRAIGHTEN_SKIP_CHARS) | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)
    count = 0
    glyph_count = 0
    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF) or chr(cp) in skip_chars:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        coords = list(glyph.coordinates)
        flags = glyph.flags
        touched = False
        start = 0
        for end in glyph.endPtsOfContours:
            n = end - start + 1
            for j in range(n):
                i = start + j
                ip = start + (j - 1) % n
                inx = start + (j + 1) % n
                if not (flags[i] & 1) or (flags[ip] & 1) or (flags[inx] & 1):
                    continue
                (ax, ay), (mx, my), (bx, by) = coords[ip], coords[i], coords[inx]
                d1 = (mx - ax, my - ay)
                d2 = (bx - mx, by - my)
                l1, l2 = math.hypot(*d1), math.hypot(*d2)
                if l1 < 8 or l2 < 8 or d1[0] * d2[0] <= 0:
                    continue
                if (
                    math.degrees(math.atan2(abs(d1[1]), abs(d1[0]))) > LUO_SMOOTH_CORNER_ANGLE_DEG
                    or math.degrees(math.atan2(abs(d2[1]), abs(d2[0]))) > LUO_SMOOTH_CORNER_ANGLE_DEG
                ):
                    continue
                turn = abs(math.degrees(math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1])))
                if turn < 1.0 or turn > LUO_SMOOTH_CORNER_MAX_TURN_DEG:
                    continue
                t = l1 / (l1 + l2)
                nx, ny = ax + (bx - ax) * t, ay + (by - ay) * t
                if math.hypot(nx - mx, ny - my) > max_move:
                    continue
                coords[i] = (int(round(nx)), int(round(ny)))
                count += 1
                touched = True
            start = end + 1
        if touched:
            for k, c in enumerate(coords):
                glyph.coordinates[k] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1
    print(f"[luo] smooth shallow corners: {count} points across {glyph_count} glyphs (max_turn={LUO_SMOOTH_CORNER_MAX_TURN_DEG}°)")


def luo_na_modulate(font: TTFont) -> None:
    """v0.4.12 round 2: thin 捺 entries so the stroke swells into the foot
    (see the LUO_NA_* constant block)."""
    if LUO_NA_REGION_EM <= 0 or LUO_NA_ENTRY >= 1.0:
        print("[luo] na modulate: skipped")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    region = LUO_NA_REGION_EM * upm
    foot = LUO_NA_FOOT_EM * upm
    max_push = LUO_NA_MAX_PUSH_EM * upm
    # The walk-radical block of STRAIGHTEN_SKIP_CHARS protects 辶 from
    # straightening, not from 捺 modulation; 这/道/近 are the 平捺 this pass
    # exists for, so only the heart glyphs and frozen 月 are skipped here.
    skip_chars = (set(STRAIGHTEN_SKIP_CHARS) - set(LUO_NA_FLAT_CHARS)) | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)
    na_count = 0
    glyph_count = 0

    def _nearest(poly, qx, qy):
        best = None
        for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
            sx, sy = x1 - x0, y1 - y0
            l2 = sx * sx + sy * sy
            u = 0.0 if l2 == 0 else max(0.0, min(1.0, ((qx - x0) * sx + (qy - y0) * sy) / l2))
            cx, cy = x0 + u * sx, y0 + u * sy
            d = math.hypot(qx - cx, qy - cy)
            if best is None or d < best[0]:
                best = (d, cx, cy)
        return best

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF) or chr(cp) in skip_chars:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        coords = list(glyph.coordinates)
        is_flat = chr(cp) in LUO_NA_FLAT_CHARS
        all_ys = [c[1] for c in coords]
        glyph_ymin = min(all_ys)
        glyph_h = max(all_ys) - glyph_ymin
        region = (LUO_NA_FLAT_REGION_EM if is_flat else LUO_NA_REGION_EM) * upm
        entry = LUO_NA_FLAT_ENTRY if is_flat else LUO_NA_ENTRY
        touched = False
        start = 0
        for end in glyph.endPtsOfContours:
            n = end - start + 1
            if n < 10 or _contour_signed_area(coords, start, end) >= 0:
                start = end + 1
                continue
            for j in range(n):
                tx, ty = coords[start + j]

                key = tx - 1.3 * ty
                if any(
                    coords[start + (j + k) % n][0] - 1.3 * coords[start + (j + k) % n][1] >= key
                    for k in (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5)
                ):
                    continue
                sides = []
                for step in (1, -1):
                    pts = []
                    arc = 0.0
                    lx, ly = tx, ty
                    k = 1
                    while k < n // 2:
                        idx = start + (j + step * k) % n
                        px, py = coords[idx]
                        arc += math.hypot(px - lx, py - ly)
                        lx, ly = px, py
                        pts.append((idx, px, py, arc))
                        if arc > region * 1.2:
                            break
                        k += 1
                    sides.append(pts)
                if any(not p or p[-1][3] < region for p in sides):
                    continue
                # Direction of the stroke body: foot -> mid-region, must run
                # up-left at a 捺 angle (excludes 提, 点 and vertical hooks).
                def _at(pts, a):
                    return min(pts, key=lambda r: abs(r[3] - a))
                m1, m2 = _at(sides[0], region * 0.8), _at(sides[1], region * 0.8)
                dx = (m1[1] + m2[1]) / 2.0 - tx
                dy = (m1[2] + m2[2]) / 2.0 - ty
                if dx >= 0 or dy <= 0:
                    continue
                ang = math.degrees(math.atan2(dy, -dx))
                # The low 平捺 band only applies near the glyph bottom; a
                # 3-20° tip higher up is a sloped horizontal end (道's 首).
                flat_here = is_flat and ty < glyph_ymin + 0.25 * glyph_h
                ang_min = LUO_NA_FLAT_ANGLE_MIN if flat_here else LUO_NA_ANGLE_MIN
                if not (ang_min <= ang <= LUO_NA_ANGLE_MAX):
                    continue
                polys = [[(tx, ty)] + [(r[1], r[2]) for r in p] for p in sides]
                # Sample the foot width at interpolated arc positions:
                # LXGW 平捺 bottoms carry few points (道 has none between
                # 50u and 335u of arc), so vertex-only sampling misses them.
                def _point_at(si, a):
                    prev = (tx, ty, 0.0)
                    for _idx, px, py, arc in sides[si]:
                        if arc >= a:
                            u = (a - prev[2]) / max(arc - prev[2], 1e-6)
                            return prev[0] + (px - prev[0]) * u, prev[1] + (py - prev[1]) * u
                        prev = (px, py, arc)
                    return None

                foot_ws = []
                for si in (0, 1):
                    for f in (0.7, 0.85, 1.0, 1.15):
                        q = _point_at(si, foot * f)
                        if q is not None:
                            foot_ws.append(_nearest(polys[1 - si], q[0], q[1])[0])
                if len(foot_ws) < 2:
                    continue
                foot_w = sorted(foot_ws)[len(foot_ws) // 2]
                if foot_w < 0.03 * upm or foot_w > 0.095 * upm:  # wider feet are junction blobs, not 捺
                    continue
                _NA_TIPS.setdefault(gname, []).append((tx, ty, foot_w))
                moved = False
                for si in (0, 1):
                    for idx, px, py, arc in sides[si]:
                        if arc <= foot or arc >= region:
                            continue
                        w, cx, cy = _nearest(polys[1 - si], px, py)
                        if w < 1.0 or w > foot_w * LUO_NA_JOINT_RATIO:
                            continue
                        x = (arc - foot) / (region - foot)
                        target = foot_w * (1.0 - (1.0 - entry) * x)
                        # Ease the last 25% back to zero so the untouched
                        # junction meets the narrowed body without a step.
                        fade = min(1.0, (1.0 - x) / 0.25)
                        shrink = min((w - target) / 2.0, max_push) * fade
                        if shrink < 1.0:
                            continue
                        nx, ny = (px - cx) / w, (py - cy) / w
                        coords[idx] = (int(round(px - shrink * nx)), int(round(py - shrink * ny)))
                        moved = True
                if moved:
                    if os.environ.get("LUO_NA_DEBUG"):
                        print(f"[na] {chr(cp)} tip=({tx},{ty}) ang={ang:.0f} foot_w={foot_w:.0f}")
                    na_count += 1
                    touched = True
            start = end + 1
        if touched:
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1
    print(f"[luo] na modulate: {na_count} strokes across {glyph_count} glyphs (region={LUO_NA_REGION_EM}em, entry={LUO_NA_ENTRY})")


_NA_TIPS: dict = {}


def _densify_near(glyph, glyf, tips, max_len: float, radius: float) -> None:
    """Split quadratic/line segments that come within `radius` of a tip until
    each chord is <= max_len (de Casteljau at t=0.5, outline unchanged)."""
    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    coords = list(glyph.coordinates)
    flags = list(glyph.flags)
    new_c, new_f, new_e = [], [], []
    start = 0
    for end in glyph.endPtsOfContours:
        pts = [(coords[i], flags[i] & 1) for i in range(start, end + 1)]
        start = end + 1
        near = any(math.hypot(p[0] - tx, p[1] - ty) < radius for p, _ in pts for tx, ty in tips)
        if not near or not any(on for _, on in pts):
            new_c += [p for p, _ in pts]
            new_f += [f for _, f in pts]
            new_e.append(len(new_c) - 1)
            continue
        exp = []
        n = len(pts)
        for i in range(n):
            p, on = pts[i]
            q, qon = pts[(i + 1) % n]
            exp.append((p, on))
            if not on and not qon:
                exp.append((((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0), 1))
        k0 = next(i for i, (_, on) in enumerate(exp) if on)
        exp = exp[k0:] + exp[:k0]
        m = len(exp)
        out = []

        def _close(a, b):
            return any(min(math.hypot(a[0] - tx, a[1] - ty), math.hypot(b[0] - tx, b[1] - ty)) < radius for tx, ty in tips)

        def _emit(p0, c, p1, depth=0):
            if depth > 5 or math.hypot(p1[0] - p0[0], p1[1] - p0[1]) <= max_len or not _close(p0, p1):
                out.append((p0, 1))
                if c is not None:
                    out.append((c, 0))
                return
            if c is None:
                mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
                _emit(p0, None, mid, depth + 1)
                _emit(mid, None, p1, depth + 1)
            else:
                c1 = ((p0[0] + c[0]) / 2.0, (p0[1] + c[1]) / 2.0)
                c2 = ((c[0] + p1[0]) / 2.0, (c[1] + p1[1]) / 2.0)
                mid = ((c1[0] + c2[0]) / 2.0, (c1[1] + c2[1]) / 2.0)
                _emit(p0, c1, mid, depth + 1)
                _emit(mid, c2, p1, depth + 1)

        i = 0
        while i < m:
            p0 = exp[i][0]
            if exp[(i + 1) % m][1]:
                _emit(p0, None, exp[(i + 1) % m][0])
                i += 1
            else:
                _emit(p0, exp[(i + 1) % m][0], exp[(i + 2) % m][0])
                i += 2
        new_c += [(int(round(x)), int(round(y))) for (x, y), _ in out]
        new_f += [f for _, f in out]
        new_e.append(len(new_c) - 1)
    glyph.coordinates = GlyphCoordinates(new_c)
    glyph.flags = bytearray(new_f)
    glyph.endPtsOfContours = new_e
    glyph.numberOfContours = len(new_e)
    glyph.recalcBounds(glyf)


def luo_na_foot_swell(font: TTFont) -> None:
    """v0.4.12 round 5: give 捺 a W04-like foot (see LUO_NA_SWELL_* block).

    Round 4 pushed each point toward a target width measured by nearest-point
    distance; on dense points that estimate is noisy and the edges went
    lumpy. Here each stroke gets ONE foot width (recorded by
    luo_na_modulate) and both sides move along the smooth curve normal by a
    smooth bump of arc length, so the offset itself cannot introduce noise.
    """
    if LUO_NA_SWELL_PEAK_EM <= 0 or not _NA_TIPS:
        print("[luo] na foot swell: skipped")
        return
    glyf = font["glyf"]
    upm = font["head"].unitsPerEm
    peak = LUO_NA_SWELL_PEAK_EM * upm
    rise = LUO_NA_SWELL_RISE_EM * upm
    hold = LUO_NA_SWELL_HOLD_EM * upm
    fade_end = LUO_NA_SWELL_FADE_EM * upm
    max_push = LUO_NA_SWELL_MAX_PUSH_EM * upm

    def _bump(a):
        def ss(t):
            t = max(0.0, min(1.0, t))
            return t * t * (3 - 2 * t)
        if a <= rise:
            return ss(a / rise)
        if a <= hold:
            return 1.0
        return 1.0 - ss((a - hold) / (fade_end - hold))

    strokes = 0
    glyphs = 0
    for gname, recs in _NA_TIPS.items():
        glyph = glyf[gname]
        todo = list(recs)
        if not todo:
            continue
        _densify_near(glyph, glyf, [(tx, ty) for tx, ty, _ in todo], LUO_NA_SWELL_STEP_EM * upm, fade_end * 1.1)
        coords = list(glyph.coordinates)
        ends = list(glyph.endPtsOfContours)
        moves: dict = {}
        smooth_ok: set = set()
        for tx, ty, fw in todo:
            # Re-find the tip (densify keeps existing on-curves in place).
            best = None
            start = 0
            for end in ends:
                for i in range(start, end + 1):
                    d = math.hypot(coords[i][0] - tx, coords[i][1] - ty)
                    if best is None or d < best[0]:
                        best = (d, i, start, end)
                start = end + 1
            if best is None or best[0] > 4:
                continue
            _, ti, cs, ce = best
            n = ce - cs + 1
            # W04's foot runs ~20-25% wider than the stroke body, so even a
            # 捺 already near PEAK gets a relative swell.
            amp = min(max((peak - fw) / 2.0, LUO_NA_SWELL_REL * fw), max_push)
            if amp < 1.0:
                continue
            walks = []
            for step in (1, -1):
                arc = 0.0
                lx, ly = coords[ti]
                pts = []
                for k in range(1, n // 2):
                    idx = cs + (ti - cs + step * k) % n
                    px, py = coords[idx]
                    arc += math.hypot(px - lx, py - ly)
                    lx, ly = px, py
                    if arc >= fade_end:
                        break
                    pts.append((idx, arc))
                walks.append(pts)
            if not walks[0] or not walks[1]:
                continue
            # Outward sign per side: away from the other side's points.
            ox = sum(coords[i][0] for i, _ in walks[1]) / len(walks[1])
            oy = sum(coords[i][1] for i, _ in walks[1]) / len(walks[1])
            ax_ = sum(coords[i][0] for i, _ in walks[0]) / len(walks[0])
            ay_ = sum(coords[i][1] for i, _ in walks[0]) / len(walks[0])
            for side, (cx, cy) in ((walks[0], (ox, oy)), (walks[1], (ax_, ay_))):
                for idx, arc in side:
                    pos = idx - cs
                    pa = coords[cs + (pos - 1) % n]
                    pb = coords[cs + (pos + 1) % n]
                    tx_, ty_ = pb[0] - pa[0], pb[1] - pa[1]
                    tl = math.hypot(tx_, ty_)
                    if tl < 1e-6:
                        continue
                    nx, ny = -ty_ / tl, tx_ / tl
                    px, py = coords[idx]
                    if (px - cx) * nx + (py - cy) * ny < 0:
                        nx, ny = -nx, -ny
                    d = amp * _bump(arc)
                    if d < 0.5:
                        continue
                    prev = moves.get(idx)
                    if prev is None or d > prev[0]:
                        moves[idx] = (d, nx, ny)
                    if arc > LUO_NA_SWELL_KEEP_TIP_EM * upm:
                        smooth_ok.add(idx)
            strokes += 1
        if moves:
            for idx, (d, nx, ny) in moves.items():
                px, py = coords[idx]
                coords[idx] = (int(round(px + d * nx)), int(round(py + d * ny)))
            # Offsetting on- and off-curves independently breaks tangent
            # continuity (visible facets at 700px). Put each moved on-curve
            # that sits between two off-curves back at their midpoint.
            # Straight edges offset by a varying bump become a polyline with
            # visible corners; turn interior on-curves of the moved run into
            # off-curves so the implied midpoints give a smooth quadratic
            # spline. Run ends and the tip cap stay on-curve.
            fl = glyph.flags
            start = 0
            for end in ends:
                n = end - start + 1
                flip = []
                for idx in range(start, end + 1):
                    if idx not in smooth_ok or not (fl[idx] & 1):
                        continue
                    ia = start + (idx - start - 1) % n
                    ib = start + (idx - start + 1) % n
                    if ia in smooth_ok and ib in smooth_ok:
                        flip.append(idx)
                for idx in flip:
                    fl[idx] &= ~1
                start = end + 1
            start = 0
            for end in ends:
                n = end - start + 1
                for idx in range(start, end + 1):
                    if idx not in moves or not (fl[idx] & 1):
                        continue
                    ia = start + (idx - start - 1) % n
                    ib = start + (idx - start + 1) % n
                    if (fl[ia] & 1) or (fl[ib] & 1):
                        continue
                    coords[idx] = (
                        int(round((coords[ia][0] + coords[ib][0]) / 2.0)),
                        int(round((coords[ia][1] + coords[ib][1]) / 2.0)),
                    )
                start = end + 1
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyphs += 1
    print(f"[luo] na foot swell: {strokes} strokes across {glyphs} glyphs (peak={LUO_NA_SWELL_PEAK_EM}em)")


def luo_stem_normalize(font: TTFont) -> None:
    """v0.4.12 round 6: pull vertical stem widths into the W04 band (see the
    LUO_STEM_NORM_* constant block)."""
    if LUO_STEM_NORM_HI_EM <= 0:
        print("[luo] stem normalize: skipped")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    hi = LUO_STEM_NORM_HI_EM * upm
    lo = LUO_STEM_NORM_LO_EM * upm
    max_shift = LUO_STEM_NORM_MAX_SHIFT_EM * upm
    skip_chars = set(STRAIGHTEN_SKIP_CHARS) | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)
    thin_count = thick_count = glyph_count = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF) or chr(cp) in skip_chars:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        coords = list(glyph.coordinates)
        flags = glyph.flags
        ends = glyph.endPtsOfContours
        ys = [c[1] for c in coords]
        xs = [c[0] for c in coords]
        glyph_max = max(max(xs) - min(xs), max(ys) - min(ys))
        if glyph_max <= 0:
            continue
        min_len = LUO_STEM_NORM_MIN_LEN_RATIO * glyph_max

        # (x_mid, y_lo, y_hi, dir, start, end, ia, ib)
        chords = []
        short_chords = []
        start = 0
        for end in ends:
            n = end - start + 1
            oc = [start + j for j in range(n) if flags[start + j] & 1]
            # Merge consecutive near-vertical same-direction segments: LXGW
            # often splits one stem edge in two (好's 子), and rebuilding only
            # the long half left a step at the seam.
            m = len(oc)
            seg_ok = []
            for k in range(m):
                (ax, ay), (bx, by) = coords[oc[k]], coords[oc[(k + 1) % m]]
                dy = by - ay
                if abs(dy) < 0.03 * glyph_max or abs(bx - ax) > 0.18 * abs(dy):
                    seg_ok.append(0)
                else:
                    seg_ok.append(1 if dy > 0 else -1)
            k = 0
            while k < m:
                if seg_ok[k] == 0:
                    k += 1
                    continue
                d0 = seg_ok[k]
                j = k
                while j + 1 < m and seg_ok[j + 1] == d0:
                    j += 1
                ia, ib = oc[k], oc[(j + 1) % m]
                (ax, ay), (bx, by) = coords[ia], coords[ib]
                dy = by - ay
                if abs(dy) >= min_len and abs(bx - ax) <= 0.18 * abs(dy):
                    chords.append(((ax + bx) / 2.0, min(ay, by), max(ay, by), d0, start, end, ia, ib))
                elif abs(dy) >= 0.06 * glyph_max and abs(bx - ax) <= 0.18 * abs(dy):
                    short_chords.append(((ax + bx) / 2.0, min(ay, by), max(ay, by), d0, start, end, ia, ib))
                k = j + 1
            start = end + 1

        moves: dict[int, float] = {}
        for L in chords:
            if L[3] != 1:
                continue
            best = None
            for R in chords:
                if R[3] != -1 or R[0] <= L[0]:
                    continue
                if R[4] != L[4] and _contour_signed_area(coords, L[4], L[5]) < 0 and _contour_signed_area(coords, R[4], R[5]) < 0:
                    # Two different OUTER contours: overlapping LXGW strokes
                    # (孵's 卵). A frame wall pairs an outer edge with a
                    # counter edge and must still pair (典/口).
                    continue
                ov = min(L[2], R[2]) - max(L[1], R[1])
                if ov < 0.6 * min(L[2] - L[1], R[2] - R[1]):
                    continue
                gap = R[0] - L[0]
                if gap > 0.12 * upm:
                    continue
                # Round 12: another vertical edge between L and R means a
                # counter sits between them (朋's two 月, 卵, 詹): pairing across
                # it and rebuilding closed the counter into a black bar.
                if any(
                    O is not L and O is not R
                    and L[0] < O[0] < R[0]
                    and min(O[2], L[2], R[2]) - max(O[1], L[1], R[1]) > 0
                    for O in chords
                ):
                    continue
                if best is None or gap < best[0]:
                    best = (gap, R)
            if best is None:
                continue
            _, R = best
            # Round 12: the space between the pair must be ink. Sample three
            # heights between the edges with an even-odd test on the raw
            # points; any miss means a counter sits between (绷/赡/孵).
            def _inside(qx, qy):
                # Non-zero winding: overlapping stroke contours stay ink.
                wn = 0
                s0 = 0
                for e0 in ends:
                    pts = coords[s0:e0 + 1]
                    s0 = e0 + 1
                    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
                        if (y0 > qy) != (y1 > qy):
                            if qx < x0 + (x1 - x0) * (qy - y0) / (y1 - y0):
                                wn += 1 if y1 > y0 else -1
                return wn != 0
            yl, yh = max(L[1], R[1]), min(L[2], R[2])
            if not all(
                _inside(L[0] + (R[0] - L[0]) * fx, yl + (yh - yl) * f)
                for f in (0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95) for fx in (0.15, 0.35, 0.5, 0.65, 0.85)
            ):
                continue
            # Round 9: measure the width at the bottom and top of the shared
            # span and correct each end separately, so a tapered stem (LXGW
            # 子 竖钩: thin under the 横, fat below) comes out parallel
            # instead of keeping its wedge.
            y_lo = max(L[1], R[1])
            y_hi = min(L[2], R[2])

            def _x_at(chord, yq):
                # Follow every point of the edge (off-curves included), so a
                # bowed edge (书 竖钩 belly) measures at its real width.
                _, _, _, _, cs, ce, ia, ib = chord
                pts = []
                idx = ia
                while True:
                    pts.append(coords[idx])
                    if idx == ib:
                        break
                    idx += 1
                    if idx > ce:
                        idx = cs
                best = None
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    lo_y, hi_y = min(y0, y1), max(y0, y1)
                    if lo_y <= yq <= hi_y and y1 != y0:
                        xq = x0 + (x1 - x0) * (yq - y0) / (y1 - y0)
                        best = xq if best is None else (max(best, xq) if chord[3] == -1 else min(best, xq))
                if best is None:
                    (x0, y0), (x1, y1) = coords[ia], coords[ib]
                    best = (x0 + x1) / 2.0 if y1 == y0 else x0 + (x1 - x0) * (yq - y0) / (y1 - y0)
                return best

            # Round 11: rebuild the stem as two straight parallel edges of
            # one width around its own centre line (W04 keeps 竖 straight
            # and even). Pushing points on the old curved edges always left
            # a belly or a bitten-in notch (书/好/言).
            # Short stubs (书's 竖 above the top 横) are left alone: rebuilt
            # on their own they drift off the main stem's line.
            if y_hi - y_lo < 0.15 * glyph_max:
                continue
            # Edges must describe the same stem length: when one runs on far
            # past the other (傀's 亻), they are two different strokes.
            if max(L[2] - L[1], R[2] - R[1]) > 1.35 * (y_hi - y_lo):
                continue
            ws = [_x_at(R, yq) - _x_at(L, yq) for yq in (y_lo, y_lo + (y_hi - y_lo) * 0.25, (y_lo + y_hi) / 2.0, y_lo + (y_hi - y_lo) * 0.75, y_hi)]
            w_med = sorted(ws)[len(ws) // 2]
            if min(ws) < 0.03 * upm or max(ws) > 1.8 * max(min(ws), 1.0):
                continue  # tapering edges (傀's 亻 竖 vs 撇) are not one stem
            if w_med > 0.105 * upm:
                continue  # wider than any real stem: two strokes plus a gap
            w_t = min(max(w_med, lo), hi)
            c_lo = (_x_at(L, y_lo) + _x_at(R, y_lo)) / 2.0
            c_hi = (_x_at(L, y_hi) + _x_at(R, y_hi)) / 2.0
            span = (y_hi - y_lo) or 1.0
            if abs(w_t - w_med) >= 1.0 or max(ws) - min(ws) > 0.12 * w_t:
                if w_t < w_med:
                    thick_count += 1
                else:
                    thin_count += 1
            else:
                continue
            for chord, sign in ((L, -1.0), (R, 1.0)):
                _, _, _, _, cs, ce, ia, ib = chord
                idx = ia
                while True:
                    px, py = coords[idx]
                    u = (py - y_lo) / span
                    cx_line = c_lo + (c_hi - c_lo) * u + sign * w_t / 2.0
                    mv = cx_line - px
                    mv = max(-LUO_STEM_NORM_BULGE_MAX_EM * upm, min(LUO_STEM_NORM_BULGE_MAX_EM * upm, mv))
                    prev = moves.get(idx)
                    if prev is None or abs(mv) > abs(prev):
                        moves[idx] = mv
                    if idx == ib:
                        break
                    idx += 1
                    if idx > ce:
                        idx = cs
        # Round 13: an outer wall with a stack of short counter edges inside
        # (典/目: several small 口 along one wall) never pairs above, so it
        # kept its thin LXGW width. Measure against the nearest inner edges
        # and push only the OUTER edge outward; counters stay untouched.
        paired = {id(c) for c in chords if any(m in moves for m in (c[6], c[7]))}
        for W in chords:
            if id(W) in paired or _contour_signed_area(coords, W[4], W[5]) >= 0:
                continue
            outward = 1.0 if W[3] == -1 else -1.0  # right wall edge runs down
            inner = [
                O for O in chords + short_chords
                if O[3] == -W[3] and 0 < (W[0] - O[0]) * outward <= 0.12 * upm
                and _contour_signed_area(coords, O[4], O[5]) > 0  # a counter, not a neighbouring stroke (傀)
                and min(O[2], W[2]) - max(O[1], W[1]) > 0
            ]
            if not inner:
                continue
            ws = []
            for f in (0.2, 0.35, 0.5, 0.65, 0.8):
                yq = W[1] + (W[2] - W[1]) * f
                near = [abs(W[0] - O[0]) for O in inner if O[1] <= yq <= O[2]]
                if near:
                    ws.append(min(near))
            if len(ws) < 3:
                continue
            w_med = sorted(ws)[len(ws) // 2]
            if w_med >= LUO_STEM_NORM_WALL_TARGET_EM * upm or w_med < 0.03 * upm:
                continue
            # Round 17: only near-vertical walls with open space outside. 荔's
            # left 力 hook edge (slope 0.16) was pushed 0.035em into the narrow
            # gap before the right 力 and closed it.
            (wx0, wy0), (wx1, wy1) = coords[W[6]], coords[W[7]]
            if abs(wx1 - wx0) > 0.12 * abs(wy1 - wy0):
                continue
            def _ink_at(qx, qy):
                wn = 0
                s0 = 0
                for e0 in ends:
                    pts = coords[s0:e0 + 1]
                    s0 = e0 + 1
                    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
                        if (y0 > qy) != (y1 > qy) and qx < x0 + (x1 - x0) * (qy - y0) / (y1 - y0):
                            wn += 1 if y1 > y0 else -1
                return wn != 0

            clear = True
            for f in (0.25, 0.5, 0.75):
                qy = wy0 + (wy1 - wy0) * f
                qx0 = wx0 + (wx1 - wx0) * f
                for dd in (0.05, 0.08, 0.11):
                    if _ink_at(qx0 + outward * dd * upm, qy):
                        clear = False
            if not clear:
                continue
            d = outward * min(LUO_STEM_NORM_WALL_TARGET_EM * upm - w_med, LUO_STEM_NORM_WALL_MAX_PUSH_EM * upm)
            idx = W[6]
            while True:
                # No end easing: this edge often has a single on-curve at its
                # lower end, so easing left the lower wall unpushed (a wedge).
                mv = d
                prev = moves.get(idx)
                if prev is None or abs(mv) > abs(prev):
                    moves[idx] = mv
                if idx == W[7]:
                    break
                idx += 1
                if idx > W[5]:
                    idx = W[4]
            thin_count += 1

        if moves:
            for idx, dx in moves.items():
                x, y = coords[idx]
                coords[idx] = (int(round(x + dx)), y)
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1
    print(f"[luo] stem normalize: {thick_count} thick / {thin_count} thin stems across {glyph_count} glyphs (band={LUO_STEM_NORM_LO_EM}-{LUO_STEM_NORM_HI_EM}em)")


def luo_flick_taper(font: TTFont) -> None:
    """v0.4.12 round 8: taper round upward flick tips (see LUO_FLICK_*)."""
    if LUO_FLICK_REGION_EM <= 0 or LUO_FLICK_TIP >= 1.0:
        print("[luo] flick taper: skipped")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    region = LUO_FLICK_REGION_EM * upm
    max_push = LUO_FLICK_MAX_PUSH_EM * upm
    skip_chars = set(STRAIGHTEN_SKIP_CHARS) | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)
    tips = glyphs = 0

    def _nearest(poly, qx, qy):
        best = None
        for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
            sx, sy = x1 - x0, y1 - y0
            l2 = sx * sx + sy * sy
            u = 0.0 if l2 == 0 else max(0.0, min(1.0, ((qx - x0) * sx + (qy - y0) * sy) / l2))
            cx, cy = x0 + u * sx, y0 + u * sy
            d = math.hypot(qx - cx, qy - cy)
            if best is None or d < best[0]:
                best = (d, cx, cy)
        return best

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF) or chr(cp) in skip_chars:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        coords = list(glyph.coordinates)
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        gw, gh = xmax - xmin, ymax - ymin
        if gw <= 0 or gh <= 0:
            continue
        touched = False
        start = 0
        for end in glyph.endPtsOfContours:
            n = end - start + 1
            if n < 10 or _contour_signed_area(coords, start, end) >= 0:
                start = end + 1
                continue
            for j in range(n):
                tx, ty = coords[start + j]
                if tx < xmin + 0.55 * gw or ty - ymin > 0.45 * gh:
                    continue
                # Local top, flat tops allowed (风's tip is three points at
                # one y); only the first point of a plateau counts.
                if any(coords[start + (j + k) % n][1] > ty for k in (-4, -3, -2, -1, 1, 2, 3, 4)):
                    continue
                if coords[start + (j - 1) % n][1] == ty:
                    continue
                sides = []
                for step in (1, -1):
                    pts, arc, (lx, ly) = [], 0.0, (tx, ty)
                    for k in range(1, n // 2):
                        idx = start + (j + step * k) % n
                        px, py = coords[idx]
                        arc += math.hypot(px - lx, py - ly)
                        lx, ly = px, py
                        pts.append((idx, px, py, arc))
                        if arc > region * 1.6:
                            break
                    sides.append(pts)
                if any(not p or p[-1][3] < region for p in sides):
                    continue
                # Both sides must run downward from the tip (a flick, not a
                # cap on a horizontal) and stay roughly vertical.
                ok = True
                for p in sides:
                    q = min(p, key=lambda r: abs(r[3] - region))
                    dx, dy = q[1] - tx, q[2] - ty
                    if dy >= 0 or abs(dx) > 1.2 * abs(dy):
                        ok = False
                if not ok:
                    continue
                polys = [[(tx, ty)] + [(r[1], r[2]) for r in p] for p in sides]
                ref = []
                for si in (0, 1):
                    q = min(sides[si], key=lambda r: abs(r[3] - region))
                    ref.append(_nearest(polys[1 - si], q[1], q[2])[0])
                full = sum(ref) / 2.0
                if full < 0.03 * upm or full > 0.11 * upm:
                    continue
                moves = []
                for si in (0, 1):
                    for idx, px, py, arc in sides[si]:
                        if arc <= 0 or arc >= region:
                            continue
                        w, cx, cy = _nearest(polys[1 - si], px, py)
                        if w < 1.0:
                            continue
                        x = arc / region
                        target = full * (LUO_FLICK_TIP + (1.0 - LUO_FLICK_TIP) * x ** 0.8)
                        d = min((w - target) / 2.0, max_push)
                        if d < 1.0:
                            continue
                        moves.append((idx, -d * (px - cx) / w, -d * (py - cy) / w))
                for idx, mx_, my_ in moves:
                    px, py = coords[idx]
                    coords[idx] = (int(round(px + mx_)), int(round(py + my_)))
                if moves:
                    if os.environ.get("LUO_FLICK_DEBUG"):
                        print(f"[flick] {chr(cp)} tip=({tx},{ty}) full={full:.0f}")
                    tips += 1
                    touched = True
            start = end + 1
        if touched:
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyphs += 1
    print(f"[luo] flick taper: {tips} tips across {glyphs} glyphs (region={LUO_FLICK_REGION_EM}em, tip={LUO_FLICK_TIP})")


def luo_pie_tail_fill(font: TTFont) -> None:
    """v0.4.12: give long 撇 tails flesh down to a blunt point (see the
    LUO_PIE_FILL_* constant block)."""
    if LUO_PIE_FILL_REGION_EM <= 0 or LUO_PIE_FILL_TIP >= 1.0:
        print("[luo] pie tail fill: skipped")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    region = LUO_PIE_FILL_REGION_EM * upm
    max_push = LUO_PIE_FILL_MAX_PUSH_EM * upm
    skip_chars = set(STRAIGHTEN_SKIP_CHARS) | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)
    tail_count = 0
    glyph_count = 0

    def _interp(side, s_q):
        # side: list of (s, t) sorted by s; linear interpolation, None outside.
        for (s0, t0), (s1, t1) in zip(side, side[1:]):
            if s0 <= s_q <= s1:
                if s1 - s0 < 1e-6:
                    return t0
                return t0 + (t1 - t0) * (s_q - s0) / (s1 - s0)
        return None

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF):
            continue
        if chr(cp) in skip_chars:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        coords = list(glyph.coordinates)
        ends = glyph.endPtsOfContours
        touched = False
        start = 0
        for end in ends:
            n = end - start + 1
            if n < 10 or _contour_signed_area(coords, start, end) >= 0:
                start = end + 1
                continue
            for j in range(n):
                ti = start + j
                tx, ty = coords[ti]
                # Tip: strict extremum toward down-left within +-5 points.
                key = -(tx + 1.3 * ty)
                if any(
                    -(coords[start + (j + k) % n][0] + 1.3 * coords[start + (j + k) % n][1]) >= key
                    for k in (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5)
                ):
                    continue
                # Convex tip only: notches (阝 inner corner, 也 hook knee)
                # also point down-left but turn the other way. Outer
                # contours here have negative signed area, so a convex
                # vertex has a negative turn cross product.
                pax, pay = coords[start + (j - 3) % n]
                pbx, pby = coords[start + (j + 3) % n]
                if (tx - pax) * (pby - ty) - (ty - pay) * (pbx - tx) >= 0:
                    continue
                # Walk both sides until the axial distance passes region.
                sides = []
                for step in (1, -1):
                    pts = []
                    k = 1
                    while k < n // 2:
                        idx = start + (j + step * k) % n
                        px, py = coords[idx]
                        pts.append((idx, px - tx, py - ty))
                        if math.hypot(px - tx, py - ty) > region * 1.25:
                            break
                        k += 1
                    sides.append(pts)
                if any(math.hypot(p[-1][1], p[-1][2]) < region for p in sides):
                    continue
                # Axis: tip toward the midpoint of the two sides at ~region.
                def _at(pts):
                    for idx, dx, dy in pts:
                        if math.hypot(dx, dy) >= region:
                            return dx, dy
                    return pts[-1][1], pts[-1][2]
                (ax1, ay1), (ax2, ay2) = _at(sides[0]), _at(sides[1])
                mx, my = (ax1 + ax2) / 2.0, (ay1 + ay2) / 2.0
                alen = math.hypot(mx, my)
                if alen < 1e-6 or mx <= 0 or my <= 0:
                    continue
                ang = math.degrees(math.atan2(my, mx))
                if not (LUO_PIE_FILL_ANGLE_MIN <= ang <= LUO_PIE_FILL_ANGLE_MAX):
                    continue
                # Local width: each side point against the opposite side's
                # polyline (curved 撇 have no single axis). Arc length from
                # the tip along each side gives the taper coordinate.
                polys = [[(tx, ty)] + [(tx + dx, ty + dy) for _, dx, dy in pts] for pts in sides]

                def _nearest(poly, qx, qy):
                    best = None
                    for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
                        sx, sy = x1 - x0, y1 - y0
                        l2 = sx * sx + sy * sy
                        u = 0.0 if l2 == 0 else max(0.0, min(1.0, ((qx - x0) * sx + (qy - y0) * sy) / l2))
                        cx, cy = x0 + u * sx, y0 + u * sy
                        d = math.hypot(qx - cx, qy - cy)
                        if best is None or d < best[0]:
                            best = (d, cx, cy)
                    return best

                def _profile(side_i):
                    pts = sides[side_i]
                    other = polys[1 - side_i]
                    out = []
                    arc = 0.0
                    lx, ly = tx, ty
                    for idx, dx, dy in pts:
                        qx, qy = tx + dx, ty + dy
                        arc += math.hypot(qx - lx, qy - ly)
                        lx, ly = qx, qy
                        nb = _nearest(other, qx, qy)
                        out.append((idx, arc, nb))
                    return out

                profs = [_profile(0), _profile(1)]

                # Hook guard: a 横折钩/竖钩 tip also points down-left, but
                # its stroke turns into a near-vertical stem right after the
                # flick. A 撇 keeps slanting across the upper half too.
                def _pt_at(side_i, target_arc):
                    prof = profs[side_i]
                    idx = min(prof, key=lambda r: abs(r[1] - target_arc))[0]
                    return coords[idx]
                (h1x, h1y), (h2x, h2y) = _pt_at(0, region * 0.5), _pt_at(1, region * 0.5)
                (e1x, e1y), (e2x, e2y) = _pt_at(0, region), _pt_at(1, region)
                ddx = (e1x + e2x - h1x - h2x) / 2.0
                ddy = (e1y + e2y - h1y - h2y) / 2.0
                up_ang = math.degrees(math.atan2(ddy, abs(ddx))) if ddy > 0 else 0.0
                if ddx < 0 or not (45.0 <= up_ang <= 80.0):
                    continue
                bodies = []
                for prof in profs:
                    near = [(abs(arc - region), w) for _, arc, (w, _, _) in prof if region * 0.6 <= arc <= region * 1.6]
                    if near:
                        bodies.append(min(near)[1])
                if len(bodies) < 2:
                    continue
                body = sum(bodies) / len(bodies)
                if body < 0.02 * upm or body > 0.12 * upm:
                    continue
                body = max(body, LUO_PIE_FILL_BODY_MIN_EM * upm)
                moved = False
                for prof in profs:
                    for idx, arc, (w, cx, cy) in prof:
                        if arc >= region or w < 1.0:
                            continue
                        x = arc / region
                        target = body * (LUO_PIE_FILL_TIP + (1.0 - LUO_PIE_FILL_TIP) * x ** LUO_PIE_FILL_POW)
                        # Fade the push out over the last 30% so the grown
                        # tail meets the untouched body without a step.
                        fade = min(1.0, (1.0 - x) / 0.3)
                        # Round 16: ramp in from the tip too. The tip vertex
                        # never moves, so growing its neighbours at full
                        # strength left a step right at the point (用's 撇).
                        _fi = min(1.0, arc / (LUO_PIE_FILL_TIP_RAMP_EM * upm))
                        fade *= _fi * _fi * (3 - 2 * _fi)
                        grow = min((target - w) / 2.0, max_push) * fade
                        if grow < 1.0:
                            continue
                        px, py = coords[idx]
                        nx, ny = (px - cx) / w, (py - cy) / w
                        coords[idx] = (int(round(px + grow * nx)), int(round(py + grow * ny)))
                        moved = True
                if moved:
                    if os.environ.get("LUO_PIE_FILL_DEBUG"):
                        print(f"[pie] {chr(cp)} tip=({tx},{ty}) ang={ang:.0f} up={up_ang:.0f} body={body:.0f}")
                    tail_count += 1
                    touched = True
            start = end + 1
        if touched:
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1
    print(
        f"[luo] pie tail fill: {tail_count} tails across {glyph_count} glyphs "
        f"(region={LUO_PIE_FILL_REGION_EM}em, tip={LUO_PIE_FILL_TIP})"
    )


def luo_long_horiz_thin(font: TTFont) -> None:
    """v0.4.12: thin long horizontal strokes toward the W04 contrast band.

    Symmetric chord-shift thinning (see the constant block for the design
    rationale): long near-horizontal top-edge chords of outer CCW contours
    drop by delta/2, long bottom-edge chords rise by delta/2, and interior
    off-curve points between each chord's endpoints move with it. The
    stroke midline stays put, so caps and joinery shift by at most delta/2.

    Topology gate: the glyph must contain at least one long near-vertical
    chord (a real stem). Thinning horizontals only raises H/V contrast when
    a vertical stem exists to contrast AGAINST; on stem-less glyphs built
    almost entirely from horizontals (一/二/巨/乙/万/云) the same delta just
    lightens the whole glyph and overshoots past the W04 band (measured
    d_hv -0.06~-0.14 on exactly that class in the first cut of this pass).

    Skips inner contours, STRAIGHTEN_SKIP_CHARS, and the frozen 月.
    """
    if LUO_LONG_HORIZ_THIN_EM <= 0:
        print("[luo] long-horiz thin: skipped (delta=0)")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    half = LUO_LONG_HORIZ_THIN_EM * upm / 2.0
    skip_chars = (
        set(STRAIGHTEN_SKIP_CHARS)
        | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)
        | set(LUO_LONG_HORIZ_THIN_SKIP_CHARS)
    )

    seg_count = 0
    glyph_count = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF):
            continue
        char = chr(cp)
        if char in skip_chars:
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
        min_chord_len = LUO_LONG_HORIZ_THIN_MIN_RATIO * glyph_max
        min_stem_len = 0.30 * glyph_max

        # Topology gate: require at least one long near-vertical chord.
        has_stem = False
        start = 0
        for end in ends:
            n = end - start + 1
            if n >= 4:
                on_curve = [start + j for j in range(n) if flags[start + j] & 1]
                for k in range(len(on_curve)):
                    ia = on_curve[k]
                    ib = on_curve[(k + 1) % len(on_curve)]
                    dx = coords[ib][0] - coords[ia][0]
                    dy = coords[ib][1] - coords[ia][1]
                    if abs(dy) < min_stem_len:
                        continue
                    if math.degrees(math.atan2(abs(dx), abs(dy))) <= 10.0:
                        has_stem = True
                        break
            if has_stem:
                break
            start = end + 1
        if not has_stem:
            continue

        # Collect (point_index, dy) moves first so overlapping chords never
        # double-shift a point; the largest requested move wins.
        moves: dict[int, float] = {}

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
                if length < min_chord_len or dx == 0:
                    continue
                angle_off_h = math.degrees(math.atan2(abs(dy), abs(dx)))
                if angle_off_h > LUO_LONG_HORIZ_THIN_ANGLE_DEG:
                    continue
                # Round 8: the bottom main 横 (田/且/里/王 closing bar) is the
                # 主笔 in kai and W04 keeps it the heaviest horizontal; thinning
                # it made 田's bottom read weak. Same gate as gesture body
                # contract's is_main_bottom.
                if (
                    length >= LUO_GESTURE_MAIN_H_MIN_W * glyph_w
                    and min(ay, by) < min(all_ys) + LUO_GESTURE_MAIN_H_BAND * glyph_h
                ):
                    continue
                # dx > 0 on a CCW outer = top edge (thin downward);
                # dx < 0 = bottom edge (thin upward).
                shift = -half if dx > 0 else half

                idx = ia
                while True:
                    prev = moves.get(idx)
                    if prev is None or abs(shift) > abs(prev):
                        moves[idx] = shift
                    if idx == ib:
                        break
                    idx += 1
                    if idx > end:
                        idx = start
                seg_count += 1

            start = end + 1

        if moves:
            for idx, shift in moves.items():
                x, y = coords[idx]
                coords[idx] = (x, int(round(y + shift)))
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] long-horiz thin: {seg_count} chords across {glyph_count} glyphs "
        f"(delta={LUO_LONG_HORIZ_THIN_EM}em, min_ratio={LUO_LONG_HORIZ_THIN_MIN_RATIO})"
    )


def luo_horiz_weight_rescue(font: TTFont) -> None:
    """Re-thicken near-horizontal strokes on Tang thin-bar queue.

    Inverse of `luo_long_horiz_thin`: top-edge chords move UP by half delta,
    bottom-edge chords move DOWN, so stroke thickness grows about the midline.
    Lower MIN_RATIO (0.22) so secondary mid 横 (清's 青 stack) also recover,
    not only the full-width main bar. Explicit char list only.
    """
    if LUO_HORIZ_WEIGHT_RESCUE_EM <= 0 or not LUO_HORIZ_WEIGHT_RESCUE_CHARS:
        print("[luo] horiz weight rescue: skipped")
        return
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    half = LUO_HORIZ_WEIGHT_RESCUE_EM * upm / 2.0
    seg_count = 0
    glyph_count = 0

    for char in LUO_HORIZ_WEIGHT_RESCUE_CHARS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
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
        min_chord_len = LUO_HORIZ_WEIGHT_RESCUE_MIN_RATIO * glyph_max
        moves: dict[int, float] = {}
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
                if length < min_chord_len or dx == 0:
                    continue
                angle_off_h = math.degrees(math.atan2(abs(dy), abs(dx)))
                if angle_off_h > LUO_LONG_HORIZ_THIN_ANGLE_DEG:
                    continue
                # Inverse of thin: top edge (dx>0) up, bottom edge (dx<0) down
                shift = half if dx > 0 else -half
                idx = ia
                while True:
                    prev = moves.get(idx)
                    if prev is None or abs(shift) > abs(prev):
                        moves[idx] = shift
                    if idx == ib:
                        break
                    idx += 1
                    if idx > end:
                        idx = start
                seg_count += 1
            start = end + 1
        if moves:
            for idx, shift in moves.items():
                x, y = coords[idx]
                coords[idx] = (x, int(round(y + shift)))
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] horiz weight rescue: {seg_count} chords across {glyph_count} glyphs "
        f"(delta={LUO_HORIZ_WEIGHT_RESCUE_EM}em, chars={LUO_HORIZ_WEIGHT_RESCUE_CHARS})"
    )


def _late_refine_qing_tip(font: TTFont) -> None:
    """Run 清 tip blunt late in the pipeline (after H-rescue / free-end)."""
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    gname = cmap.get(ord("清"))
    if not gname or gname not in glyf:
        return
    glyph = glyf[gname]
    if glyph.numberOfContours <= 0:
        return
    if _refine_problem_qing(glyph, glyf, upm):
        print("[luo] late 清 tip blunt: ok")


def luo_free_end_blunt(font: TTFont) -> None:
    """Blunt needle free-ends on Tang-circled terminals (玄云两来清).

    Screenshot circles landed on right-side 捺 tips, top-横 right caps, and
    short-tick exits that taper into blades. For each outer contour tip whose
    local thickness is below the floor, pull the tip back along the stroke
    axis and expand the last ZONE along the perpendicular so the cut reads
    short and weighty (print-kai), not pointed.
    """
    if (
        LUO_FREE_END_BLUNT_PULL_EM <= 0 and LUO_FREE_END_BLUNT_PLUMP_EM <= 0
    ) or not LUO_FREE_END_BLUNT_CHARS:
        print("[luo] free-end blunt: skipped")
        return
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    zone = LUO_FREE_END_BLUNT_ZONE_EM * upm
    pull = LUO_FREE_END_BLUNT_PULL_EM * upm
    plump = LUO_FREE_END_BLUNT_PLUMP_EM * upm
    floor_t = LUO_FREE_END_BLUNT_THICK_FLOOR_EM * upm
    tip_count = 0
    glyph_count = 0

    def _local_thick(coords, start, end, i):
        x, y = coords[i]
        best = None
        for j in range(start, end + 1):
            if j == i:
                continue
            px, py = coords[j]
            d = math.hypot(px - x, py - y)
            if d < 3.0 or d > 0.14 * upm:
                continue
            if best is None or d < best:
                best = d
        return best

    for char in LUO_FREE_END_BLUNT_CHARS:
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        coords = list(glyph.coordinates)
        flags = glyph.flags
        ends = glyph.endPtsOfContours
        all_xs = [c[0] for c in coords]
        all_ys = [c[1] for c in coords]
        xmin, xmax = min(all_xs), max(all_xs)
        ymin, ymax = min(all_ys), max(all_ys)
        gw = max(1.0, xmax - xmin)
        gh = max(1.0, ymax - ymin)
        moves: dict[int, tuple[float, float]] = {}
        start = 0
        for end in ends:
            n = end - start + 1
            if n < 6:
                start = end + 1
                continue
            if _contour_signed_area(coords, start, end) >= 0:
                start = end + 1
                continue
            on_curve = [start + j for j in range(n) if flags[start + j] & 1]
            if len(on_curve) < 3:
                start = end + 1
                continue
            # Candidate tips: right-side or lower-right on-curve points with
            # thin local thickness (the circled needles).
            candidates = []
            rightmost_i = max(on_curve, key=lambda i: coords[i][0])
            for i in on_curve:
                x, y = coords[i]
                xn = (x - xmin) / gw
                yn = (y - ymin) / gh
                # free ends Tang circled: right half, or lower-right tail
                if xn < 0.55 and not (xn > 0.48 and yn < 0.40):
                    continue
                thick = _local_thick(coords, start, end, i)
                force_right = i == rightmost_i and xn >= 0.88
                if thick is None:
                    continue
                if thick >= floor_t and not force_right:
                    continue
                # prefer true extrema: farther out than on-curve neighbors
                k = on_curve.index(i)
                ip, iq = on_curve[k - 1], on_curve[(k + 1) % len(on_curve)]
                r = math.hypot(x - (xmin + gw * 0.45), y - (ymin + gh * 0.5))
                rp = math.hypot(
                    coords[ip][0] - (xmin + gw * 0.45),
                    coords[ip][1] - (ymin + gh * 0.5),
                )
                rq = math.hypot(
                    coords[iq][0] - (xmin + gw * 0.45),
                    coords[iq][1] - (ymin + gh * 0.5),
                )
                if r + 4.0 < max(rp, rq) and not force_right:
                    continue
                candidates.append((thick, xn, -yn, i))
            if not candidates:
                start = end + 1
                continue
            # Prefer rightmost thin tips (the circled needles), then thinnest.
            candidates.sort(key=lambda c: (-c[1], c[0]))
            for thick, _xn, _yn, tip_i in candidates[:4]:
                tx, ty = coords[tip_i]
                # Stroke axis: from mean of thicker nearby points toward tip
                body_x = body_y = 0.0
                body_n = 0
                for j in range(start, end + 1):
                    px, py = coords[j]
                    if math.hypot(px - tx, py - ty) > zone * 1.4:
                        continue
                    jt = _local_thick(coords, start, end, j)
                    if jt is not None and jt >= floor_t * 0.85:
                        body_x += px
                        body_y += py
                        body_n += 1
                if body_n < 2:
                    # fallback: contour bbox centre
                    cxs = [coords[j][0] for j in range(start, end + 1)]
                    cys = [coords[j][1] for j in range(start, end + 1)]
                    body_x = sum(cxs) / len(cxs)
                    body_y = sum(cys) / len(cys)
                else:
                    body_x /= body_n
                    body_y /= body_n
                ax, ay = tx - body_x, ty - body_y
                alen = math.hypot(ax, ay)
                if alen < 4.0:
                    start = end + 1
                    continue
                ux, uy = ax / alen, ay / alen  # outward along stroke
                nx, ny = -uy, ux  # perpendicular
                # More pull when thinner or when the taper runs long.
                deficit = max(0.0, (floor_t - thick) / max(floor_t, 1.0))
                taper_boost = 1.0 + min(1.0, max(0.0, (alen - 0.06 * upm) / (0.10 * upm)))
                local_pull = pull * (0.55 + 0.45 * deficit) * taper_boost
                local_plump = plump * (0.50 + 0.50 * deficit) * (0.85 + 0.15 * taper_boost)
                local_zone = zone * (1.0 + 0.25 * (taper_boost - 1.0))
                for j in range(start, end + 1):
                    px, py = coords[j]
                    dist = math.hypot(px - tx, py - ty)
                    if dist > local_zone:
                        continue
                    t = 1.0 - dist / local_zone
                    t = t * t  # stronger near tip
                    # pull back toward body
                    dx = -ux * local_pull * t
                    dy = -uy * local_pull * t
                    # plump perpendicular away from axis
                    side = (px - body_x) * nx + (py - body_y) * ny
                    if abs(side) >= 1.0:
                        s = 1.0 if side > 0 else -1.0
                        dx += nx * s * local_plump * t
                        dy += ny * s * local_plump * t
                    prev = moves.get(j)
                    if prev is None or abs(dx) + abs(dy) > abs(prev[0]) + abs(prev[1]):
                        moves[j] = (dx, dy)
                tip_count += 1
            start = end + 1

        if moves:
            for i, (dx, dy) in moves.items():
                x, y = coords[i]
                coords[i] = (int(round(x + dx)), int(round(y + dy)))
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] free-end blunt: {tip_count} tips across {glyph_count} glyphs "
        f"(pull={LUO_FREE_END_BLUNT_PULL_EM}em, plump={LUO_FREE_END_BLUNT_PLUMP_EM}em, "
        f"chars={LUO_FREE_END_BLUNT_CHARS})"
    )


def luo_long_diag_thin(font: TTFont) -> None:
    """v0.4.12: slenderise long 撇/捺 toward the W04 diagonal weight.

    See the LUO_LONG_DIAG_THIN_* constant block. Each long diagonal edge
    chord of an outer contour shifts inward (ink side, i.e. right of the
    travel direction for the outer orientation used across this pipeline)
    by half the delta; interior off-curves move with their chord. Both
    edges of a stroke travel in opposite directions, so the stroke thins
    symmetrically about its own axis. Tip caps are short chords and never
    qualify, so the existing tapered tips are preserved.
    """
    if LUO_LONG_DIAG_THIN_EM <= 0:
        print("[luo] long-diag thin: skipped (delta=0)")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    skip_chars = (
        set(STRAIGHTEN_SKIP_CHARS)
        | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)
        | set(LUO_LONG_DIAG_THIN_SKIP_CHARS)
    )

    seg_count = 0
    glyph_count = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF):
            continue
        char = chr(cp)
        if char in skip_chars:
            continue

        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue

        # Graduated delta: full on simple glyphs (<=3 contours), lerped
        # down to the complex value by 8 contours. Complex glyphs already
        # carry graduated (lighter) bolden, so a flat delta over-thins them.
        t = min(1.0, max(0.0, (glyph.numberOfContours - 3) / 5.0))
        delta_em = LUO_LONG_DIAG_THIN_EM + (LUO_LONG_DIAG_THIN_EM_COMPLEX - LUO_LONG_DIAG_THIN_EM) * t
        half = delta_em * upm / 2.0

        coords = list(glyph.coordinates)
        flags = glyph.flags
        ends = glyph.endPtsOfContours

        all_xs = [c[0] for c in coords]
        all_ys = [c[1] for c in coords]
        glyph_w = max(all_xs) - min(all_xs)
        glyph_h = max(all_ys) - min(all_ys)
        if glyph_w <= 0 or glyph_h <= 0:
            continue
        min_chord_len = LUO_LONG_DIAG_THIN_MIN_RATIO * max(glyph_w, glyph_h)
        moves: dict[int, tuple[float, float]] = {}

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
                if not (LUO_LONG_DIAG_THIN_ANGLE_LO <= angle_off_h <= LUO_LONG_DIAG_THIN_ANGLE_HI):
                    continue
                # Ink sits right of travel for this pipeline's outer
                # orientation (see luo_horiz_cap_flatten: dx>0 = top edge).
                nx = dy / length
                ny = -dx / length

                # Round 9: only thin what is actually heavier than the floor.
                # 岁's long 撇 was 0.065em (W04 ~0.072-0.080em) and still lost
                # another 0.010em here. Cast from the chord middle along the
                # ink normal to the first crossing of the same contour.
                mxp, myp = (ax + bx) / 2.0, (ay + by) / 2.0
                poly = [coords[i] for i in range(start, end + 1)]
                width = None
                for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
                    ex, ey = x1 - x0, y1 - y0
                    den = nx * ey - ny * ex
                    if abs(den) < 1e-9:
                        continue
                    tt = ((x0 - mxp) * ey - (y0 - myp) * ex) / den
                    uu = ((x0 - mxp) * ny - (y0 - myp) * nx) / den
                    if 0.0 <= uu <= 1.0 and tt > 4.0 and (width is None or tt < width):
                        width = tt
                floor_w = LUO_LONG_DIAG_THIN_MIN_WIDTH_EM * upm
                if width is None or width <= floor_w:
                    continue
                half_here = min(half, (width - floor_w) / 2.0)

                # Round 7: fade the shift to zero toward a free end (tip or
                # corner). A flat shift also moved the tip vertex and cut
                # already-thin 撇/捺 ends into needles (交/多/岁/家/名). An end
                # that continues into a collinear chord (LXGW splits long
                # edges) keeps the full shift so the seam gets no notch.
                def _continues(i_other, i_here, before):
                    ox, oy = coords[i_other]
                    hx, hy = coords[i_here]
                    vx, vy = (hx - ox, hy - oy) if before else (ox - hx, oy - hy)
                    vl = math.hypot(vx, vy)
                    if vl < 1e-6:
                        return False
                    return (vx * dx + vy * dy) / (vl * length) > math.cos(math.radians(30.0))

                fade_a = not _continues(on_curve[k - 1], ia, True)
                fade_b = not _continues(on_curve[(k + 2) % num_oc], ib, False)
                ramp = LUO_LONG_DIAG_THIN_TIP_FADE_EM * upm

                idx = ia
                while True:
                    px, py = coords[idx]
                    along = ((px - ax) * dx + (py - ay) * dy) / length
                    w = 1.0
                    if fade_a:
                        w = min(w, max(0.0, along) / ramp)
                    if fade_b:
                        w = min(w, max(0.0, length - along) / ramp)
                    w = w * w * (3 - 2 * w)
                    sx = half_here * nx * w
                    sy = half_here * ny * w
                    prev = moves.get(idx)
                    if prev is None or (sx * sx + sy * sy) > (prev[0] ** 2 + prev[1] ** 2):
                        moves[idx] = (sx, sy)
                    if idx == ib:
                        break
                    idx += 1
                    if idx > end:
                        idx = start
                seg_count += 1

            start = end + 1

        if moves:
            for idx, (sx, sy) in moves.items():
                x, y = coords[idx]
                coords[idx] = (int(round(x + sx)), int(round(y + sy)))
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] long-diag thin: {seg_count} chords across {glyph_count} glyphs "
        f"(delta={LUO_LONG_DIAG_THIN_EM}em, angle=[{LUO_LONG_DIAG_THIN_ANGLE_LO},{LUO_LONG_DIAG_THIN_ANGLE_HI}])"
    )


def luo_gesture_body_contract(font: TTFont) -> None:
    """v0.4.12 prototype: shorten free horizontal ends so the body tightens
    while main strokes keep their reach (see constant block)."""
    if LUO_GESTURE_H_SHORTEN_EM <= 0 or not LUO_GESTURE_BODY_CHARS:
        print("[luo] gesture body contract: skipped")
        return
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    delta = LUO_GESTURE_H_SHORTEN_EM * upm
    taper = LUO_GESTURE_TAPER_EM * upm
    max_drop = LUO_GESTURE_CAP_MAX_DROP_EM * upm
    min_drop = LUO_GESTURE_CAP_MIN_DROP_EM * upm
    x_window = LUO_GESTURE_CAP_X_WINDOW_EM * upm

    cap_count = 0
    touched_count = 0
    skip_chars = (
        set(STRAIGHTEN_SKIP_CHARS)
        | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)
        | set(LUO_GESTURE_SKIP_CHARS)
    )

    if LUO_GESTURE_BODY_CHARS == "all":
        rcmap = _build_reverse_cmap(font)
        char_iter = [
            chr(cp)
            for gname in font.getGlyphOrder()
            if (cp := rcmap.get(gname)) is not None and 0x3400 <= cp <= 0x9FFF
        ]
    else:
        char_iter = list(LUO_GESTURE_BODY_CHARS)

    for char in char_iter:
        if char in skip_chars:
            continue
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
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
        glyph_ymin = min(all_ys)
        if glyph_w <= 0 or glyph_h <= 0:
            continue
        # Flat single-stroke glyphs (一/二-style rows) are all main stroke.
        if glyph_h < LUO_GESTURE_FLAT_GLYPH_RATIO * glyph_w:
            continue
        min_chord = LUO_GESTURE_MIN_CHORD_RATIO * glyph_w
        # (contour_range, band_lo, band_hi, cap_x, side) side=+1 right cap
        caps: list[tuple[int, int, float, float, float, int]] = []

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

            # Merge consecutive near-horizontal on-curve chords into runs:
            # LXGW subdivides long edges, so a single-chord length test
            # misses most caps. A run qualifies by TOTAL length.
            # 2 = short wildcard segment: joins whichever run it sits inside
            # (LXGW edges carry micro-steps that must not break the chain).
            seg_dir: list[int] = []  # +1 top-edge segment, -1 bottom, 0 other
            seg_len: list[float] = []
            for k in range(num_oc):
                ia = on_curve[k]
                ib = on_curve[(k + 1) % num_oc]
                ax, ay = coords[ia]
                bx, by = coords[ib]
                dx = bx - ax
                dy = by - ay
                length = math.hypot(dx, dy)
                seg_len.append(length)
                if length < 60.0:
                    seg_dir.append(2)
                elif dx == 0 or math.degrees(math.atan2(abs(dy), abs(dx))) > 14.0:
                    seg_dir.append(0)
                else:
                    seg_dir.append(1 if dx > 0 else -1)

            tops: list[tuple[int, int]] = []
            bottoms: list[tuple[int, int]] = []
            k = 0
            while k < num_oc:
                d0 = seg_dir[k]
                if d0 in (0, 2):
                    k += 1
                    continue
                j = k
                total = 0.0
                while j < num_oc and (seg_dir[j] == d0 or seg_dir[j] == 2):
                    total += seg_len[j]
                    j += 1
                # Trim trailing wildcards off the run end so the cap walk
                # starts from the last real directional segment.
                jj = j
                while jj > k and seg_dir[jj - 1] == 2:
                    jj -= 1
                if total >= min_chord:
                    run_start = on_curve[k]
                    run_end = on_curve[jj % num_oc]
                    run_y = (coords[run_start][1] + coords[run_end][1]) / 2.0
                    is_main_bottom = (
                        total >= LUO_GESTURE_MAIN_H_MIN_W * glyph_w
                        and run_y < glyph_ymin + LUO_GESTURE_MAIN_H_BAND * glyph_h
                    )
                    if not is_main_bottom:
                        (tops if d0 > 0 else bottoms).append((run_start, run_end))
                k = j

            # Cap confirmation uses ANY correctly-directed near-horizontal
            # segment start on the far side — the long-run requirement
            # applies only to the side that establishes the stroke (文's
            # bottom-right edge stub after the 撇 junction is 375u and must
            # still confirm the right cap).
            bottom_starts = set()
            top_starts = set()
            for k in range(num_oc):
                ia = on_curve[k]
                ib = on_curve[(k + 1) % num_oc]
                dxs = coords[ib][0] - coords[ia][0]
                dys = coords[ib][1] - coords[ia][1]
                if abs(dxs) < 20 or math.degrees(math.atan2(abs(dys), abs(dxs))) > 20.0:
                    continue
                if dxs < 0:
                    bottom_starts.add(ia)
                else:
                    top_starts.add(ia)

            def _walk(idx: int) -> int:
                idx += 1
                if idx > end:
                    idx = start
                return idx

            # Right caps: end of a top chord -> start of a bottom chord.
            # drop >= min_drop is a full cap (shorten only); a smaller drop
            # is a needle terminal (LXGW tapered exit) — Tang's screenshots
            # flagged those as "针尖" on 里's middle bars, so needles also
            # get a local vertical re-inflate toward full stroke thickness.
            for _ia, ib in tops:
                bx, by = coords[ib]
                idx = ib
                ok = None
                for _ in range(16):
                    idx = _walk(idx)
                    px, py = coords[idx]
                    if abs(px - bx) > x_window:
                        break
                    # The walk climbing well above the top edge means the
                    # stroke turns up into a hook (绝/色 竖弯钩), not a cap.
                    if py > by + max_drop:
                        break
                    if idx in bottom_starts:
                        drop = by - py
                        if -10 <= drop <= max_drop:
                            ok = idx
                        break
                if ok is None:
                    continue
                drop = by - coords[ok][1]
                needle_c = (by + coords[ok][1]) / 2.0 if drop < min_drop else None
                cy_lo = coords[ok][1] - 30
                cy_hi = by + 30
                cap_x = max(bx, coords[ok][0])
                caps.append((start, end, cy_lo, cy_hi, cap_x, +1, needle_c))
                cap_count += 1

            # Left caps: end of a bottom chord -> start of a top chord.
            for _ia, ib in bottoms:
                bx, by = coords[ib]
                idx = ib
                ok = None
                for _ in range(16):
                    idx = _walk(idx)
                    px, py = coords[idx]
                    if abs(px - bx) > x_window:
                        break
                    if idx in top_starts:
                        rise = py - by
                        if -10 <= rise <= max_drop:
                            ok = idx
                        break
                if ok is None:
                    continue
                rise = coords[ok][1] - by
                needle_c = (by + coords[ok][1]) / 2.0 if rise < min_drop else None
                cy_lo = by - 30
                cy_hi = coords[ok][1] + 30
                cap_x = min(bx, coords[ok][0])
                caps.append((start, end, cy_lo, cy_hi, cap_x, -1, needle_c))
                cap_count += 1

            start = end + 1

        if not caps:
            continue
        moves: dict[int, float] = {}
        y_moves: dict[int, float] = {}
        inflate_zone = 0.10 * upm
        for cstart, cend, y_lo, y_hi, cap_x, side, needle_c in caps:
            for i in range(cstart, cend + 1):
                px, py = coords[i]
                if not (y_lo <= py <= y_hi):
                    continue
                if side > 0:
                    zone = px - (cap_x - taper)
                    if zone <= 0:
                        continue
                    shift = -delta * min(1.0, zone / taper)
                else:
                    zone = (cap_x + taper) - px
                    if zone <= 0:
                        continue
                    shift = delta * min(1.0, zone / taper)
                prev = moves.get(i)
                if prev is None or abs(shift) > abs(prev):
                    moves[i] = shift
                # Needle terminals additionally re-inflate vertically so
                # the tapered exit reads as a full-thickness print-kai cut.
                if needle_c is not None:
                    if side > 0:
                        t = (px - (cap_x - inflate_zone)) / inflate_zone
                    else:
                        t = ((cap_x + inflate_zone) - px) / inflate_zone
                    t = max(0.0, min(1.0, t))
                    if t > 0:
                        k = 1.0 + 0.45 * t
                        dy_shift = (py - needle_c) * (k - 1.0)
                        prev_y = y_moves.get(i)
                        if prev_y is None or abs(dy_shift) > abs(prev_y):
                            y_moves[i] = dy_shift
        if moves or y_moves:
            for i, shift in moves.items():
                x, y = coords[i]
                coords[i] = (int(round(x + shift)), y)
            for i, dy_shift in y_moves.items():
                x, y = coords[i]
                coords[i] = (x, int(round(y + dy_shift)))
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            touched_count += 1

    print(
        f"[luo] gesture body contract: {cap_count} free caps across "
        f"{touched_count} glyphs (shorten={LUO_GESTURE_H_SHORTEN_EM}em)"
    )


def luo_small_stroke_plump(font: TTFont) -> None:
    """v0.4.12: re-inflate slash-thin small strokes toward W04's plump ticks.

    Tang's screenshot circles landed on 来's side ticks and 觉's top
    strokes: LXGW draws them as tapered slashes, and the v0.4.12 global
    thinning made them read as blades. The reference (and 卫夫人's 点如
    坠石) keeps small strokes short but WEIGHTY. For each small elongated
    outer contour whose average thickness (area / long dimension) falls
    below the floor, scale it up along its minor principal axis around its
    centroid. Round dots (aspect < 1.7) are left to the dot channel.
    """
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    floor_t = LUO_SMALL_PLUMP_FLOOR_EM * upm
    max_dim_gate = 0.24 * upm
    skip_chars = set(STRAIGHTEN_SKIP_CHARS) | set(LUO_HORIZ_CAP_FLATTEN_FROZEN_CHARS)

    plump_count = 0
    glyph_count = 0

    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF):
            continue
        char = chr(cp)
        if char in skip_chars:
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
            if n < 4:
                start = end + 1
                continue
            signed = _contour_signed_area(coords, start, end)
            if signed >= 0:
                start = end + 1
                continue
            pts = [coords[i] for i in range(start, end + 1)]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            long_dim = max(w, h)
            if long_dim <= 0 or long_dim > max_dim_gate or long_dim < 0.04 * upm:
                start = end + 1
                continue
            area = abs(signed)
            avg_t = area / long_dim
            if avg_t <= 0 or avg_t >= floor_t or long_dim / max(avg_t, 1.0) < 1.7:
                start = end + 1
                continue
            k = min(LUO_SMALL_PLUMP_MAX_SCALE, floor_t / avg_t)
            if k < 1.05:
                start = end + 1
                continue
            # Principal axis via the 2x2 covariance of the contour points.
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            sxx = sum((x - cx) ** 2 for x in xs)
            syy = sum((y - cy) ** 2 for y in ys)
            sxy = sum((x - cx) * (y - cy) for x, y in pts)
            theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
            ux, uy = math.cos(theta), math.sin(theta)  # major axis
            vx, vy = -uy, ux  # minor axis
            for i in range(start, end + 1):
                x, y = coords[i]
                du = (x - cx) * ux + (y - cy) * uy
                dv = ((x - cx) * vx + (y - cy) * vy) * k
                coords[i] = (
                    int(round(cx + du * ux + dv * vx)),
                    int(round(cy + du * uy + dv * vy)),
                )
            plump_count += 1
            glyph_touched = True
            start = end + 1

        if glyph_touched:
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            glyph_count += 1

    print(
        f"[luo] small stroke plump: {plump_count} contours across "
        f"{glyph_count} glyphs (floor={LUO_SMALL_PLUMP_FLOOR_EM}em)"
    )


def luo_face_narrow(font: TTFont) -> None:
    """v0.4.12: per-char face narrowing for the overlay-flagged wide set."""
    if not LUO_FACE_NARROW_CHARS:
        return
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    touched: list[str] = []
    for char, factor in LUO_FACE_NARROW_CHARS.items():
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
        _x_min, _x_max, _y_min, _y_max, _gw, _gh, cx, _cy = box
        for i in range(len(coords)):
            x, y = coords[i]
            coords[i] = (int(round(cx + (x - cx) * factor)), y)
        glyph.recalcBounds(glyf)
        touched.append(char)
    if touched:
        print(f"[luo] face narrow: {''.join(touched)}")


def luo_dense_ink_relief(font: TTFont) -> None:
    """v0.4.12: thin long vertical chords on the audit's over-dense chars.

    See the LUO_DENSE_INK_RELIEF constant block. Chord-shift mechanics are
    identical to luo_long_diag_thin, restricted to near-vertical long
    chords, including hole contours so counters open while strokes thin.
    """
    if LUO_DENSE_INK_RELIEF_EM <= 0:
        print("[luo] dense-ink relief: skipped (delta=0)")
        return
    tier_by_char: dict[str, float] = {}
    for tier, chars in LUO_DENSE_INK_RELIEF_TIERS.items():
        for ch in chars:
            tier_by_char[ch] = tier
    skip = set(IDENTITY_FRAME_CHARS) | set(IDENTITY_FRAME_RISK_CHARS) | {"月"}

    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    seg_count = 0
    touched: list[str] = []
    # Round 16: the curated tiers only cover homepage chars; the full GB2312
    # set is dominated by dense level-2 glyphs (鬣/馨/齉). Any glyph with at
    # least AUTO_CONTOURS contours joins at AUTO_TIER.
    if LUO_DENSE_INK_AUTO_CONTOURS > 0:
        rc = _build_reverse_cmap(font)
        for gname in font.getGlyphOrder():
            cp = rc.get(gname)
            if cp is None or not (0x3400 <= cp <= 0x9FFF):
                continue
            ch = chr(cp)
            if ch not in tier_by_char and glyf[gname].numberOfContours >= LUO_DENSE_INK_AUTO_CONTOURS:
                tier_by_char[ch] = LUO_DENSE_INK_AUTO_TIER

    for char, tier in tier_by_char.items():
        if char in skip:
            continue
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        half = LUO_DENSE_INK_RELIEF_EM * tier * upm / 2.0
        coords = list(glyph.coordinates)
        flags = glyph.flags
        ends = glyph.endPtsOfContours
        box = _glyph_box(coords)
        if box is None:
            continue
        _x_min, _x_max, _y_min, _y_max, _gw, glyph_h, _cx, _cy = box
        if glyph_h <= 0:
            continue
        min_chord_len = 0.22 * glyph_h
        moves: dict[int, tuple[float, float]] = {}

        start = 0
        for end in ends:
            n = end - start + 1
            if n < 4:
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
                if angle_off_h < 76.0:
                    continue
                nx = dy / length
                ny = -dx / length
                sx = half * nx
                sy = half * ny
                idx = ia
                while True:
                    prev = moves.get(idx)
                    if prev is None or (sx * sx + sy * sy) > (prev[0] ** 2 + prev[1] ** 2):
                        moves[idx] = (sx, sy)
                    if idx == ib:
                        break
                    idx += 1
                    if idx > end:
                        idx = start
                seg_count += 1
            start = end + 1

        if moves:
            for idx, (sx, sy) in moves.items():
                x, y = coords[idx]
                coords[idx] = (int(round(x + sx)), int(round(y + sy)))
            for i, c in enumerate(coords):
                glyph.coordinates[i] = c
            glyph.recalcBounds(glyf)
            touched.append(char)

    print(
        f"[luo] dense-ink relief: {seg_count} chords across {len(touched)} glyphs "
        f"(max delta={LUO_DENSE_INK_RELIEF_EM}em)"
    )


def luo_char_posture_lift(font: TTFont) -> None:
    """v0.4.12: whole-glyph vertical translate for audit posture residuals."""
    if not LUO_CHAR_POSTURE_LIFT:
        return
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    touched: list[str] = []
    for char, lift_em in LUO_CHAR_POSTURE_LIFT.items():
        gname = cmap.get(ord(char))
        if not gname or gname not in glyf:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        dy = int(round(lift_em * upm))
        if dy == 0:
            continue
        coords = glyph.coordinates
        for i in range(len(coords)):
            x, y = coords[i]
            coords[i] = (x, y + dy)
        glyph.recalcBounds(glyf)
        touched.append(char)
    if touched:
        print(f"[luo] char posture lift: {''.join(touched)}")


def luo_diag_endpoint_clean(font: TTFont) -> None:
    """Lightly tuck chunky diagonal tails on simple W04 comparison glyphs."""
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    touched: list[str] = []

    for char in LUO_DIAG_ENDPOINT_CLEAN_CHARS:
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
        x_min, _x_max, y_min, _y_max, glyph_w, glyph_h, cx, _cy = box
        glyph_touched = False

        for c in _contour_info(glyph, coords):
            signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
            if signed > 0:
                continue
            for i in range(int(c["start"]), int(c["end"]) + 1):
                x, y = coords[i]
                xn = (x - x_min) / max(1.0, glyph_w)
                yn = (y - y_min) / max(1.0, glyph_h)
                if yn > 0.34:
                    continue
                left_t = max(0.0, (0.38 - xn) / 0.38)
                right_t = max(0.0, (xn - 0.62) / 0.38)
                side_t = max(left_t, right_t)
                if side_t <= 0:
                    continue
                bottom_t = (0.34 - yn) / 0.34
                t = side_t * bottom_t
                inward = min(0.010 * upm * t, 18.0)
                lift = min(0.004 * upm * t, 8.0)
                new_x = x + inward if x < cx else x - inward
                new_y = y + lift
                new_xy = (int(round(new_x)), int(round(new_y)))
                if new_xy != tuple(coords[i]):
                    coords[i] = new_xy
                    glyph_touched = True

        if glyph_touched:
            glyph.recalcBounds(glyf)
            touched.append(char)

    if touched:
        print(f"[luo] diagonal endpoint clean: {''.join(touched)}")


def luo_posture_contain(font: TTFont) -> None:
    """v0.4.12: global vertical posture toward the print-kai reference.

    Uniform affine on every CJK glyph: y' = pivot + s * (y - pivot) with
    pivot = LUO_POSTURE_PIVOT_EM (em above baseline) and
    s = LUO_POSTURE_SCALE_Y. Points above the pivot move up slightly, points
    below move up more; the whole face contracts toward the pivot, which
    raises the ink centroid, pulls the bottom edge in toward the baseline,
    and trims bbox height back to the reference band. Runs as the LAST
    outline pass so every earlier pass works in the original coordinates.

    `月` (the v0.4.8 frozen anchor) is transformed like everything else; the
    frozen invariant moves from "identical points to the v0.3 baseline" to
    "affine-equivalent under this posture transform" (see
    scripts/check_frozen_glyphs.py).
    """
    if LUO_POSTURE_SCALE_Y >= 1.0:
        print("[luo] posture contain: skipped (scale>=1)")
        return
    glyf = font["glyf"]
    rcmap = _build_reverse_cmap(font)
    upm = font["head"].unitsPerEm
    pivot = LUO_POSTURE_PIVOT_EM * upm
    s = LUO_POSTURE_SCALE_Y

    glyph_count = 0
    for gname in font.getGlyphOrder():
        cp = rcmap.get(gname)
        if cp is None or not (0x3400 <= cp <= 0x9FFF):
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours <= 0:
            continue
        coords = glyph.coordinates
        for i in range(len(coords)):
            x, y = coords[i]
            coords[i] = (x, int(round(pivot + s * (y - pivot))))
        glyph.recalcBounds(glyf)
        glyph_count += 1

    print(
        f"[luo] posture contain: {glyph_count} glyphs "
        f"(pivot={LUO_POSTURE_PIVOT_EM}em, scale_y={s})"
    )


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
        orig_coords = list(coords)
        ends = glyph.endPtsOfContours
        glyph_touched = False

        start = 0
        for end in ends:
            n = end - start + 1
            if n < 12:
                start = end + 1
                continue
            # Round 16: dots (宀/氵 small contours) have no hook; their bottom
            # corner was read as one and tapered into a dimple.
            _xs = [coords[i][0] for i in range(start, end + 1)]
            _ys = [coords[i][1] for i in range(start, end + 1)]
            if max(max(_xs) - min(_xs), max(_ys) - min(_ys)) < HOOK_TAIL_MIN_CONTOUR_EM * font["head"].unitsPerEm:
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

                # Round 16: a real hook flicks upward after the knee (竖钩,
                # 横折钩, 竖弯钩). Dot corners (宀's left dot) and 横撇 turns
                # (子) leave sideways or downward and were being tapered into
                # a dimple and a waist.
                if d_out_y < HOOK_TAIL_MIN_RISE * len_out:
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

                hook_capped_here = False
                for k in range(1, HOOK_TAIL_CAP_SAMPLES + 1):
                    sample_j = (j + k) % n
                    sample_idx = start + sample_j

                    # v0.4.12 taper: the width budget narrows linearly from
                    # stem width at the knee toward TIP_FACTOR x stem at the
                    # last sample, so tails end slender instead of club-blunt.
                    # Curved hooks (>=80°, 竖弯钩/弯钩) keep a plumper floor:
                    # Tang's screenshot flagged 觉's tail thinning into a
                    # wispy knot at the deep-taper setting.
                    tip_factor = LUO_HOOK_TAIL_TAPER_TIP
                    if angle >= 80.0:
                        tip_factor = max(tip_factor, 0.70)
                    taper = 1.0 - (1.0 - tip_factor) * (
                        k / float(HOOK_TAIL_CAP_SAMPLES)
                    )
                    target_width = stem_width * taper
                    cap_threshold = target_width * (1.0 + HOOK_TAIL_CAP_TOLERANCE)

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

                    excess = local_width - target_width
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
            # Round 16: several detected "hooks" can push the same point
            # (宀 left dot, 子 turn in 字); clamp the total move per point so
            # overlapping pushes cannot stack into a nub or a waist.
            lim = HOOK_TAIL_CAP_MAX_PUSH
            for i, (c, o) in enumerate(zip(coords, orig_coords)):
                dx, dy = c[0] - o[0], c[1] - o[1]
                d = math.hypot(dx, dy)
                if d > lim:
                    coords[i] = (int(round(o[0] + dx * lim / d)), int(round(o[1] + dy * lim / d)))
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


# Note: the v0.4.11 luo_horiz_cap_flatten replacement lives near the
# canonical pre-existing whitelist version below. This stub is intentionally
# left as a no-op marker; do not call it.


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


def luo_top_bottom_separate(font: TTFont) -> None:
    """v0.4.7: open the gap between upper and lower outer halves.

    The site-wide audit on 1,118 page glyphs showed about a third of the
    "no special whitelist" generic glyphs match a clean top-bottom layout
    (盘 / 孟 / 官 / 单 / 盏 / 答 / 案 / 室 / 客 ...) where one outer contour sits
    in the upper band and another sits in the lower band with no dense
    middle layer. Print-kai prefers a clearly visible gap between the two
    halves; LXGW WenKai reads slightly more compressed because the soft
    bow blurs the boundary.

    Detection (per outer contour, signed_area <= 0):
      - upper layer: centroid Y >= y_min + LUO_TOP_BOTTOM_TOP_BAND * gh
      - lower layer: centroid Y <= y_min + LUO_TOP_BOTTOM_BOT_BAND * gh
      - each layer's area >= LUO_TOP_BOTTOM_MIN_AREA fraction of glyph bbox
    The glyph is skipped when 2+ outer contours sit in the middle band
    with area >= LUO_TOP_BOTTOM_MID_BLOCK_AREA, so 三-style stacked-three
    layouts and densely-middle glyphs are not over-compressed.

    Action: shift each upper contour up by LUO_TOP_BOTTOM_LIFT_EM and
    lightly contract its width by LUO_TOP_BOTTOM_TOP_SCALE_X around its
    own centroid; settle each lower contour down by LUO_TOP_BOTTOM_SETTLE_EM
    and y-scale by LUO_TOP_BOTTOM_BOT_SCALE_Y around its own centroid. The
    y-scale on the bottom is presence-floor guarded against
    WEB_PRESENCE_H_MIN_EM so body horizontals never disappear.

    Skipped on the dedicated channels that already shape top-bottom
    geometry: STRAIGHTEN_SKIP (心字底 / 走之底 dedicated), HEART_CHARS,
    WALK_FINAL_CHARS, IDENTITY_FRAME_CHARS, KAI_BALANCE_ROOF_CHARS,
    KAI_BALANCE_STACK_CHARS. Combined with the existing v0.4.5
    luo_bottom_anchor_settle (wide-foot only), this completes the
    top-bottom hierarchy story without naming glyphs.
    """
    if (
        LUO_TOP_BOTTOM_LIFT_EM <= 0
        and LUO_TOP_BOTTOM_SETTLE_EM <= 0
        and LUO_TOP_BOTTOM_BOT_SCALE_Y >= 1.0
        and LUO_TOP_BOTTOM_TOP_SCALE_X >= 1.0
    ):
        print("[luo] top-bottom separate: skipped (identity)")
        return
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    upm = font["head"].unitsPerEm
    h_min = WEB_PRESENCE_H_MIN_EM * upm
    lift_units = LUO_TOP_BOTTOM_LIFT_EM * upm
    settle_units = LUO_TOP_BOTTOM_SETTLE_EM * upm
    # v0.4.10 fix: CORE_LAYER chars get the dedicated `_identity_core_layer_gap`
    # (0.010em up + 0.007em down ≈ 41 units total spread). Without this skip,
    # 章/重/第 etc. would also eat the v0.4.7 lift+settle (~17 units), netting
    # ~58 units of vertical separation that reads as "上下间隔太开" at 96px+.
    # Mirror pattern from `luo_frame_inner_open` / `luo_inner_counter_open`
    # which already skip IDENTITY_CORE_V2_CHARS for the same surgical reason.
    skip = (
        set(STRAIGHTEN_SKIP_CHARS)
        | set(IDENTITY_FRAME_CHARS)
        | set(KAI_BALANCE_ROOF_CHARS)
        | set(KAI_BALANCE_STACK_CHARS)
        | set(HEART_CHARS)
        | set(WALK_FINAL_CHARS)
        | set(IDENTITY_CORE_LAYER_CHARS)
    )
    upper_count = 0
    lower_count = 0
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
        if glyph_area <= 0:
            continue
        contours = _contour_info(glyph, coords)
        outers = [
            c for c in contours
            if _contour_signed_area(coords, int(c["start"]), int(c["end"])) <= 0
        ]
        if len(outers) < 2:
            continue
        top_band_y = y_min + glyph_h * LUO_TOP_BOTTOM_TOP_BAND
        bot_band_y = y_min + glyph_h * LUO_TOP_BOTTOM_BOT_BAND
        upper = [
            c for c in outers
            if float(c["cy"]) >= top_band_y
            and float(c["area"]) >= glyph_area * LUO_TOP_BOTTOM_MIN_AREA
        ]
        lower = [
            c for c in outers
            if float(c["cy"]) <= bot_band_y
            and float(c["area"]) >= glyph_area * LUO_TOP_BOTTOM_MIN_AREA
        ]
        if not upper or not lower:
            continue
        # Avoid firing on glyphs with substantial middle content (三 / 重 / 王
        # style stacked layouts where shifting the outer two would crush
        # the middle layer).
        middle_block = [
            c for c in outers
            if bot_band_y < float(c["cy"]) < top_band_y
            and float(c["area"]) >= glyph_area * LUO_TOP_BOTTOM_MID_BLOCK_AREA
        ]
        if len(middle_block) >= 2:
            continue
        glyph_touched = False
        for c in upper:
            c_w = max(1.0, float(c["xmax"]) - float(c["xmin"]))
            sx = _presence_guarded_scale(LUO_TOP_BOTTOM_TOP_SCALE_X, c_w, h_min)
            _scale_contour(coords, c, scale_x=sx, shift_y=lift_units)
            upper_count += 1
            glyph_touched = True
        for c in lower:
            c_h = max(1.0, float(c["ymax"]) - float(c["ymin"]))
            sy = _presence_guarded_scale(LUO_TOP_BOTTOM_BOT_SCALE_Y, c_h, h_min)
            _scale_contour(coords, c, scale_y=sy, shift_y=-settle_units)
            lower_count += 1
            glyph_touched = True
        if glyph_touched:
            glyph.recalcBounds(glyf)
            glyph_count += 1
    print(
        f"[luo] top-bottom separate: {upper_count} upper + {lower_count} lower "
        f"contours across {glyph_count} glyphs "
        f"(lift={LUO_TOP_BOTTOM_LIFT_EM}em, settle={LUO_TOP_BOTTOM_SETTLE_EM}em, "
        f"bot_y={LUO_TOP_BOTTOM_BOT_SCALE_Y}, top_x={LUO_TOP_BOTTOM_TOP_SCALE_X})"
    )


def luo_frame_inner_open(font: TTFont) -> None:
    """v0.4.7: open the off-center inner counters of frame-with-content glyphs.

    The existing v0.4.6 luo_inner_counter_open targets only counters whose
    centroid X falls in the middle band [LUO_INNER_COUNTER_BAND_LO,
    LUO_INNER_COUNTER_BAND_HI]. Glyphs like 田 (four quadrant counters)
    and 自 / 角 / 由 (broad outer hull with internal layout) leave their
    inner counters un-opened because those counters sit outside the
    middle band. This pass picks up only the off-center counters in
    frame-with-content topology and applies a smaller expansion than the
    main inner_counter_open pass (1.014 / 1.008 vs 1.040 / 1.020) so it
    does not over-stretch the typical kai grid.

    Detection (per glyph):
      - the largest outer contour's bbox spans at least
        LUO_FRAME_INNER_OUTER_W * gw and LUO_FRAME_INNER_OUTER_H * gh
        (i.e. the glyph has a clear "frame hull")
      - at least one inner contour (signed_area > 0) sits with its
        centroid X outside [BAND_LO, BAND_HI] (so we do not double-stack
        on luo_inner_counter_open) and its area in
        [LUO_FRAME_INNER_MIN_AREA, LUO_FRAME_INNER_MAX_AREA]

    Skipped on the dedicated channels that already restructure the
    frame: STRAIGHTEN_SKIP_CHARS, IDENTITY_FRAME_CHARS,
    IDENTITY_CORE_V2_CHARS.
    """
    if LUO_FRAME_INNER_X <= 1.0 and LUO_FRAME_INNER_Y <= 1.0:
        print("[luo] frame-inner open: skipped (identity)")
        return
    glyf = font["glyf"]
    cmap = _build_cmap(font)
    skip = (
        set(STRAIGHTEN_SKIP_CHARS)
        | set(IDENTITY_FRAME_CHARS)
        | set(IDENTITY_CORE_V2_CHARS)
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
        x_min, _x_max, _y_min, _y_max, glyph_w, glyph_h, _cx, _cy = box
        glyph_area = glyph_w * glyph_h
        if glyph_area <= 0:
            continue
        contours = _contour_info(glyph, coords)
        outers = [
            c for c in contours
            if _contour_signed_area(coords, int(c["start"]), int(c["end"])) <= 0
        ]
        if not outers:
            continue
        # Largest outer hull = frame candidate.
        largest = max(
            outers,
            key=lambda c: (float(c["xmax"]) - float(c["xmin"]))
            * (float(c["ymax"]) - float(c["ymin"])),
        )
        hull_w = float(largest["xmax"]) - float(largest["xmin"])
        hull_h = float(largest["ymax"]) - float(largest["ymin"])
        if hull_w < glyph_w * LUO_FRAME_INNER_OUTER_W:
            continue
        if hull_h < glyph_h * LUO_FRAME_INNER_OUTER_H:
            continue
        band_lo = x_min + glyph_w * LUO_INNER_COUNTER_BAND_LO
        band_hi = x_min + glyph_w * LUO_INNER_COUNTER_BAND_HI
        glyph_touched = False
        for c in contours:
            signed = _contour_signed_area(coords, int(c["start"]), int(c["end"]))
            if signed <= 0:
                continue
            cc_x = float(c["cx"])
            # Skip the middle-band counters that luo_inner_counter_open
            # already handles to avoid double-stacking.
            if band_lo <= cc_x <= band_hi:
                continue
            area = float(c["area"])
            if area < glyph_area * LUO_FRAME_INNER_MIN_AREA:
                continue
            if area > glyph_area * LUO_FRAME_INNER_MAX_AREA:
                continue
            # Counter must sit inside the frame hull horizontally (otherwise
            # it is not really an interior counter of the frame).
            if (
                float(c["xmin"]) < float(largest["xmin"]) - 1
                or float(c["xmax"]) > float(largest["xmax"]) + 1
            ):
                continue
            _scale_contour(coords, c, scale_x=LUO_FRAME_INNER_X, scale_y=LUO_FRAME_INNER_Y)
            seg_count += 1
            glyph_touched = True
        if glyph_touched:
            glyph.recalcBounds(glyf)
            glyph_count += 1
    print(
        f"[luo] frame-inner open: {seg_count} counters across {glyph_count} glyphs "
        f"(outer_min={LUO_FRAME_INNER_OUTER_W}x{LUO_FRAME_INNER_OUTER_H}, "
        f"x={LUO_FRAME_INNER_X}, y={LUO_FRAME_INNER_Y})"
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
    luo_horiz_kink_join(font)

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
    luo_top_bottom_separate(font)
    luo_frame_inner_open(font)
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
    luo_homepage_p6_left_right(font)
    luo_curve_tail_polish(font)
    luo_horiz_cap_flatten(font)
    luo_frame_upright(font)
    # luo_frame_foot_tuck disabled: its y-clamp chops the bottom-left foot
    # flat (古/田/晋) and notches the 竖弯钩 tip (绝); six-dim bands hold without it.
    luo_long_horiz_thin(font)
    luo_stem_normalize(font)
    luo_long_diag_thin(font)
    luo_gesture_body_contract(font)
    luo_pie_tail_fill(font)
    luo_flick_taper(font)
    luo_na_modulate(font)
    luo_na_foot_swell(font)
    luo_smooth_shallow_corners(font)
    luo_horiz_weight_rescue(font)  # no-op when EM=0 / chars empty
    luo_free_end_blunt(font)  # no-op when pull=0 / chars empty
    luo_dense_ink_relief(font)
    luo_small_stroke_plump(font)
    luo_face_narrow(font)
    luo_char_posture_lift(font)
    luo_diag_endpoint_clean(font)
    luo_posture_contain(font)
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
