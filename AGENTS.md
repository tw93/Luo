# Luo 落文

Luo (落文) is a CJK reading/display typeface inspired by Wei Furen's bone-method calligraphy. SIL OFL 1.1.

## Build

```bash
pip install -r requirements.txt
python scripts/build.py          # starter mode: site + print + README + common chars
LUO_BUILD_CHARS=seed python scripts/build.py   # seed mode: diagnostic chars only
LUO_BUILD_CHARS=gb2312-level1 python scripts/build.py  # v0.4-alpha expansion
LUO_BUILD_CHARS=gb2312-full python scripts/build.py    # full GB2312 experiment
```

Output: `dist/Luo-Regular.{ttf,woff2}` (v0.3 dropped the misleading `.otf` that was just a TrueType outline in an OpenType sfnt; a real CFF build would ship as a separate product)

Side effects: `build.py` also patches four files with a cache-bust string derived from VERSION + woff2 sha8. Always commit these after a build that changes the font binary:
- `assets/styles/luo.css`
- `assets/styles/print.css`
- `index.html`
- `assets/asset_version.txt` (read by `scripts/catalog_chinese_fonts.py` for Vercel deploy; falls back to `"v0"` if absent)

Source font: `source/LXGWWenKaiScreen-Regular.ttf`

## Pipeline (order matches main() in scripts/build.py)

1. Subset to starter/site/seed characters, or explicit GB2312 expansion mode
2. Graduated stroke thickening (BOLDEN_H=6, BOLDEN_V=14, contour-scaled, dot-aware cap)
3. Endpoint softening (sharp corners to subtype soft-cuts: h / v_bottom / diag)
4. Stroke straightening with corner protection (long near-axis spans flatten LXGW bow; per-off-curve perp-ratio gate skips corner controls)
5. Complexity-aware horizontal narrowing + vertical face-ratio scaling (SCALE_Y=1.00)
6. Component-aware refinement (7 categories: enclosed, dense_top, wide_split, walk_enclosed, dense_complex, multi_horiz, top_bottom)
7. Heart-character reshape (special case: 心字底/旁)
8. Dot contour direction (xiaokai dot rotation + adaptive compression)
9. Kai component-balance refinement (氵旁降灰、密字开内白、`书` 右点收短)
9a. v0.4.6 typographic-kai abstractions (4 generic component refiners, no whitelists):
 bottom_anchor_settle (底盘下沉), left_radical_contain (左旁内收), inner_counter_open (内白舒展), dense_counter_tier (密字内白二阶)
9b. v0.4.7 typographic-kai abstractions (2 more generic component refiners, no whitelists):
 top_bottom_separate (上下层断隔), frame_inner_open (含框内白舒展)
10. Targeted turn refinement (priority endpoints / frames / multi-horiz only)
10b. Luo signature: long-h end micro-emphasis (luo_horiz_end_emphasis, geometric, no whitelist)
11. Dense dot-cluster protection (墨)
12. Hook refinement on whitelist (refine_hooks_final)
13. Geometric hook-tail width cap: tail outline width <= stem width at hook root (whitelist-free)
13b. Luo signature: hook-root inward handle (luo_hook_root_inward_handle, geometric, no whitelist)
14. Walk-radical final containment (透/道/遇/etc.)
15. Display anchor refinement (落/笔/见)
16. Identity refinement: HIGH_RISK + PRIORITY anchor glyphs + all-covered guardrails + identity_core_v2 whitelist
17. CJK punctuation proportional width (0.75em)
18. Space half-width (50%)
19. CJK spacing stays 1em by default for reading rhythm
20. Name table rewrite, write Luo-Regular.ttf and .woff2
21. Patch asset-version cache-bust strings in luo.css/print.css/index.html (derived from VERSION + woff2 sha8)

## Design Direction (v0.4 print-kai pivot)

Target: modern print-ready title font, typographic-kai gesture with Wei-Jin bone hint.

- **Style ratio: 60% private typographic-kai reference abstraction / 30% Wei-Jin xiaokai bone / 10% modern font engineering.** (v0.3 was 50/40/10; see HANDOFF.v0.3.md for the prior shape.)
- Strokes are decisive, near-line; LXGW WenKai's soft-kai bow is actively flattened by `straighten_strokes`. v0.4.2 adds `STRAIGHTEN_MAX_PERP_RATIO=0.18` so off-curve points sitting more than 18% perpendicular from the chord (the bao-gai right corner / 横折钩 right corner) are recognised as corner controls and left alone, instead of being dragged along the chord into a downward triangular spike.
- Site-priority glyphs must not merely be "the source font with more bone"; use the identity similarity + bow-distance report to find high-overlap glyphs, then solve with structure, counters, hierarchy, and terminals.
- Clean, upright, print-friendly, not calligraphic or handwritten.
- Hooks: short, decisive, directional, contained, no dragging. v0.4.1 web-body reduction: `HOOK_FINAL_SHORTEN=0.16`, `HOOK_FINAL_TIP_SHARPEN=0.18` with `HOOK_FINAL_TIP_SHARPEN_CURVED=0.10` for hooks turning ≥80° so 弯钩/竖弯钩 keep a continuous tail and don't read as two segments meeting at a sharp corner.
- Dots: short, wedge-like xiaokai dots; not round, not slash-like. v0.4.1 brings `DOT_SHORT_AXIS` back to 0.55 (the v0.3 value) after 0.50 made body-size dots break into chips on 地/发/亦/源.
- Endpoints: soft-cut but flatter, less round; `ENDPOINT_H_BLEND=0.025`, `ENDPOINT_DIAG_BLEND=0.020`.
- Turns: clear bone-node at every CJK glyph, but quieter on body text. v0.4.1 splits the displace: default `TURN_FINAL_DISPLACE=1.6` everywhere, `TURN_FINAL_PRIORITY_DISPLACE=2.2` only on the priority anchor list (`TURN_FINAL_CHARS`). Frame chars keep their own dedicated knobs.
- Strokes: horizontal lighter than vertical (H/V ratio ~0.43). v0.4.2 restores BOLDEN_H/V to the v0.3 baseline (6/14) after the v0.4.1 systemic rollback removed the compensating reductions and left the font globally too thin; the new stroke balance keeps the print-kai feel without making body text 发虚 again.
- Components: learn private typographic-kai reference hierarchy, not just straightness. 氵旁/secondary components should read lighter; dense glyphs need open counters; `落`/`书` anchors get local component balance before identity guards.

