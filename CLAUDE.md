# Luo 落文

Luo (落文) is a CJK reading/display typeface inspired by Wei Furen's bone-method calligraphy. SIL OFL 1.1.

## Build

```bash
pip install -r requirements.txt
python scripts/build.py          # starter mode: site + print + README + common chars
LUO_BUILD_CHARS=seed python scripts/build.py   # seed mode: diagnostic chars only
```

Output: `dist/Luo-Regular.{otf,ttf,woff2}`

Source font: `source/LXGWWenKaiScreen-Regular.ttf`

## Pipeline (order matters)

1. Subset to starter/site/seed characters
2. Graduated stroke thickening (BOLDEN_H=6, BOLDEN_V=15, contour-scaled)
3. Endpoint softening (sharp corners to soft-cut)
4. Hook refinement (root thin, body shorten, tip direction)
5. Complexity-aware horizontal narrowing
6. Vertical face-ratio scaling (SCALE_Y=1.05)
7. Component-aware refinement (7 categories: enclosed, dense_top, wide_split, walk_enclosed, dense_complex, multi_horiz, top_bottom)
8. CJK punctuation proportional width (0.75em)
9. Space half-width (50%)
10. CJK spacing stays 1em by default for reading rhythm
11. Name table rewrite, output

## Design Direction (frozen v0.3)

Target: modern print-ready title font with Wei Furen bone structure.

- Wei Furen bone-method 60%, TsangerJinKai comfort 30%, modern typographic stability 10%
- More bone than the source font, more restrained than TsangerJinKai02
- Clean, upright, print-friendly, not calligraphic or handwritten
- Hooks: short, precise, directional, no dragging
- Dots: short, directional xiaokai dots, not round, not hard blocks
- Endpoints: soft-cut, not round-cute, not spike-sharp
- Strokes: horizontal slightly thinner than vertical (H/V ratio ~0.40)

## Frozen Parameters

Do NOT change these without explicit approval:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| BOLDEN_H | 6 | Horizontal stroke weight |
| BOLDEN_V | 15 | Vertical stroke weight |
| BOLDEN_GRAD_STEP | 0.06 | Weight reduction per contour above onset |
| BOLDEN_GRAD_FLOOR | 0.85 | Minimum weight scale for complex chars |
| BOLDEN_GRAD_ONSET | 3 | Contour count where graduation starts |
| NARROW_SIMPLE | 0.995 | Simple char horizontal scale |
| NARROW_REGULAR | 0.965 | Regular char horizontal scale |
| NARROW_COMPLEX | 0.935 | Complex char horizontal scale |
| SCALE_Y | 1.05 | Vertical face ratio |
| SOFTEN_BLEND | 0.08 | Endpoint softening intensity |
| HOOK_ROOT_THIN | 0.09 | Hook root thinning |
| HOOK_SHORTEN | 0.14 | Hook body compression |
| HOOK_TIP_TAPER | -0.02 | Hook tip direction (negative = extend) |
| SPACING_BASE | 1.00 | Keep CJK advances on 1em rhythm |
| SPACING_STEP | 0.000 | No complexity-based advance widening by default |

## Do NOT

- Make the font rounder, softer, or more handwritten
- Increase overall weight (already calibrated)
- Make hooks longer
- Return to the source font's loose casual feel
- Copy TsangerJinKai02's specific outlines
- Add calligraphic flourishes, ink effects, or brush textures
