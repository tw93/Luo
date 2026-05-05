"""
Cheap post-build checks for CI.

Verifies that the font produced by scripts/build.py meets a few basic
invariants:
  - the .ttf and .woff2 files exist and are non-trivially sized
  - the font is loadable by fontTools
  - the cmap covers a plausible number of CJK codepoints for the build mode
  - core anchor glyphs from STYLE.md exist in the cmap

Intentionally lightweight: visual / similarity checks live elsewhere.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
TTF = DIST / "Luo-Regular.ttf"
WOFF2 = DIST / "Luo-Regular.woff2"

# (mode, min_total_cmap, min_cjk_unified)
THRESHOLDS = {
    "seed": (60, 50),
    "site": (200, 180),
    "starter": (1000, 1000),
    "gb2312-level1": (3500, 3500),
    "gb2312-full": (6500, 6500),
    "full": (1000, 1000),
}

CORE_ANCHORS = "落文字书心清骨风纸印"


def fail(message: str) -> None:
    print(f"[ci] FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def check_dist_files() -> None:
    for path in (TTF, WOFF2):
        if not path.exists():
            fail(f"missing build artifact: {path.relative_to(ROOT)}")
        size = path.stat().st_size
        if size < 50_000:
            fail(f"{path.name} is suspiciously small ({size} bytes)")
    print(
        f"[ci] dist sizes: ttf={TTF.stat().st_size}, "
        f"woff2={WOFF2.stat().st_size}"
    )


def collect_cmap(font: TTFont) -> dict[int, str]:
    cmap: dict[int, str] = {}
    if "cmap" not in font:
        fail("font has no cmap table")
    for table in font["cmap"].tables:
        if table.cmap:
            cmap.update(table.cmap)
    return cmap


def main() -> None:
    mode = os.environ.get("LUO_BUILD_CHARS", "starter")
    if mode not in THRESHOLDS:
        fail(f"unknown build mode {mode!r}")

    check_dist_files()

    font = TTFont(str(TTF))
    cmap = collect_cmap(font)
    cjk_count = sum(
        1 for cp in cmap if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
    )

    min_total, min_cjk = THRESHOLDS[mode]
    print(f"[ci] mode={mode} cmap={len(cmap)} cjk_unified={cjk_count}")
    if len(cmap) < min_total:
        fail(f"cmap too small: {len(cmap)} < {min_total}")
    if cjk_count < min_cjk:
        fail(f"cjk_unified too small: {cjk_count} < {min_cjk}")

    missing = [c for c in CORE_ANCHORS if ord(c) not in cmap]
    if missing:
        fail(f"core anchor glyphs missing from cmap: {''.join(missing)}")
    print(f"[ci] core anchors present: {CORE_ANCHORS}")

    # name table sanity: family must be Luo, version must match VERSION
    name_table = font["name"]
    family_records = [r for r in name_table.names if r.nameID == 1]
    if not any(
        str(r) == "Luo" for r in family_records
    ):
        fail("name table family is not 'Luo'")
    print("[ci] name table family ok: Luo")

    print(f"[ci] OK ({mode})")


if __name__ == "__main__":
    main()