For batch glyph editing or handoff to another AI, use `STYLE.md` as the single source of truth. It contains the compact Luo style abstraction, positive/negative AI prompts, anchor glyph groups, and acceptance criteria. Do not invent a parallel style guide in another file.

## Coverage Roadmap

- v0.3 uses `LUO_BUILD_CHARS=starter` by default. It is a small, credible starter subset for the site, README, print proof, Lanting text, and priority anchors.
- Do not start broad coverage expansion inside v0.3 final. Keep v0.3 fixes scoped to visible specimen text, print checks, core anchors, and `proof/gb2312.html` usability.
- v0.4 expansion starts with `LUO_BUILD_CHARS=gb2312-level1`, then moves to `LUO_BUILD_CHARS=gb2312-full` only after level-1 glyphs are visually stable.
- `LUO_BUILD_CHARS=full` keeps the source font's full glyph set for bottom-up experiments; it is not the v0.4 GB2312 release path.
- `proof/gb2312.html` should expose only `已覆盖` and `待补字`. Optimization categories are engineering internals and should stay out of the public calibration grid.

## West Lake Stone Reference Boundary

Use the West Lake stone/tile lettering only as a local reminder for shortness and containment:

- Learn: short, dry, decisive hooks; crisp dot placement; firm turns; clean stops.
- Do not learn: running-script linkage, omitted strokes, drifting centers, stone texture, breakage, noise, tourist-sign decoration, ancient-style ornament.

Luo is still a modern printable typeface, not stone inscription revival.

## Engineering Principles

1. Fixed multipliers are input-blind. If an input attribute has a wide distribution, lerp toward identity as the input grows; the dot pass does this with source aspect.
2. Earlier passes can create non-linear divergence. If bolden has already stretched two similar dots differently, downstream dot shaping can narrow the gap but cannot fully erase it.
3. A soft channel means normalize lightly, not reshape. `DOT_SHORT_AXIS_SOFT=0.95` is intentional: 氵/讠 dots get angle normalization with near-identity compression.
4. Prefer generic parameter logic over char lists. Use lists only to skip a whole pass (`DOT_SKIP_CHARS`) or route to a truly different path (`HEART_CHARS`).
5. Similarity gates are QA signals, not a license to cheat with whole-glyph shifts. Regular site-priority glyphs target source IoU <= 0.60; extremely simple glyphs may pass up to 0.75 because their legal design space is naturally smaller.
6. Core source-separation must stay whitelist-based. `identity_core_v2` handles only frame, layered, and diagonal/long-slant groups; do not broaden it into another all-covered pass.

## v0.4 Unfrozen Parameters (retuned for print-kai pivot)

These v0.3 values were unfrozen for the v0.4 pivot. v0.3 baseline shown in parentheses. v0.4.1 reductions are flagged where the v0.4 launch values stacked into web-body damage and were rolled back. **v0.4.3 is a pure audit-driven 减法迭代 on top of v0.4.2: each affected knob was relaxed one notch toward identity to mitigate residual hook-tip spike, dot dropout, secondary-horizontal weakness, side-left starvation, and roof/stack bottom crush; no new pass, no new whitelist, no BOLDEN change.** **v0.4.4 widens Luo's structural distance from the source via three Luo-only signature features (long-h end micro-emphasis, hook-root inward handle, and a 14° → 17° dot rotation bump) plus 团 added to the frame whitelists. No BOLDEN change, no readability rollback. The 30-char anchor IoU vs LXGW is essentially unchanged at 384px raster (raw 0.748, centered 0.716) because the new features are sub-pixel at that raster, but they add real geometric distance LXGW does not have.** **v0.4.5 adds three generic component-level typographic-kai abstractions (bottom_anchor_settle, left_radical_contain, inner_counter_open). All three use topology-only triggers (signed area, centroid, aspect, area ratio), not character whitelists, and respect the v0.4.3 readability floor (`WEB_PRESENCE_DOT_MIN_EM` / `WEB_PRESENCE_H_MIN_EM`) plus the dedicated KAI_BALANCE / IDENTITY_FRAME / STRAIGHTEN_SKIP categories so they do not double-stack on glyphs already handled by per-category geometry. No BOLDEN change, no readability rollback. 30-char source IoU is essentially flat (raw 0.7504 → 0.7522, centered 0.7215 → 0.7206) for the same reason as v0.4.4: per-contour shifts of 5-10 units are sub-pixel at 256px raster. Visible structural progress shows up in the local private-reference queue: 径/次 leave the top-30 and 径(-0.132) 茫(-0.098) 泽(-0.078) 剑(-0.072) 式(-0.064) 给(-0.042) 今(-0.038) all move toward the print-kai gesture without regressing the homepage anchor set.** **v0.4.6 adds dense_counter_tier inside the same topology-only abstraction group: dense multi-contour glyphs with at least one middle counter and either multiple counters or dot-like component density get a second +1-2% counter opening. This targets homepage P0/P1 dense glyphs by structure, not by character name, and does not change BOLDEN, global weight, or the v0.4.3 readability floors.** **v0.4.7 adds two more topology-driven generic refiners (top_bottom_separate and frame_inner_open) targeting the residual ~70% of homepage chars that previously had no specialised pass at all. Site-wide audit on 1,118 homepage glyphs showed the "generic" bucket sitting at avg raw IoU 0.8411 vs LXGW while the various specialised buckets sat at 0.71-0.84; the two new passes pull the generic bucket to 0.8339 (-0.72 pts) and the OVERALL average to 0.8277 (-0.68 pts), with all six frozen pass buckets (frame / walk / heart / stack / roof + the v0.4.5 abstractions in their domain) staying at exact zero delta because the skip lists hold. No BOLDEN change, no readability rollback; magnitudes are deliberately small (≤0.005em / ≤2% scale) and presence-floor guarded.**

