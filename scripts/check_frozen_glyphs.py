"""Check glyphs that are intentionally frozen to historical outlines.

The current v0.4.8 exception is 月: visual review showed that partial v0.4
adjustments mixed badly with the older sweep/hook rhythm, so the final pass
point-locks it to Luo v0.3. This script guards that invariant.

v0.4.12: the global `luo_posture_contain` pass applies one uniform affine
y' = pivot + s * (y - pivot) to every CJK glyph as the last outline pass.
Exempting 月 would leave it sitting ~0.02em lower than every neighbouring
glyph, which is visible in running text. The frozen invariant is therefore
"affine-equivalent to the v0.3 outline under the posture transform"; the
transform parameters are imported from build.py so the two can never drift
apart silently. With the posture pass disabled (scale >= 1) the check
degrades to the original exact point-lock.

Run:
    python3 scripts/check_frozen_glyphs.py
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

from fontTools.ttLib import TTFont


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402  -- posture transform constants live in the pipeline

CURRENT_LUO = ROOT / "dist" / "Luo-Regular.ttf"
BASELINE_FONT = ROOT / "local" / "ref" / "baselines" / "Luo-v0.3.0-final.ttf"
BASELINE_SPEC = "v0.3.0-final:dist/Luo-Regular.ttf"
FROZEN_CHARS = "月"


def _load_font(path: Path, fallback_git_spec: str | None = None) -> TTFont:
    if path.exists():
        return TTFont(str(path))
    if fallback_git_spec is None:
        raise FileNotFoundError(path)
    data = subprocess.check_output(["git", "show", fallback_git_spec], cwd=ROOT)
    return TTFont(io.BytesIO(data))


def _glyph_shape(font: TTFont, char: str) -> tuple[list[int], list[tuple[int, int]]]:
    cmap = font.getBestCmap() or {}
    gname = cmap.get(ord(char))
    if not gname:
        raise KeyError(f"{char} missing from cmap")
    glyph = font["glyf"][gname]
    return list(glyph.endPtsOfContours), [tuple(pt) for pt in glyph.coordinates]


def _posture_transform(
    shape: tuple[list[int], list[tuple[int, int]]], upm: int
) -> tuple[list[int], list[tuple[int, int]]]:
    """Replay build.py's luo_posture_contain affine on a baseline outline."""
    if build.LUO_POSTURE_SCALE_Y >= 1.0:
        return shape
    pivot = build.LUO_POSTURE_PIVOT_EM * upm
    s = build.LUO_POSTURE_SCALE_Y
    ends, coords = shape
    return ends, [(x, int(round(pivot + s * (y - pivot)))) for x, y in coords]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--current", type=Path, default=CURRENT_LUO)
    parser.add_argument("--baseline", type=Path, default=BASELINE_FONT)
    parser.add_argument("--chars", default=FROZEN_CHARS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    current = _load_font(args.current)
    baseline = _load_font(args.baseline, BASELINE_SPEC)
    upm = current["head"].unitsPerEm

    failed: list[str] = []
    for char in args.chars:
        expected = _posture_transform(_glyph_shape(baseline, char), upm)
        if _glyph_shape(current, char) != expected:
            failed.append(char)

    if failed:
        raise SystemExit(f"[frozen] mismatch: {''.join(failed)}")
    mode = (
        "affine-equivalent" if build.LUO_POSTURE_SCALE_Y < 1.0 else "point-locked"
    )
    print(f"[frozen] ok ({mode}): {args.chars}")


if __name__ == "__main__":
    main()
