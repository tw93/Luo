"""Check glyphs that are intentionally frozen to historical outlines.

The current v0.4.8 exception is 月: visual review showed that partial v0.4
adjustments mixed badly with the older sweep/hook rhythm, so the final pass
point-locks it to Luo v0.3. This script guards that invariant.

Run:
    python3 scripts/check_frozen_glyphs.py
"""

from __future__ import annotations

import argparse
import io
import subprocess
from pathlib import Path

from fontTools.ttLib import TTFont


ROOT = Path(__file__).resolve().parent.parent
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

    failed: list[str] = []
    for char in args.chars:
        if _glyph_shape(current, char) != _glyph_shape(baseline, char):
            failed.append(char)

    if failed:
        raise SystemExit(f"[frozen] mismatch: {''.join(failed)}")
    print(f"[frozen] ok: {args.chars}")


if __name__ == "__main__":
    main()