| Parameter | v0.4 (current) | (v0.3) | Purpose |
|-----------|------|--------|---------|
| BOLDEN_H | **6** (v0.4.2: was 5) | (6) | Horizontal stroke weight; v0.4.2 restores the v0.3 value because the v0.4.1 systemic rollback removed the compensating 减重 channels and left the font globally too thin. Combined with the new geometric corner protection in straighten_strokes, body text reads at the right灰度 without 发虚 at 12-19px. |
| BOLDEN_V | **14** (v0.4.2: was 13) | (14) | Vertical stroke weight; restored to the v0.3 baseline alongside BOLDEN_H. The v0.4 4/11 attempt was already known to undershoot; v0.4 5/13 + rolled-back compensators landed in the same 偏瘦 zone, so v0.4.2 returns to 6/14. |
| BOLDEN_DIAG_BONUS | 7.0 | (9.0) | Less 撇/捺 visual lift than v0.3 but a touch more than the initial v0.4=6. v0.4.2 verified that 文/之/来/兮/今/代/友/这 read with credible speed at the new 6/14 base; no further bonus reduction needed. |
| ENDPOINT_H_BLEND | 0.025 | (0.040) | Flatter horizontal terminals |
| ENDPOINT_DIAG_BLEND | 0.020 | (0.030) | Flatter 撇/捺 terminals |
| DOT_SHORT_AXIS | **0.55** (v0.4.1: was 0.50) | (0.55) | v0.4.1 returns to the v0.3 floor; 0.50 broke body dots into chips on 地/发/亦/源. WEB_PRESENCE_DOT_MIN_EM also raised to 0.150em (was 0.125em). |
| HOOK_FINAL_SHORTEN | **0.16** (v0.4.1: was 0.18) | (0.14) | Sits between v0.3 and earlier v0.4; web-body 弯钩 stops reading as two segments. |
| HOOK_FINAL_TIP_SHARPEN | **0.15** (v0.4.3: was 0.18) | (0.18) | v0.4.3 audit-driven reduction; 0.18 still produced visible 弯钩/横折钩 tip spikes on priority anchors at heading sizes. Curved hooks (≥80°) keep the softer 0.10 via `HOOK_FINAL_TIP_SHARPEN_CURVED`, which only sharpens the on-curve tip so the off-curve handle still draws a continuous tail. |
| HOOK_FINAL_TAIL_CONTAIN | **0.045** (v0.4.1: was 0.055) | (0.06) | Less axial pull-in; halved again for curved hooks. |
| TURN_FINAL_DISPLACE | **1.6** (v0.4.1: was 2.5) | (1.2) | Default bone-node is quieter on body text; sharp 折点 at hook roots and short-stroke joints (笔/书/览/无) is the symptom of 2.5 stacking with hook refinement. |
| TURN_FINAL_PRIORITY_DISPLACE | **1.9** (v0.4.3: was 2.2; new in v0.4.1) | — | v0.4.3 reduction; 2.2 still drove visible 钉头/折点 on priority anchors. The displace is kept only for chars in `TURN_FINAL_CHARS` (display anchors / multi-horiz / frames) where explicit 骨节 is desired at heading sizes. |
| TURN_FINAL_INNER | **0.955** (v0.4.1: was 0.94) | (0.96) | Default inner-corner tightening relaxed; priority chars use 0.94 via `TURN_FINAL_PRIORITY_INNER`. |
| TURN_FINAL_CHARS scope | full CJK | (~30 chars) | Bone-node for every CJK glyph; v0.4.1 reserves the stronger displace/inner only for the curated priority list. |
| IDENTITY_SIMPLE_FACE_X | 1.020 | (1.008) | Simple chars more open |
| IDENTITY_REGULAR_FACE_X | 1.012 | (1.004) | Regular chars more open |
| IDENTITY_ALL_TOP_CONTAIN | 0.985 | (0.992) | Top more contained |
| IDENTITY_ALL_BOTTOM_EXPAND | 1.012 | (1.004) | Bottom more grounded |
| IDENTITY_ALL_H_LAYER_X | **0.999** (v0.4.3: was 0.997) | — | v0.4.3 audit-driven nudge to near-identity; 0.997 still stacked with `MULTI_HORIZ_SECONDARY` and pulled body-text secondary horizontals weak. v0.4 originally stacked with 0.965 and pulled them down to ~0.96 in 无/东/亦/荒/起/代; both knobs were progressively raised to leave secondary 横画 readable. |
| IDENTITY_SIMPLE_H_LAYER_X | **0.995** (v0.4.1: was 0.990) | — | Same fix on simple glyphs. |
| MULTI_HORIZ_SECONDARY | **0.985** (v0.4.3: was 0.978) | — | v0.4.3 audit-driven raise; 0.978 still left secondary 横画 thin on body text once the H_LAYER_X factor was applied. v0.4 originally was 0.965 (pulled stroke ratio to ~0.96 alongside H_LAYER_X). |
| DOT_ROTATE_DEG | **17.0** (v0.4.4: was 14.0) | — | v0.4.4 widening: bump xiaokai 楔形点 rotation by 3° so dot direction reads further from LXGW's near-horizontal dots. Combines with `DOT_LONG_AXIS / DOT_SHORT_AXIS / DOT_RELAX_*`; soft channel (氵/讠) is already at near-identity so the bump only really shifts hard-channel dots. |
| IDENTITY_FRAME_CHARS | **国回图园日目月团** (v0.4.4: was 国回图园日目月) | — | v0.4.4 widening: 团 joins the frame whitelist (and `IDENTITY_CORE_V2_CHARS` / `IDENTITY_CORE_FRAME_CHARS`) so the v2 frame_posture stem-narrow + counter-expand language reaches it instead of being treated as a generic complex glyph. |
| LUO_BOTTOM_ANCHOR_SCALE_Y | **0.945** (new in v0.4.5) | n/a | v0.4.5 abstraction: outer contours sitting in the lower 36% of glyph height with aspect ≥ 1.5 or width ≥ 40% of glyph width and area in [1.5%, 30%] of glyph area get this Y compression around their own centroid. The "wide foot" topology covers most reading-grade kai 底盘下沉 cases without a character list. Skips frame chars and KAI_BALANCE_ROOF / STACK chars so 实/寒/库/头 keep their dedicated per-category 底盘 treatment. |
| LUO_BOTTOM_ANCHOR_LIFT_EM | **0.008** (new in v0.4.5) | n/a | Upward shift applied alongside the Y compression. The 8-unit lift opens space above the foot layer so the upper component reads slightly raised, matching the typographic-kai gesture of "底不沉". |
| LUO_LEFT_RADICAL_X | **0.940** (new in v0.4.5) | n/a | v0.4.5 abstraction: outer contours fully on the left half (xmax within 46% of glyph width) with aggregate area in [4%, 22%] are treated as a self-contained left radical and contracted around their centroid. Generalises the 11-char `KAI_BALANCE_SIDE_SPLIT_CHARS` whitelist to all glyphs with the same topology (往/径/征/敛/松/孤/雄/状...), while skipping the curated SIDE_SPLIT / SPEECH / WATER / FRAME char lists that already have dedicated geometry. |
| LUO_LEFT_RADICAL_Y | **0.975** (new in v0.4.5) | n/a | Companion to `LUO_LEFT_RADICAL_X`. The Y axis is held closer to identity than X so the left radical retains visible vertical extent while losing horizontal mass. |
| LUO_LEFT_RADICAL_GAP_EM | **0.006** (new in v0.4.5) | n/a | Rightward shift applied after the contraction. Opens the gap between the contained left radical and the right component, echoing the print-kai layout where left radicals sit clearly inside the left zone with breathing room on their inside edge. |
| LUO_INNER_COUNTER_X | **1.040** (new in v0.4.5) | n/a | v0.4.5 abstraction: inner counter contours (signed area > 0) whose centroid X falls in the middle horizontal third [30%, 70%] of glyph width and whose area is in [0.5%, 15%] of glyph area get a small horizontal expansion around their own centroid. Targets the residual middle-column over-inking pattern in dense / multi-component glyphs (言/试/调/诸/熹) that earlier passes did not fully resolve. Skips frame chars (already handled by `identity_core_v2`) and STRAIGHTEN_SKIP_CHARS. |
| LUO_INNER_COUNTER_Y | **1.020** (new in v0.4.5) | n/a | Companion vertical lift on the same counter band. Smaller than X because the dominant private-kai pattern is widened-but-still-tall counters; over-Y can pop counters into rounded shapes that do not match the print-kai geometry. |
| LUO_DENSE_COUNTER_MIN_CONTOURS / MIN_INNERS / DOT_MIN | **7 / 1 / 3** (new in v0.4.6) | n/a | v0.4.6 dense tier: after `inner_counter_open` identifies eligible middle counters, glyphs with at least 7 contours and either multiple eligible counters or at least 3 dot-like component contours get a second counter-only opening. This catches 籍/赢/魔/麟-style dense topology without naming glyphs or weakening the whole glyph. |
| LUO_DENSE_COUNTER_X / Y | **1.018 / 1.010** (new in v0.4.6) | n/a | Extra counter-only expansion for the dense tier. Kept below the main `LUO_INNER_COUNTER_X/Y` magnitude so it adds local white and layer rhythm without bursting counters in already-open frame glyphs. |
| LUO_TOP_BOTTOM_TOP_BAND / BOT_BAND | **0.62 / 0.38** (new in v0.4.7) | n/a | v0.4.7 abstraction: outer contours with cy in upper 38% (≥ 0.62) qualify as "upper layer", outers with cy in lower 38% (≤ 0.38) qualify as "lower layer". Glyphs with both qualifying layers (each ≥ 4% of glyph area) and no dense middle block get an upper-lift + lower-settle treatment to open the typographic-kai 上下层断隔. The 0.62/0.38 split keeps the middle band wide enough that 三-style stacked-three layouts and densely-middle glyphs are correctly skipped. |
| LUO_TOP_BOTTOM_LIFT_EM / SETTLE_EM | **0.005 / 0.004** (new in v0.4.7) | n/a | Upward shift on the upper layer and downward shift on the lower layer (in em). Sub-5-unit moves at typical EM are sub-pixel at body raster but accumulate visible "断隔" rhythm at heading sizes. Magnitudes deliberately matched so the visual gap roughly doubles compared to source without changing glyph bbox externally. |
| LUO_TOP_BOTTOM_BOT_SCALE_Y | **0.988** (new in v0.4.7) | n/a | Vertical compression on the lower layer around its own centroid. Combined with `SETTLE_EM`, gives a print-kai 底盘下沉 feel that is much lighter than `LUO_BOTTOM_ANCHOR_SCALE_Y=0.945` (which is reserved for the wide-foot topology). Presence-floor guarded against `WEB_PRESENCE_H_MIN_EM` so body horizontals never disappear. |
| LUO_TOP_BOTTOM_TOP_SCALE_X | **0.992** (new in v0.4.7) | n/a | Horizontal contraction on the upper layer. Sub-1% so the upper component visually reads as "tucked above" the lower without shrinking its silhouette. Skipped completely when the upper-layer width is too small to survive the contraction without falling under `WEB_PRESENCE_H_MIN_EM`. |
| LUO_TOP_BOTTOM_MIN_AREA / MID_BLOCK_AREA | **0.04 / 0.10** (new in v0.4.7) | n/a | Each candidate layer must occupy at least 4% of the glyph bbox. Two or more outer contours occupying ≥ 10% of the glyph in the middle band trigger a hard skip (avoids over-compressing 三 / 王 / 重 style stacked-three layouts). |
| LUO_FRAME_INNER_OUTER_W / OUTER_H | **0.55 / 0.55** (new in v0.4.7) | n/a | v0.4.7 abstraction: glyphs whose largest outer contour spans at least 55% of glyph width AND 55% of glyph height qualify as a frame-with-content topology (自/曲/田/角/由/见 / 取 / etc.). The 0.55/0.55 floor catches the broad-hull cases without false-firing on chars with a tall single stem and one tiny side outer. |
| LUO_FRAME_INNER_X / Y | **1.014 / 1.008** (new in v0.4.7) | n/a | Counter expansion magnitude for the frame-inner pass, kept smaller than `LUO_INNER_COUNTER_X/Y = 1.040 / 1.020` because the trigger is broader (any glyph with a frame hull, not just dense glyphs with a middle counter). The smaller magnitude keeps frame-with-content glyphs from over-stretching their inner kai grid. Skips the middle-band counters that `luo_inner_counter_open` already handles, plus `IDENTITY_FRAME_CHARS` and `IDENTITY_CORE_V2_CHARS` which already restructure their own counters. |
| LUO_FRAME_INNER_MIN_AREA / MAX_AREA | **0.008 / 0.20** (new in v0.4.7) | n/a | Per-counter area gate (fraction of glyph bbox area). Min 0.8% rejects pinhole counters that would not visibly benefit; max 20% rejects whole-glyph counters that would over-stretch the outer hull. |

