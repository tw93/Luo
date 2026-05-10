"""Render a local Luo refinement comparison sheet.

The sheet is a human QA artifact for v0.4.8+ tuning. It compares the source
font, an optional private style reference, two historical Luo baselines,
and the current build across the glyph groups that tend to expose roughness.

The private reference (Tsanger Print Kai or any commercial print-kai font)
is supplied via the ``LUO_PRIVATE_KAI_REF`` environment variable, mirroring
the convention used by ``compare_to.py``. When the env var is unset or the
file does not exist, the private column is silently skipped so the script
runs cleanly on contributor machines and CI without the private input.

Output stays under ignored ``local/ref/renders/``.

Run:
    python3 scripts/render_refinement_sheet.py
    LUO_PRIVATE_KAI_REF=/path/to/private.ttf python3 scripts/render_refinement_sheet.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_FONT = ROOT / "source" / "LXGWWenKaiScreen-Regular.ttf"
CURRENT_LUO = ROOT / "dist" / "Luo-Regular.ttf"
_PRIVATE_REF_ENV = os.environ.get("LUO_PRIVATE_KAI_REF")
PRIVATE_REF = Path(_PRIVATE_REF_ENV) if _PRIVATE_REF_ENV else None
BASELINE_DIR = ROOT / "local" / "ref" / "baselines"
DEFAULT_OUTPUT = ROOT / "local" / "ref" / "renders" / "v048_refinement_sheet.png"

BASELINE_SPECS = {
    "Luo v0.3": ("v0.3.0-final:dist/Luo-Regular.ttf", BASELINE_DIR / "Luo-v0.3.0-final.ttf"),
    "Luo v0.4.5": ("4337744:dist/Luo-Regular.ttf", BASELINE_DIR / "Luo-v0.4.5.ttf"),
}

ROWS = [
    ("reported", 52, "月答答案"),
    ("p0-grid", 52, "曲重田首里"),
    ("p0-hook", 52, "争色事第使"),
    ("p0-comp", 52, "技盖准装输"),
    ("p1-grid-a", 44, "虽县单盘基算"),
    ("p1-grid-b", 44, "相官抽自堵盏"),
    ("p1-grid-c", 44, "革由吕审目"),
    ("p1-hook-a", 44, "求角走种值快"),
    ("p1-hook-b", 44, "强支别战同也"),
    ("p1-hook-c", 44, "持联继服"),
    ("p1-comp-a", 44, "者邑棹斗身蓄"),
    ("p1-comp-b", 44, "考难每再维植"),
    ("p1-comp-c", 44, "徊岫鱼查扁主"),
    ("p1-comp-d", 44, "轼复建理具郁"),
    ("p1-rad", 52, "往轻给法浅"),
    ("p1-roof", 52, "宙宇安定宿"),
    ("p3-src-a", 44, "曲抽角重争"),
    ("p3-src-b", 44, "盘者岫虽盏"),
    ("p3-src-c", 44, "求种复基斗"),
    ("p3-src-d", 44, "色相革事再"),
    ("p3-src-e", 44, "棹堵难官县"),
    ("p3-src-f", 44, "每植堆"),
    ("p4-src-a", 44, "去要共朗型"),
    ("p4-src-b", 44, "携考单技粟"),
    ("p4-src-c", 44, "稚第樽便理"),
    ("p4-src-d", 44, "鱼具邑仲皋"),
    ("p4-src-e", 44, "独值律其身"),
    ("p4-src-f", 44, "虾快看腹雅"),
    ("p4-src-g", 44, "柯距展更鹿"),
    ("p4-src-h", 44, "直扁耳槊由"),
    ("p2-src-a", 44, "堆共皋其组"),
    ("p2-src-b", 44, "要稚携净直"),
    ("p2-src-c", 44, "粟独樽鹿古"),
    ("p2-src-d", 44, "耳真距型律"),
    ("p2-src-e", 44, "便更寓展虾"),
    ("p2-src-f", 44, "仲朗果免雅"),
    ("p2-src-g", 44, "暑腹窗柯蛟"),
    ("p2-src-h", 44, "着看郎槊"),
    ("core", 56, "落文清骨风"),
    ("hook", 46, "字书亭序家"),
    ("dense", 42, "藏霜馈赢魔"),
    ("frame", 46, "国回日目月"),
    ("stack", 42, "实寒库头眷"),
    ("generic", 42, "孟答曾章由"),
    ("body", 28, "兰亭集序永和九年"),
]


def _materialize_git_font(spec: str, out: Path) -> Path:
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    data = subprocess.check_output(["git", "show", spec], cwd=ROOT)
    out.write_bytes(data)
    return out


def _available_fonts() -> list[tuple[str, Path]]:
    fonts: list[tuple[str, Path]] = [("LXGW source", SOURCE_FONT)]
    if PRIVATE_REF is not None and PRIVATE_REF.exists():
        fonts.append(("Private kai", PRIVATE_REF))
    elif _PRIVATE_REF_ENV:
        print(f"[sheet] LUO_PRIVATE_KAI_REF set but file missing: {_PRIVATE_REF_ENV}; skipping")
    for label, (git_spec, out) in BASELINE_SPECS.items():
        try:
            fonts.append((label, _materialize_git_font(git_spec, out)))
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"[sheet] skipped {label}: cannot read {git_spec}")
    fonts.append(("Luo current", CURRENT_LUO))
    return [(label, path) for label, path in fonts if path.exists()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    from PIL import Image, ImageDraw, ImageFont

    args = parse_args()
    fonts = _available_fonts()
    if not fonts:
        raise SystemExit("[sheet] no fonts available")

    label_font = ImageFont.load_default()
    font_objs = {
        (label, size): ImageFont.truetype(str(path), size)
        for label, path in fonts
        for _row_label, size, _text in ROWS
    }

    label_w = 112
    col_w = 330
    header_h = 72
    row_h = 104
    width = label_w + col_w * len(fonts) + 24
    height = header_h + row_h * len(ROWS) + 24
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    draw.text((16, 18), "Luo v0.4.8 refinement comparison", fill=(20, 20, 20), font=label_font)
    for i, (label, _path) in enumerate(fonts):
        x = label_w + i * col_w + 10
        draw.text((x, 46), label, fill=(70, 70, 70), font=label_font)

    for row_index, (row_label, size, text) in enumerate(ROWS):
        y = header_h + row_index * row_h
        fill = (250, 250, 248) if row_index % 2 else (255, 255, 255)
        draw.rectangle((0, y, width, y + row_h), fill=fill)
        draw.text((16, y + 42), row_label, fill=(80, 80, 80), font=label_font)
        for i, (label, _path) in enumerate(fonts):
            x = label_w + i * col_w + 10
            draw.text((x, y + 18), text, fill=(0, 0, 0), font=font_objs[(label, size)])
            draw.line((x, y + 82, x + col_w - 30, y + 82), fill=(235, 235, 235))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.output)
    try:
        display = args.output.resolve().relative_to(ROOT.resolve())
    except ValueError:
        display = args.output
    print(f"[sheet] wrote {display}")


if __name__ == "__main__":
    main()
