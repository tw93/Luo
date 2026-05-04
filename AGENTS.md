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

Output: `dist/Luo-Regular.{otf,ttf,woff2}`

Source font: `source/LXGWWenKaiScreen-Regular.ttf`

## Pipeline (order matters)

1. Subset to starter/site/seed characters, or explicit GB2312 expansion mode
2. Graduated stroke thickening (BOLDEN_H=6, BOLDEN_V=14, contour-scaled, dot-aware cap)
3. Endpoint softening (sharp corners to subtype soft-cuts)
4. Complexity-aware horizontal narrowing + vertical face-ratio scaling (SCALE_Y=1.00)
5. Component-aware refinement (7 categories: enclosed, dense_top, wide_split, walk_enclosed, dense_complex, multi_horiz, top_bottom)
6. Heart-character reshape (special case: 心字底/旁)
7. Dot contour direction (xiaokai dot rotation + adaptive compression)
8. Targeted turn refinement (priority endpoints / frames / multi-horiz only)
9. Hook refinement on whitelist only (refine_hooks_final)
10. CJK punctuation proportional width (0.75em)
11. Space half-width (50%)
12. CJK spacing stays 1em by default for reading rhythm
13. Name table rewrite, output

## Design Direction (v0.3 final)

Target: modern print-ready title font with Wei Furen bone structure.

- Wei-Jin xiaokai-style clear bone 50%, open skeleton from contemporary expanded kaishu-inspired print type 40%, modern font engineering stability 10%
- More bone than the source font, more restrained than copying any existing font outlines
- Clean, upright, print-friendly, not calligraphic or handwritten
- Hooks: short, precise, directional, contained, no dragging
- Dots: short, directional xiaokai dots, not round, not slash-like
- Endpoints: soft-cut with slight dry restraint, not round-cute, not spike-sharp
- Strokes: horizontal slightly thinner than vertical (H/V ratio ~0.40)

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

## Frozen Parameters

Do NOT change these without explicit approval. Reflects actual `scripts/build.py` defaults.

| Parameter | Value | Purpose |
|-----------|-------|---------|
| BOLDEN_H | 6 | Horizontal stroke weight |
| BOLDEN_V | 14 | Vertical stroke weight ceiling for print density |
| BOLDEN_DIAG_BONUS | 9.0 | 撇/捺 visual lift without changing pure h/v |
| DOT_BOLDEN_X_CAP_FACTOR | 1.15 | Dot contour x-only expansion cap inside bolden |
| BOLDEN_GRAD_STEP | 0.06 | Weight reduction per contour above onset |
| BOLDEN_GRAD_FLOOR | 0.85 | Minimum weight scale for complex chars |
| BOLDEN_GRAD_ONSET | 3 | Contour count where graduation starts |
| NARROW_SIMPLE | 1.000 | Simple char horizontal scale |
| NARROW_REGULAR | 0.975 | Regular char horizontal scale |
| NARROW_COMPLEX | 0.950 | Complex char horizontal scale |
| SCALE_Y | 1.00 | Vertical face ratio |
| SOFTEN_BLEND | 0.05 | Endpoint softening fallback intensity |
| ENDPOINT_H_BLEND | 0.040 | Horizontal terminal soft-cut intensity |
| ENDPOINT_V_BOTTOM_BLEND | 0.045 | Vertical bottom terminal soft-cut intensity |
| ENDPOINT_DIAG_BLEND | 0.030 | 撇/捺 diagonal terminal soft-cut intensity |
| DOT_LONG_AXIS | 0.92 | Dot long-axis scale |
| DOT_LONG_AXIS_SOFT | 1.00 | Soft channel long-axis identity |
| DOT_SHORT_AXIS | 0.55 | Dot short-axis carve |
| DOT_SHORT_AXIS_SOFT | 0.95 | Soft channel for 氵/讠 |
| DOT_ROTATE_DEG | 14.0 | Dot rotation angle |
| HOOK_FINAL_SHORTEN | 0.14 | Final hook endpoint pull |
| HOOK_FINAL_TIP_SHARPEN | 0.18 | Final hook tip perpendicular containment |
| HOOK_FINAL_TAIL_CONTAIN | 0.06 | Final hook tail axial containment |
| TURN_FINAL_DISPLACE | 1.2 | Targeted turn apex displacement |
| TURN_FINAL_INNER | 0.96 | Targeted turn inner-side light tightening |
| TURN_FINAL_FRAME_DISPLACE | 1.6 | Frame-only turn apex displacement |
| TURN_FINAL_FRAME_INNER | 0.955 | Frame-only inner-side tightening |
| TURN_FINAL_FRAME_SEG_MAX | 140 | Frame-only turn segment ceiling |
| DENSE_COMPLEX_INNER | 0.970 | Dense character inner white opening |
| DENSE_COMPLEX_INNER_EXTRA | 0.945 | Extra dense glyph internal white opening |
| DENSE_TOP_REDUCE_EXTRA | 0.955 | Extra dense rain/cao top contraction |
| MULTI_HORIZ_SECONDARY | 0.965 | Secondary horizontal layer lightening |
| SPACING_BASE | 1.00 | Keep CJK advances on 1em rhythm |
| SPACING_STEP | 0.000 | No complexity-based advance widening |

## Do NOT

- Make the font rounder, softer, or more handwritten.
- Increase overall weight or `BOLDEN_V`; dense characters will blur.
- Make hooks longer; strength comes from direction and containment, not length.
- Lower `DOT_SHORT_AXIS_SOFT`; SOFT is angle normalization, not another carve pass.
- Raise `DOT_SHORT_AXIS` toward round dots; default dots must stay wedge-like.
- Increase `BOLDEN_DIAG_BONUS`; 撇捺 will overpower the H/V ratio.
- Turn endpoint subtype softening into another global taper; it exists only to avoid template-like identical terminals.
- Disable frame-specific turn rollback last; if frames are hurt, first set frame turn params back to the base turn values.
- Change `SPACING_STEP`; 1em CJK rhythm is a core reading feature.
- Return to LXGW WenKai's loose casual feel.
- Copy any existing commercial font outlines.
- Add stone texture, breakage, ink effects, flying white, or brush simulation.

## Verification

- Font pipeline changes: run `python scripts/build.py` and inspect generated files under `dist/` and `proof/`.
- Parameter changes: compare representative dense, simple, dot-heavy, hook-heavy, and punctuation glyphs before handoff.
- Style guide changes: keep `STYLE.md` aligned with the design direction in this file.
- Documentation-only changes: check command and path accuracy.