NEW v0.4 parameters (no v0.3 baseline):

| Parameter | v0.4 | Purpose |
|-----------|------|---------|
| STRAIGHTEN_H_BLEND | 0.65 | Horizontal-band span flattening intensity |
| STRAIGHTEN_V_BLEND | 0.60 | Vertical-band span flattening intensity |
| STRAIGHTEN_DIAG_BLEND | 0.30 | Diagonal-band span flattening intensity (lower so 撇/捺 keep speed) |
| STRAIGHTEN_H_BAND | 30.0 | Degrees off horizontal still counted as "near-axial" |
| STRAIGHTEN_V_BAND | 30.0 | Degrees off vertical still counted as "near-axial" |
| STRAIGHTEN_MIN_LEN_RATIO | 0.04 | Skip spans shorter than this fraction of glyph max(w,h) |
| STRAIGHTEN_MIN_LEN_ABS | 30.0 | Absolute floor in font units |
| STRAIGHTEN_MAX_PERP_RATIO | **0.20** (v0.4.3: was 0.18; new in v0.4.2) | Per-off-curve corner protection: skip pulling controls whose perpendicular distance from the chord exceeds 20% of chord length. v0.4.3 widens the protection band (was 0.18) because audit found residual triangular spikes at the right end of long horizontals where corner controls sat just below the previous threshold. Bow controls still sit at <5% and bao-gai/横折钩 corner controls at 15-30%, so the threshold continues to cleanly separate the two. |
| HOOK_TAIL_CAP_TOLERANCE | **0.05** (new in v0.4.2) | Geometric hook-tail cap tolerance: tail outline width may exceed the stem width at the hook root by this fraction before being pushed inward. |
| HOOK_TAIL_CAP_MAX_PUSH | **16.0** (new in v0.4.2) | Maximum half-excess push (in font units) per side per sample. Caps the geometric inward correction so weird outlines can't be folded onto themselves. |
| HOOK_TAIL_CAP_SAMPLES | **4** (new in v0.4.2) | Number of contour points walked forward from each hook knee when searching for tail outline-width violations. |
| KAI_BALANCE_WATER_X/Y_SCALE | 0.915 / 0.910 | Lower ink in 氵旁 for 清/源/落-style glyphs without starving dots |
| KAI_BALANCE_COUNTER_EXPAND_X/Y | 1.125 / 1.095 | Open positive inner counters in dense glyphs such as 魔/皆/熹 |
| KAI_BALANCE_DENSE_LAYER_X/Y/GAP | 0.970 / 0.965 / 0.004em | Add hierarchy and breathing room to dense horizontal layers without global weight cuts |
| KAI_BALANCE_DENSE_UPPER_X/Y | 0.985 / 0.970 | Lightly relieve upper dense components in 皆-style glyphs without changing whole-glyph width |
| KAI_BALANCE_BOOK_DOT_X/Y_SCALE | 0.940 / 0.880 | Shorten `书` right dot without making it disappear in body text |
| KAI_BALANCE_SPEECH_SECONDARY_X/Y | 0.945 / 0.960 | Reduce secondary horizontal weight in 言/讠 glyphs without collapsing width |
| KAI_BALANCE_SPEECH_DOT_X/Y | **0.880 / 0.860** (v0.4.3: was 0.860 / 0.840) | Keep speech dots short and decisive after soft dot normalization. v0.4.3 audit raised both axes one notch because 言/讠 dots still read too small at body sizes; combined with `WEB_PRESENCE_DOT_MIN_EM=0.160`. |
| KAI_BALANCE_SPEECH_UPPER_X/Y | 0.975 / 0.900 | Contain standalone `言` upper horizontals so the stack separates from source posture |
| KAI_BALANCE_SIDE_LEFT_X/Y | **0.970 / 0.980** (v0.4.3: was 0.960 / 0.972; v0.4.1: was 0.945 / 0.960) | v0.4.3 audit-driven relax; 0.960 / 0.972 still left 欢/剑/给/怡-style left components a touch underweight at body sizes. The split-chars list stays scoped to glyphs that genuinely need extra subordination beyond `wide_split`. |
| KAI_BALANCE_WATER_X/Y_SCALE | **0.950 / 0.945** (v0.4.3: was 0.940 / 0.935; v0.4.1: was 0.915 / 0.910) | v0.4.3 audit-driven relax; the v0.4.1 numbers still occasionally let the 氵 third dot drop in 源/清/落 at very small body sizes once the bottom-dot extra cap was removed. The position-driven `shift_y` for top/bottom dots is preserved. |
| WEB_PRESENCE_DOT/H_MIN_EM | **0.160 / 0.080** (v0.4.3: was 0.150 / 0.075; v0.4.1: was 0.125 / 0.066) | Minimum visible extent guard for compressed dots and short horizontals. v0.4.3 audit raises both floors one notch so 地/发/亦/源 dot mass and 荒/无/东 secondary 横画 stay readable even when downstream component-balance passes get raised. |
| SITE_BODY_READABILITY chars | dynamic union (v0.4.1) | — | Replaced the v0.4 fixed list with an on-disk scan of `index.html`, `README.md`, `proof/a4.html`, `assets/styles/*.css`, plus the visible-defect anchor set. Stats line: `[luo] body readability guard: N glyphs`. |
| KAI_BALANCE_ROOF_BOTTOM_X/Y | **0.945 / 0.945** (v0.4.3: was 0.925 / 0.925) | Contain heavy lower layers in roof/top-bottom glyphs (字/宇/宙/家/序). v0.4.3 audit relaxed both axes because 0.925 / 0.925 was making body sizes 顶轻底碎; raising one notch keeps the contain direction without crushing the lower layer. |
| KAI_BALANCE_STACK_BOTTOM_X/Y | **0.930 / 0.910** (v0.4.3: was 0.910 / 0.885) | Stronger bottom containment for 实/寒/库/头-style stack glyphs. v0.4.3 audit relaxed both axes because the v0.4.1 values broke the lower stack into chips at small body sizes; the new values still keep clear hierarchy. |
| KAI_BALANCE_WIDE_EDGE/BOTTOM_CONTAIN | 0.030 / 0.045 | Contain lower tails and wide edges for current wide_simple/diag anchors |
| WALK_FINAL_X_CONTAIN / RAISE / TAIL | 0.910 / 0.050em / 0.125 | Stronger final containment for site-visible walk-radical glyphs |
| LUO_HORIZ_END_EMPHASIS_PUSH_EM | **0.005** (new in v0.4.4) | Maximum downward push (in em) at the right end of long horizontal strokes, decaying away from the cap. Geometric, no whitelist. The Luo "stop" is intentionally subtle; if heading sizes ever read as a heavy tail or fishhook, drop toward 0.003 first, do not raise. |
| LUO_HORIZ_END_EMPHASIS_LEN_RATIO | **0.06** (new in v0.4.4) | Tail length (fraction of chord length) over which the downward push tapers; covers the last ~5-7% of the cap region. |
| LUO_HORIZ_END_EMPHASIS_MIN_RATIO | **0.25** (new in v0.4.4) | Minimum chord length (fraction of glyph max(w,h)) for a chord to qualify. Plan called for 0.40, but LXGW outlines subdivide long edges with multiple on-curve points, so 0.25 is the lowest gate that catches per-chord segments of typical multi-horizontal stacks (王/主/章/兰/集/印) without firing on short joinery. |
| LUO_HORIZ_END_EMPHASIS_ANGLE_DEG | **10.0** (new in v0.4.4) | Maximum chord deviation from horizontal (degrees). |
| LUO_HORIZ_END_EMPHASIS_SAMPLES | **4** (new in v0.4.4) | Number of outline points pushed down past the cap top (decay 4/5, 3/5, 2/5, 1/5). |
| LUO_HOOK_ROOT_HANDLE_PUSH_EM | **0.003** (new in v0.4.4) | Inward push (toward glyph centroid) on the off-curve handle just before each detected hook root. Adds a small inward-curving "knuckle" gesture LXGW does not have. Subtle by design. |

## Frozen Parameters (unchanged from v0.3)

Do NOT change these without explicit approval. Reflects actual `scripts/build.py` defaults.

| Parameter | Value | Purpose |
|-----------|-------|---------|
| DOT_BOLDEN_X_CAP_FACTOR | 1.15 | Dot contour x-only expansion cap inside bolden |
| BOLDEN_GRAD_STEP | 0.06 | Weight reduction per contour above onset |
| BOLDEN_GRAD_FLOOR | 0.85 | Minimum weight scale for complex chars |
| BOLDEN_GRAD_ONSET | 3 | Contour count where graduation starts |
| NARROW_SIMPLE | 1.000 | Simple char horizontal scale |
| NARROW_REGULAR | 0.975 | Regular char horizontal scale |
| NARROW_COMPLEX | 0.950 | Complex char horizontal scale |
| SCALE_Y | 1.00 | Vertical face ratio |
| SOFTEN_BLEND | 0.05 | Endpoint softening fallback intensity |
| ENDPOINT_V_BOTTOM_BLEND | 0.045 | Vertical bottom terminal soft-cut intensity |
| DOT_LONG_AXIS | 0.92 | Dot long-axis scale |
| DOT_LONG_AXIS_SOFT | 1.00 | Soft channel long-axis identity |
| DOT_SHORT_AXIS_SOFT | 0.95 | Soft channel for 氵/讠 |
| DOT_ROTATE_DEG | 14.0 | Dot rotation angle |
| HOOK_FINAL_TAIL_CONTAIN | 0.06 | Final hook tail axial containment |
| TURN_FINAL_FRAME_DISPLACE | 1.6 | Frame-only turn apex displacement |
| TURN_FINAL_FRAME_INNER | 0.955 | Frame-only inner-side tightening |
| TURN_FINAL_FRAME_SEG_MAX | 140 | Frame-only turn segment ceiling |
| TURN_FINAL_FRAME_DISPLACE | 1.6 | Frame-only turn apex displacement |
| TURN_FINAL_FRAME_INNER | 0.955 | Frame-only inner-side tightening |
| TURN_FINAL_FRAME_SEG_MAX | 140 | Frame-only turn segment ceiling |
| DENSE_COMPLEX_INNER | 0.970 | Dense character inner white opening |
| DENSE_COMPLEX_INNER_EXTRA | 0.945 | Extra dense glyph internal white opening |
| DENSE_TOP_REDUCE_EXTRA | 0.955 | Extra dense rain/cao top contraction |
| MULTI_HORIZ_SECONDARY | 0.965 | Secondary horizontal layer lightening |
| IDENTITY_POSTURE_TOP_RAISE_EM | 0.026 | Site-priority top posture lift |
| IDENTITY_POSTURE_BOTTOM_SETTLE_EM | 0.010 | Site-priority bottom settling |
| IDENTITY_FRAME_COUNTER_EXPAND_X | 1.050 | Frame counter horizontal opening |
| IDENTITY_FRAME_COUNTER_EXPAND_Y | 1.025 | Frame counter vertical opening |
| IDENTITY_MULTI_MID_CONTAIN | 0.935 | Multi-horizontal middle hierarchy |
| IDENTITY_RISK_FRAME_COUNTER_EXPAND_X | 1.065 | Whitelist frame-risk counter x opening |
| IDENTITY_RISK_FRAME_COUNTER_EXPAND_Y | 1.040 | Whitelist frame-risk counter y opening |
| IDENTITY_LAYER_COUNTER_EXPAND_X | 1.040 | Whitelist layered-glyph counter x opening |
| IDENTITY_LAYER_COUNTER_EXPAND_Y | 1.022 | Whitelist layered-glyph counter y opening |
| IDENTITY_LAYER_SECONDARY_SCALE | 0.986 | Whitelist layered-glyph secondary stroke lightening |
| IDENTITY_LAYER_TOP_RAISE_EM | 0.006 | Whitelist layered-glyph top separation |
| IDENTITY_LAYER_BOTTOM_SETTLE_EM | 0.004 | Whitelist layered-glyph bottom settling |
| IDENTITY_LAYER_TOP_CONTAIN | 0.992 | Whitelist layered-glyph top containment |
| IDENTITY_ALL_TOP_RAISE_EM | 0.010 | Guardrail-only all-covered top rhythm lift |
| IDENTITY_ALL_BOTTOM_SETTLE_EM | 0.003 | Guardrail-only all-covered bottom settling |
| IDENTITY_ALL_TOP_CONTAIN | 0.992 | Guardrail-only upper stroke containment |
| IDENTITY_ALL_BOTTOM_EXPAND | 1.004 | Guardrail-only lower stroke support |
| IDENTITY_ALL_WAIST_CONTAIN | 0.994 | Guardrail-only middle-layer containment |
| IDENTITY_ALL_COUNTER_EXPAND_X | 1.012 | Guardrail-only counter horizontal opening |
| IDENTITY_ALL_COUNTER_EXPAND_Y | 1.008 | Guardrail-only counter vertical opening |
| IDENTITY_ALL_COMPONENT_SHIFT_EM | 0.002 | Guardrail-only small component separation |
| IDENTITY_ALL_COMPONENT_Y_EM | 0.001 | Guardrail-only small component vertical separation |
| IDENTITY_ALL_EDGE_TENSION_EM | 0.001 | Tiny symmetric edge tension, no whole-glyph shift |
| IDENTITY_SIMPLE_FACE_X | 1.008 | Guardrail-only simple glyph face expansion |
| IDENTITY_SIMPLE_FACE_Y | 1.006 | Guardrail-only simple glyph vertical face expansion |
| IDENTITY_REGULAR_FACE_X | 1.004 | Guardrail-only regular glyph face expansion |
| IDENTITY_REGULAR_FACE_Y | 1.004 | Guardrail-only regular glyph vertical face expansion |
| IDENTITY_COMPLEX_FACE_X | 1.002 | Guardrail-only complex glyph light face expansion |
| IDENTITY_COMPLEX_FACE_Y | 1.002 | Guardrail-only complex glyph light vertical face expansion |
| IDENTITY_SIMPLE_H_LAYER_X | 0.990 | Guardrail-only simple horizontal layer containment |
| IDENTITY_ALL_H_LAYER_X | 0.994 | Guardrail-only horizontal layer containment |
| IDENTITY_ALL_H_LAYER_ROTATE_DEG | 0.25 | Guardrail-only horizontal layer direction |
| IDENTITY_ALL_V_STEM_X | 0.994 | Guardrail-only vertical stem containment |
| IDENTITY_ALL_V_STEM_Y | 1.004 | Guardrail-only vertical stem extension |
| IDENTITY_ALL_DIAG_EXPAND | 1.004 | Guardrail-only diagonal stroke tension |
| IDENTITY_ALL_SECONDARY_SCALE | 0.994 | Guardrail-only secondary stroke lightening |
| IDENTITY_ALL_SIDE_COMPONENT_X_EM | 0.001 | Guardrail-only side component separation |
| IDENTITY_ALL_SIDE_COMPONENT_Y_EM | 0.000 | Guardrail-only side component vertical rhythm |
| IDENTITY_SOURCE_SHIFT_X_EM | 0.000 | Local experiment only; keep off by default |
| IDENTITY_SOURCE_SHIFT_Y_EM | 0.000 | Local experiment only; keep off by default |
| IDENTITY_CORE_COUNTER_EXPAND_X | 1.055 | Core whitelist counter horizontal opening |
| IDENTITY_CORE_COUNTER_EXPAND_Y | 1.035 | Core whitelist counter vertical opening |
| IDENTITY_CORE_SECONDARY_SCALE | 0.960 | Core whitelist secondary stroke lightening |
| IDENTITY_CORE_HORIZ_Y_SCALE | 0.925 | Core whitelist horizontal layer thinning |
| IDENTITY_CORE_LAYER_GAP_EM | 0.010 | Core whitelist layered-glyph separation |
| IDENTITY_CORE_FRAME_STEM_X | 0.988 | Core whitelist frame/stem containment |
| IDENTITY_CORE_DIAG_EDGE_EM | 0.020 | Core whitelist diagonal tension |
| IDENTITY_CORE_DIAG_TOP_CONTAIN | 0.990 | Core whitelist top containment for diagonal chars |
| IDENTITY_CORE_DIAG_TAIL_CONTAIN | 0.012 | Core whitelist tail containment for diagonal chars |
| SPACING_BASE | 1.00 | Keep CJK advances on 1em rhythm |
| SPACING_STEP | 0.000 | No complexity-based advance widening |

## Do NOT

- Make the font rounder, softer, or more handwritten.
- Increase overall weight or `BOLDEN_V` past the v0.4.2 values (6/14); dense characters will blur. The v0.4.2 restore is calibrated against the corner-protected straighten pass, so going higher would re-introduce ink crowding now that bow stems no longer carry geometric loss.
- Make hooks longer; strength comes from direction and containment, not length.
- Push `HOOK_FINAL_TIP_SHARPEN` back above 0.20 globally — the v0.4 launch value (0.24) plus `TURN_FINAL_DISPLACE=2.5` was the v0.4.1 root cause for 笔/书/览/无 reading as two segments. Use `HOOK_FINAL_TIP_SHARPEN_CURVED` and the priority displace lists if you need explicit骨节 on display chars.
- Re-stack `MULTI_HORIZ_SECONDARY` and `IDENTITY_ALL_H_LAYER_X` aggressively on the same glyphs; the v0.4 stack (0.965 × 0.994 ≈ 0.96) erased secondary 横画 on body text. Both knobs were rolled back together for a reason.
- Lower `DOT_SHORT_AXIS_SOFT`; SOFT is angle normalization, not another carve pass.
- Raise `DOT_SHORT_AXIS` past 0.55 toward round dots; default dots must stay wedge-like.
- Increase `BOLDEN_DIAG_BONUS` past 7.0; 撇捺 will overpower the H/V ratio.
- Push `STRAIGHTEN_DIAG_BLEND` above 0.40; 撇捺 will read as geometric Hei instead of kai.
- Drop `STRAIGHTEN_*` to v0.3-style weak values without reverting the BOLDEN drop; the result is light AND curvy, the worst of both.
- Lower `STRAIGHTEN_MAX_PERP_RATIO` below 0.10 — the corner protection will fire on real bow controls and the v0.4 print-kai gesture will weaken. Above ~0.30 it stops protecting corners, and 字's bao-gai / 无's 竖弯钩 spike returns.
- Turn endpoint subtype softening into another global taper; it exists only to avoid template-like identical terminals.
- Disable frame-specific turn rollback last; if frames are hurt, first set frame turn params back to the base turn values.
- Change `SPACING_STEP`; 1em CJK rhythm is a core reading feature.
- Return to LXGW WenKai's loose casual feel.
- Treat an IoU pass caused only by whole-glyph translation as sufficient identity work.
- Treat raster IoU as a hard gate for v0.4 weight changes; it goes UP when strokes get lighter (paradox). Use bow distance + visual review. v0.4.4 confirmed this: three new Luo-only signature passes that visibly diverge from LXGW barely move 384px raster IoU because the per-feature shifts (5-6 units / ~1 px) are sub-pixel.
- Push `LUO_HORIZ_END_EMPHASIS_PUSH_EM` above 0.008 to chase IoU; the result is a heavy tail / fishhook at heading sizes and 顿 that stops looking like a quiet 印楷 stop. If a follow-up wants more structural distance, prefer extending whitelists (frame, layer, diag) before raising signature pushes.
- Push `LUO_HOOK_ROOT_HANDLE_PUSH_EM` above 0.005; the inward "knuckle" turns into a visible kink on every hook root, which would re-introduce v0.4-style 折点 noise that v0.4.1/v0.4.3 spent two iterations cleaning up.
- Raise `DOT_ROTATE_DEG` past ~20°; xiaokai-feel dots tip into slash territory, especially on 氵 secondary dots.
- Lower `LUO_BOTTOM_ANCHOR_SCALE_Y` below 0.93. The foot layer visibly loses height and the glyph reads "shrunk", not "settled"; v0.4.5 verified that 0.945 is the floor before homepage anchors take noticeable hits.
- Drop `LUO_LEFT_RADICAL_X` below 0.92. The left radical detaches into something narrower than its right counterpart and the glyph reads as two unrelated parts; the 0.94 value was tuned to match the print-kai layout where 彳/纟/木 sit *inside* the left zone, not crushed against the left bearing.
- Push `LUO_INNER_COUNTER_X` above 1.05. Counters in already-tight glyphs (皆 / 熹 / 籍) burst open and the glyph loses its dense-component identity. v0.4.5 verified that 1.040 is right around the regression knee for 皆.
- Remove the skip lists in the v0.4.5 abstractions (frame / KAI_BALANCE_ROOF / STACK / SIDE_SPLIT / SPEECH / WATER / STRAIGHTEN_SKIP). Those categories already have tuned per-character geometry, and double-stacking the generic abstractions on top has been observed to break 实/气/兴/哉.
- Remove the skip lists in the v0.4.7 abstractions (`luo_top_bottom_separate` skips frame / roof / stack / heart / walk / straighten-skip; `luo_frame_inner_open` skips frame / core_v2 / straighten-skip and the middle-band counters already handled by `luo_inner_counter_open`). Verified by the site-wide grouped IoU report: every skip-listed bucket showed exact zero delta from baseline. Removing those skips would double-stack on glyphs that already have specialised geometry and break the per-bucket layering work.
- Push `LUO_TOP_BOTTOM_LIFT_EM` / `SETTLE_EM` past 0.008. The current 0.005 / 0.004 produce a visible-but-quiet 上下层断隔 at heading sizes; 0.008+ starts reading as "the top half is floating off" especially on glyphs with light upper components like 答 / 案. If a follow-up wants more 断隔, prefer narrowing the qualifying bands (`TOP_BAND` / `BOT_BAND`) so more glyphs match, not increasing the per-glyph push.
- Push `LUO_FRAME_INNER_X` past 1.025. The 1.014 / 1.008 magnitudes are deliberately smaller than `LUO_INNER_COUNTER_X/Y` because the trigger is broader. Going higher would over-stretch the inner kai grid on high-density frame glyphs (角 / 田 type), which already read as compact-by-design.
- Re-bucket glyphs that landed in the existing pass-specific whitelists (frame / walk / heart / stack / roof / etc.) into the generic v0.4.7 passes "to give them a second pass". The whole reason those buckets stayed at exact zero delta is the skip list; the dedicated geometry was tuned independently and should not be over-stacked.
- Stack new "短/利/清/收" passes on glyphs that already have 3+ shaping passes; the v0.4 → v0.4.1 lesson is that each well-meant pass independently looks fine but the stack collapses body-text legibility. Verify in `local/ref/renders/web_glyph_regression_after.png` style side-by-sides before re-stacking.
- Hard-code site-readability char lists; `_collect_site_body_readability_chars()` rescans `index.html` / `README.md` / `proof/a4.html` / `assets/styles/*.css` plus the defect-anchor set so the guard tracks site copy automatically.
- Copy any existing commercial font outlines, including private references.
- Add stone texture, breakage, ink effects, flying white, or brush simulation.

## Verification

- Font pipeline changes: run `python scripts/build.py` and inspect generated files under `dist/` and `proof/`.
- Source-similarity changes: use a local ignored comparison script only when available. It should compare Luo against the source font with both raster IoU and bbox-centered IoU; high centered overlap still needs real structure work, not whole-glyph translation.
- Site-wide grouped audit: `.venv/bin/python scripts/measure_groups.py` runs the IoU report across the full homepage glyph set bucketed by which pass-specific whitelist (frame / walk / heart / stack / roof / water / speech / side / core_v2 / hook / turn / generic) each glyph lives in. Pass `--baseline /path/to/old.ttf` for a before/after diff that exposes whether new passes touched the buckets they were supposed to (and whether they stayed off the buckets they were supposed to skip). Output goes to `local/ref/metrics/site_grouped_iou.json`, never the public `proof/`.
- Parameter changes: compare representative dense, simple, dot-heavy, hook-heavy, and punctuation glyphs before handoff.
- Screenshot-reported glyph defects: treat the screenshot as the oracle. First isolate the exact glyphs and defect class (hook kink, missing dot, weak secondary horizontal, left/right gray imbalance, endpoint spike, dense top/bottom imbalance), then generate a local diagnostic sheet with the reported glyphs at body and display sizes under `local/ref/renders/`. Only after the visual defect is classified should you map it back to a specific build pass/parameter and change the smallest responsible dial. Do not chase private/source IoU or stack new passes before this diagnosis.
- Style guide changes: keep `STYLE.md` aligned with the design direction in this file.
- Documentation-only changes: check command and path accuracy.
