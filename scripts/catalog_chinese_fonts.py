"""
Build GB2312 audit pages for Luo.

The optional scanner can inspect local font files under /Users/tang/www, but
the default build skips that step and writes:
  - proof/gb2312.json
  - proof/gb2312.html
  - proof/gb2312-preview.html
  - proof/gb2312-preview.pdf
  - proof/gb2312-preview.png
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTCollection, TTFont

logging.getLogger("fontTools").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent.parent
PROOF_DIR = ROOT / "proof"
DEFAULT_WWW_ROOT = Path("/Users/tang/www")
DEFAULT_JSON = PROOF_DIR / "gb2312.json"
DEFAULT_HTML = PROOF_DIR / "gb2312.html"
DEFAULT_PREVIEW_HTML = PROOF_DIR / "gb2312-preview.html"
DEFAULT_PDF = PROOF_DIR / "gb2312-preview.pdf"
DEFAULT_PNG = PROOF_DIR / "gb2312-preview.png"
LUO_FONT = ROOT / "dist" / "Luo-Regular.ttf"
LUO_WEB_FONT = ROOT / "dist" / "Luo-Regular.woff2"
OPTIMIZED_CHARS = PROOF_DIR / "optimized_chars.txt"

FONT_SUFFIXES = (".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2")
CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
)
FIXTURE_PATH_MARKERS = {
    ".venv",
    "deps",
    "expected",
    "fixture",
    "fixtures",
    "fuzzing",
    "node_modules",
    "test",
    "tests",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Luo GB2312 calibration pages."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_WWW_ROOT)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--preview-html", type=Path, default=DEFAULT_PREVIEW_HTML)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--png", type=Path, default=DEFAULT_PNG)
    parser.add_argument("--preview-dpi", type=int, default=150)
    parser.add_argument("--no-preview", action="store_true")
    parser.add_argument(
        "--include-local-fonts",
        action="store_true",
        help="Also scan local fonts and include them in proof/gb2312.json.",
    )
    parser.add_argument("--min-cjk", type=int, default=300)
    parser.add_argument("--min-gb", type=int, default=100)
    parser.add_argument(
        "--method",
        choices=("auto", "mdfind", "find"),
        default="auto",
        help="Discovery method. auto uses Spotlight first, find as fallback.",
    )
    return parser.parse_args()


def run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )


def is_cjk_cp(cp: int) -> bool:
    return any(start <= cp <= end for start, end in CJK_RANGES)


def gb2312_chars() -> tuple[str, str, str]:
    level1: list[str] = []
    level2: list[str] = []
    for high in range(0xB0, 0xD8):
        for low in range(0xA1, 0xFF):
            try:
                ch = bytes((high, low)).decode("gb2312")
            except UnicodeDecodeError:
                continue
            if len(ch) == 1 and is_cjk_cp(ord(ch)):
                level1.append(ch)
    for high in range(0xD8, 0xF8):
        for low in range(0xA1, 0xFF):
            try:
                ch = bytes((high, low)).decode("gb2312")
            except UnicodeDecodeError:
                continue
            if len(ch) == 1 and is_cjk_cp(ord(ch)):
                level2.append(ch)
    all_chars = "".join(dict.fromkeys(level1 + level2))
    return "".join(level1), "".join(level2), all_chars


def discover_with_mdfind(root: Path) -> list[Path]:
    if not shutil.which("mdfind"):
        return []

    query = (
        'kMDItemContentTypeTree == "public.font"'
        ' || kMDItemFSName == "*.ttf"'
        ' || kMDItemFSName == "*.otf"'
        ' || kMDItemFSName == "*.ttc"'
        ' || kMDItemFSName == "*.otc"'
        ' || kMDItemFSName == "*.woff"'
        ' || kMDItemFSName == "*.woff2"'
    )
    proc = subprocess.run(
        ["mdfind", "-onlyin", str(root), query],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return []
    return [Path(line) for line in proc.stdout.splitlines() if line.strip()]


def discover_with_find(root: Path) -> list[Path]:
    paths: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in {".git", ".venv", "__pycache__"}
        ]
        for filename in filenames:
            path = Path(current_root) / filename
            if path.suffix.lower() in FONT_SUFFIXES:
                paths.append(path)
    return paths


def discover_font_paths(root: Path, method: str) -> tuple[list[Path], str]:
    paths: list[Path] = []
    used = method
    if method in {"auto", "mdfind"}:
        paths = discover_with_mdfind(root)
        used = "mdfind"
    if method == "find" or (method == "auto" and not paths):
        paths = discover_with_find(root)
        used = "find"

    unique: dict[str, Path] = {}
    for path in paths:
        if path.suffix.lower() not in FONT_SUFFIXES:
            continue
        try:
            resolved = str(path.resolve())
        except OSError:
            continue
        unique[resolved] = Path(resolved)
    return sorted(unique.values(), key=lambda p: str(p).lower()), used


def font_name(font: TTFont, name_id: int) -> str:
    if "name" not in font:
        return ""
    records = font["name"].names
    preferred = sorted(
        records,
        key=lambda rec: (
            rec.nameID != name_id,
            rec.platformID != 3,
            rec.langID not in {0x804, 0x409},
        ),
    )
    for record in preferred:
        if record.nameID != name_id:
            continue
        try:
            value = record.toUnicode().strip()
        except UnicodeError:
            continue
        if value:
            return value
    return ""


def font_codepoints(font: TTFont) -> set[int]:
    cps: set[int] = set()
    if "cmap" not in font:
        return cps
    for table in font["cmap"].tables:
        if table.cmap:
            cps.update(table.cmap.keys())
    return cps


def best_cmap(font: TTFont) -> dict[int, str]:
    cmap = font.getBestCmap()
    if cmap:
        return cmap
    merged: dict[int, str] = {}
    if "cmap" in font:
        for table in font["cmap"].tables:
            if table.cmap:
                merged.update(table.cmap)
    return merged


def glyph_has_outline(glyph_set, glyph_name: str) -> bool:
    if glyph_name not in glyph_set:
        return False
    pen = BoundsPen(glyph_set)
    try:
        glyph_set[glyph_name].draw(pen)
    except Exception:  # noqa: BLE001
        return True
    if pen.bounds is None:
        return False
    x_min, y_min, x_max, y_max = pen.bounds
    return x_max > x_min and y_max > y_min


def visible_gb2312_count(font: TTFont, gb_set: set[int]) -> int:
    cmap = best_cmap(font)
    if not cmap:
        return 0
    glyph_set = font.getGlyphSet()
    count = 0
    for cp in gb_set:
        glyph_name = cmap.get(cp)
        if glyph_name and glyph_has_outline(glyph_set, glyph_name):
            count += 1
    return count


def inspect_ttfont(
    font: TTFont,
    path: Path,
    face_index: int,
    gb_set: set[int],
    www_root: Path,
) -> dict[str, object]:
    cps = font_codepoints(font)
    cjk_count = sum(1 for cp in cps if is_cjk_cp(cp))
    gb_cmap_count = len(gb_set.intersection(cps))
    gb_visible_count = visible_gb2312_count(font, gb_set)
    family = font_name(font, 1) or path.stem
    subfamily = font_name(font, 2) or "Regular"
    full_name = font_name(font, 4) or f"{family} {subfamily}".strip()
    rel_path = os.path.relpath(path, www_root)
    rel_parts = {part.lower() for part in Path(rel_path).parts}
    is_fixture = bool(rel_parts.intersection(FIXTURE_PATH_MARKERS))
    digest = hashlib.sha1(f"{path}:{face_index}".encode("utf-8")).hexdigest()[:10]
    return {
        "id": f"font-{digest}",
        "family": family,
        "subfamily": subfamily,
        "full_name": full_name,
        "path": str(path),
        "relative_path": rel_path,
        "face_index": face_index,
        "format": path.suffix.lower().lstrip("."),
        "file_size": path.stat().st_size,
        "source_kind": "dependency_or_test" if is_fixture else "project",
        "is_likely_fixture": is_fixture,
        "cjk_count": cjk_count,
        "gb2312_cmap_count": gb_cmap_count,
        "gb2312_count": gb_visible_count,
        "gb2312_rate": gb_visible_count / len(gb_set) if gb_set else 0,
    }


def inspect_font_file(
    path: Path,
    gb_set: set[int],
    www_root: Path,
    min_cjk: int,
    min_gb: int,
) -> tuple[list[dict[str, object]], str | None, int]:
    records: list[dict[str, object]] = []
    suffix = path.suffix.lower()
    face_count = 0
    try:
        if suffix in {".ttc", ".otc"}:
            collection = TTCollection(str(path), lazy=True)
            try:
                for index, font in enumerate(collection.fonts):
                    face_count += 1
                    record = inspect_ttfont(font, path, index, gb_set, www_root)
                    if (
                        int(record["cjk_count"]) >= min_cjk
                        or int(record["gb2312_count"]) >= min_gb
                    ) and int(record["gb2312_count"]) >= min_gb:
                        records.append(record)
            finally:
                for font in collection.fonts:
                    font.close()
        else:
            font = TTFont(str(path), lazy=True)
            try:
                face_count = 1
                record = inspect_ttfont(font, path, 0, gb_set, www_root)
                if (
                    int(record["cjk_count"]) >= min_cjk
                    or int(record["gb2312_count"]) >= min_gb
                ) and int(record["gb2312_count"]) >= min_gb:
                    records.append(record)
            finally:
                font.close()
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}", face_count
    return records, None, face_count


def load_luo_state(gb_chars: str) -> dict[str, object]:
    gb_set = {ord(ch) for ch in gb_chars}
    covered: set[int] = set()
    if LUO_FONT.exists():
        font = TTFont(str(LUO_FONT), lazy=True)
        try:
            covered = font_codepoints(font)
        finally:
            font.close()

    optimized = set()
    if OPTIMIZED_CHARS.exists():
        optimized = set(OPTIMIZED_CHARS.read_text(encoding="utf-8"))

    gb_covered = [ch for ch in gb_chars if ord(ch) in covered]
    gb_missing = [ch for ch in gb_chars if ord(ch) not in covered]
    gb_optimized = [ch for ch in gb_chars if ch in optimized and ord(ch) in covered]
    gb_unoptimized = [
        ch for ch in gb_chars if ord(ch) in covered and ch not in optimized
    ]
    return {
        "font": str(LUO_FONT),
        "web_font": str(LUO_WEB_FONT),
        "gb2312_count": len(gb_chars),
        "covered_count": len(gb_covered),
        "missing_count": len(gb_missing),
        "optimized_count": len(gb_optimized),
        "unoptimized_covered_count": len(gb_unoptimized),
        "covered_chars": "".join(gb_covered),
        "missing_chars": "".join(gb_missing),
        "optimized_chars": "".join(gb_optimized),
        "unoptimized_covered_chars": "".join(gb_unoptimized),
    }


def css_font_url(path: Path) -> str:
    try:
        return "../" + path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        pass
    return path.resolve().as_uri()


def css_format(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".ttf": "truetype",
        ".otf": "opentype",
        ".woff": "woff",
        ".woff2": "woff2",
        ".ttc": "collection",
        ".otc": "collection",
    }.get(suffix, "truetype")


def bytes_label(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def html_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def font_face_css(records: list[dict[str, object]], include_records: bool = True) -> str:
    rules = [
        (
            '@font-face{font-family:"LuoAudit";'
            f"src:url({json.dumps(css_font_url(LUO_WEB_FONT))}) "
            'format("woff2");font-weight:400;font-style:normal;font-display:swap;}'
        )
    ]
    if include_records:
        for record in records:
            path = Path(str(record["path"]))
            face_id = html_escape(record["id"])
            rules.append(
                f'@font-face{{font-family:"{face_id}";'
                f"src:url({json.dumps(css_font_url(path))}) "
                f'format("{css_format(str(path))}");'
                "font-weight:400;font-style:normal;font-display:swap;}"
            )
    return "\n".join(rules)


def render_char_cells(
    gb_level1: str,
    gb_level2: str,
    covered_chars: set[str],
) -> str:
    cells: list[str] = []
    for level, chars in (("1", gb_level1), ("2", gb_level2)):
        for index, ch in enumerate(chars, start=1):
            status = "covered" if ch in covered_chars else "missing"
            code = f"U+{ord(ch):04X}"
            cells.append(
                '<span class="char-cell '
                f'{status}" data-char="{html_escape(ch)}" '
                f'data-code="{code}" data-level="{level}" data-status="{status}" '
                f'data-index="{index}">'
                f'<b>{html_escape(ch)}</b></span>'
            )
    return "\n".join(cells)


def render_preview_cells(chars: str, covered_chars: set[str]) -> str:
    cells: list[str] = []
    for ch in chars:
        status = "covered" if ch in covered_chars else "missing"
        cells.append(
            f'<span class="cell {status}"><b>{html_escape(ch)}</b></span>'
        )
    return "\n".join(cells)


def render_html(
    records: list[dict[str, object]],
    gb_level1: str,
    gb_level2: str,
    luo: dict[str, object],
    report: dict[str, object],
) -> str:
    gb_chars = gb_level1 + gb_level2
    gb_total = len(gb_chars)
    covered_chars = set(str(luo["covered_chars"]))
    cells = render_char_cells(gb_level1, gb_level2, covered_chars)
    font_css = font_face_css(records, include_records=False)
    generated = html_escape(report["generated_at"])
    covered_count = int(luo["covered_count"])
    missing_count = int(luo["missing_count"])
    coverage_rate = percent(covered_count / gb_total)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Luo 常用字校准</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="../assets/styles/luo.css">
  <style>
    {font_css}
    :root {{
      --paper: #f5f4ed;
      --panel: #fbfaf6;
      --ink: #151513;
      --muted: #68665f;
      --line: #dedbd0;
      --line-strong: #c6c1b3;
      --blue: #1B365D;
      --accent: #1B365D;
      --green: #2f6b50;
      --warm: #8c5b2f;
      --red: #9b3f33;
      --latin: Seravek, Candara, Optima, "Avenir Next", "SF Pro Text", sans-serif;
      --audit-fallback: "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", sans-serif;
      --audit-text: "LuoAudit", Seravek, Candara, Optima, "Noto Sans CJK SC", sans-serif;
      --luo: "LuoAudit", var(--audit-fallback);
      --mono: "JetBrains Mono", "SF Mono", Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: var(--audit-text);
      line-height: 1.55;
      letter-spacing: 0;
      -webkit-font-smoothing: antialiased;
    }}
    main {{ max-width: 1480px; margin: 0 auto; padding: 36px 42px 72px; }}
    header {{ margin-bottom: 12px; }}
    .page-nav {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      margin: 0 0 30px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }}
    .crumb {{
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-family: var(--audit-text);
      font-size: 13px;
    }}
    .crumb a {{
      color: var(--ink);
      font-weight: 600;
      text-decoration: none;
    }}
    .crumb a:hover {{ color: var(--accent); }}
    .crumb strong {{ color: var(--accent); font-weight: 500; }}
    .proof-nav-links {{
      display: flex;
      align-items: center;
      gap: 14px;
      font-family: var(--audit-text);
      font-size: 13px;
    }}
    .proof-nav-links a {{
      color: var(--muted);
      text-decoration: none;
    }}
    .proof-nav-links a:hover {{ color: var(--accent); }}
    h1 {{ margin: 0; font-size: 56px; font-weight: 500; line-height: 1.04; color: var(--ink); }}
    .status-line {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 18px;
      margin: 10px 0 0;
      color: var(--muted);
      font-family: var(--audit-text);
      font-size: 13px;
    }}
    .status-line b {{ color: var(--ink); font-weight: 600; }}
    .count-line {{ margin: 8px 0 0; color: var(--muted); font-family: var(--audit-text); font-size: 12px; }}
    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 2;
      display: grid;
      grid-template-columns: minmax(240px, 1fr) auto;
      gap: 12px;
      align-items: center;
      padding: 10px 0 12px;
      background: var(--paper);
    }}
    input[type="search"] {{
      width: 100%;
      min-height: 40px;
      border: 1px solid var(--line-strong);
      background: var(--panel);
      color: var(--ink);
      padding: 0 12px;
      font-family: var(--audit-text);
      font-size: 14px;
      border-radius: 4px;
    }}
    .segmented {{ display: flex; gap: 4px; background: transparent; }}
    .segmented button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--muted);
      min-height: 38px;
      padding: 0 12px;
      font-family: var(--audit-text);
      font-size: 13px;
      line-height: 1;
      cursor: pointer;
      border-radius: 4px;
    }}
    .segmented button::before {{
      content: "";
      display: block;
      flex: 0 0 8px;
      width: 8px;
      height: 8px;
      border: 1px solid var(--line-strong);
      background: #fffdf8;
      box-sizing: border-box;
      transform: translateY(.02em);
    }}
    .segmented button[data-filter="covered"]::before {{ border: 2px solid var(--ink); }}
    .segmented button[data-filter="missing"]::before {{ background: #efebe0; }}
    .segmented button[data-filter="all"]::before {{ display: none; }}
    .segmented button.active {{ background: var(--ink); border-color: var(--ink); color: #fff; }}
    .char-grid {{
      --cell-size: 62px;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(var(--cell-size), var(--cell-size)));
      gap: 7px;
      align-items: start;
      justify-content: start;
      margin-top: 14px;
    }}
    .char-cell {{
      position: relative;
      aspect-ratio: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 2px;
      contain: layout paint style;
      content-visibility: auto;
      contain-intrinsic-size: var(--cell-size) var(--cell-size);
      font-family: var(--audit-fallback);
      font-size: calc(var(--cell-size) * .54);
      line-height: 1;
      color: var(--ink);
      background-color: #fffdf8;
      background-image:
        linear-gradient(to right, transparent calc(50% - .5px), rgba(20,20,19,.13) calc(50% - .5px), rgba(20,20,19,.13) calc(50% + .5px), transparent calc(50% + .5px)),
        linear-gradient(to bottom, transparent calc(50% - .5px), rgba(20,20,19,.13) calc(50% - .5px), rgba(20,20,19,.13) calc(50% + .5px), transparent calc(50% + .5px));
    }}
    .char-cell b {{ font-weight: 400; }}
    .char-cell.covered {{ border-color: var(--ink); font-family: var(--luo); }}
    .char-cell.missing {{ font-family: var(--audit-fallback); }}
    .char-cell.missing b {{ opacity: .32; }}
    .char-cell.missing {{ background-color: #efebe0; }}
    .char-cell.hidden {{ display: none; }}
    .char-grid[data-filter="covered"] .char-cell:not(.covered),
    .char-grid[data-filter="missing"] .char-cell:not(.missing),
    .char-grid.is-searching .char-cell.search-hidden {{
      display: none;
    }}
    .audit-meta {{ margin-top: 18px; color: var(--muted); font: 11px var(--latin); }}
    @media (max-width: 980px) {{
      main {{ padding: 28px 18px 64px; }}
      .page-nav {{ align-items: flex-start; flex-direction: column; gap: 10px; }}
      .proof-nav-links {{ flex-wrap: wrap; gap: 10px; }}
      .toolbar {{ grid-template-columns: 1fr; }}
      .char-grid {{ --cell-size: 54px; gap: 6px; }}
    }}
  </style>
</head>
<body>
<main>
  <nav class="page-nav" aria-label="page navigation">
    <div class="crumb">
      <a href="../index.html">Luo 落文</a>
      <span>/</span>
      <strong>常用字校准</strong>
    </div>
    <div class="proof-nav-links">
      <a href="../index.html#calibration">官网字样</a>
    </div>
  </nav>
  <header>
    <h1>常用字校准</h1>
    <p class="status-line">
      <span><b>{gb_total}</b> GB2312</span>
      <span><b>{covered_count}</b> 已覆盖, {coverage_rate}</span>
      <span><b>{missing_count}</b> 待补字</span>
    </p>
  </header>

  <div class="toolbar">
    <input id="charSearch" type="search" placeholder="搜索汉字或 Unicode, 例如 落 / 843D" autocomplete="off">
    <div class="segmented" role="group" aria-label="character filters">
      <button type="button" class="active" data-filter="all">全部</button>
      <button type="button" data-filter="covered">已覆盖</button>
      <button type="button" data-filter="missing">待补字</button>
    </div>
  </div>
  <p class="count-line" id="visibleCount">显示 {gb_total} / {gb_total} 字，当前缺字 {missing_count} 个。</p>
  <div class="char-grid" id="charGrid" data-filter="all" aria-label="GB2312 common character grid">
{cells}
  </div>

  <footer class="audit-meta">Generated: {generated}</footer>
</main>
<script>
  const grid = document.getElementById('charGrid');
  const cells = Array.from(document.querySelectorAll('.char-cell'));
  const search = document.getElementById('charSearch');
  const visibleCount = document.getElementById('visibleCount');
  const buttons = Array.from(document.querySelectorAll('[data-filter]'));
  const filterCounts = {{
    all: {gb_total},
    covered: {covered_count},
    missing: {missing_count}
  }};
  let activeFilter = 'all';

  function matchesFilter(cell) {{
    if (activeFilter === 'all') return true;
    return cell.dataset.status === activeFilter;
  }}

  function matchesSearch(cell, query) {{
    if (!query) return true;
    const normalized = query.toUpperCase().replace(/^U\\+/, '');
    return cell.dataset.char.includes(query) || cell.dataset.code.includes(normalized);
  }}

  function updateGrid() {{
    const query = search.value.trim();
    grid.dataset.filter = activeFilter;
    grid.classList.toggle('is-searching', Boolean(query));
    if (!query) {{
      visibleCount.textContent = `显示 ${{filterCounts[activeFilter]}} / {gb_total} 字，当前缺字 {missing_count} 个。`;
      return;
    }}
    let shown = 0;
    for (const cell of cells) {{
      const searchVisible = matchesSearch(cell, query);
      cell.classList.toggle('search-hidden', !searchVisible);
      if (matchesFilter(cell) && searchVisible) shown += 1;
    }}
    visibleCount.textContent = `显示 ${{shown}} / {gb_total} 字，当前缺字 {missing_count} 个。`;
  }}

  buttons.forEach((button) => {{
    button.addEventListener('click', () => {{
      activeFilter = button.dataset.filter;
      buttons.forEach((item) => item.classList.toggle('active', item === button));
      updateGrid();
    }});
  }});
  search.addEventListener('input', updateGrid);
</script>
</body>
</html>
"""


def render_preview_html(
    records: list[dict[str, object]],
    gb_level1: str,
    luo: dict[str, object],
    report: dict[str, object],
) -> str:
    gb_total = int(luo["gb2312_count"])
    covered_count = int(luo["covered_count"])
    missing_count = int(luo["missing_count"])
    covered_chars = set(str(luo["covered_chars"]))
    font_css = font_face_css(records, include_records=False)
    preview_chars = gb_level1[:1155]
    cells = render_preview_cells(preview_chars, covered_chars)
    generated = html_escape(report["generated_at"])

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Luo 中文字体校准截图</title>
  <link rel="stylesheet" href="../assets/styles/luo.css">
  <style>
    {font_css}
    @page {{ size: A4 portrait; margin: 11mm; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #f5f4ed;
      color: #151513;
      font-family: "LuoAudit", "Noto Sans CJK SC", sans-serif;
      line-height: 1.45;
      letter-spacing: 0;
    }}
    h1 {{ margin: 0; color: #151513; font-size: 34pt; font-weight: 500; line-height: 1.05; }}
    h2 {{ margin: 0 0 6pt; font-size: 14pt; font-weight: 500; }}
    p {{ margin: 0; color: #68665f; font-size: 7.5pt; }}
    .top {{ border-bottom: .8pt solid #c6c1b3; padding-bottom: 9pt; }}
    .lede {{ width: 130mm; margin-top: 5pt; font-size: 9pt; color: #504e49; }}
    .meta {{ position: absolute; right: 11mm; top: 11mm; text-align: right; font: 7pt Seravek, Candara, Optima, "Avenir Next", sans-serif; color: #68665f; }}
    .calibration {{ margin-top: 10pt; }}
    .grid {{ font-size: 0; line-height: 0; }}
    .cell {{
      display: inline-block;
      position: relative;
      width: 17pt;
      height: 17pt;
      line-height: 17pt;
      text-align: center;
      vertical-align: top;
      border: .45pt solid #dedbd0;
      margin: 0 .8pt .8pt 0;
      background: #fffdf8;
      font-size: 10.2pt;
      color: #151513;
    }}
    .cell::before, .cell::after {{
      content: "";
      position: absolute;
      background: rgba(27, 54, 93, .18);
    }}
    .cell::before {{ left: 50%; top: 0; width: .35pt; height: 100%; }}
    .cell::after {{ top: 50%; left: 0; height: .35pt; width: 100%; }}
    .cell b {{ position: relative; z-index: 1; font-weight: 400; }}
    .cell.covered {{ border-color: #151513; }}
    .cell.missing {{ background: #efebe0; color: rgba(21, 21, 19, .34); }}
    .legend {{ margin-top: 6pt; color: #68665f; font: 7pt Seravek, Candara, Optima, "Avenir Next", sans-serif; }}
    .legend span {{ margin-right: 9pt; }}
  </style>
</head>
<body>
  <div class="top">
    <h1>常用字校准</h1>
    <p class="lede">GB2312 {gb_total} 字，已覆盖 {covered_count}，待补 {missing_count}。交互页：proof/gb2312.html。</p>
    <div class="meta">Generated<br>{generated}</div>
  </div>
  <section class="calibration">
    <h2>一级常用字田字格抽样</h2>
    <div class="grid">
{cells}
    </div>
    <p class="legend"><span>深框: 已覆盖</span><span>浅底: 待补</span></p>
  </section>
</body>
</html>
"""


def render_preview(html_path: Path, pdf_path: Path, png_path: Path, dpi: int) -> dict[str, object]:
    weasyprint = shutil.which("weasyprint")
    pdftoppm = shutil.which("pdftoppm")
    if not weasyprint or not pdftoppm:
        missing = []
        if not weasyprint:
            missing.append("weasyprint")
        if not pdftoppm:
            missing.append("pdftoppm")
        return {
            "ok": False,
            "reason": f"missing tools: {', '.join(missing)}",
            "html": str(html_path),
            "pdf": str(pdf_path),
            "png": str(png_path),
        }

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    pdf_result = run_command([weasyprint, str(html_path), str(pdf_path)])
    if pdf_result.returncode != 0:
        return {
            "ok": False,
            "reason": pdf_result.stderr.strip() or pdf_result.stdout.strip(),
            "html": str(html_path),
            "pdf": str(pdf_path),
            "png": str(png_path),
        }

    with tempfile.TemporaryDirectory(prefix="luo-font-audit-") as tmp:
        prefix = Path(tmp) / "preview"
        png_result = run_command(
            [
                pdftoppm,
                "-r",
                str(dpi),
                "-f",
                "1",
                "-l",
                "1",
                "-png",
                str(pdf_path),
                str(prefix),
            ]
        )
        if png_result.returncode != 0:
            return {
                "ok": False,
                "reason": png_result.stderr.strip() or png_result.stdout.strip(),
                "html": str(html_path),
                "pdf": str(pdf_path),
                "png": str(png_path),
            }
        generated = prefix.with_name(prefix.name + "-1.png")
        if not generated.exists():
            return {
                "ok": False,
                "reason": "pdftoppm did not produce page 1 PNG",
                "html": str(html_path),
                "pdf": str(pdf_path),
                "png": str(png_path),
            }
        shutil.copyfile(generated, png_path)

    return {
        "ok": True,
        "method": "weasyprint + pdftoppm",
        "dpi": dpi,
        "html": str(html_path),
        "pdf": str(pdf_path),
        "png": str(png_path),
    }


def build_report(args: argparse.Namespace) -> dict[str, object]:
    gb_level1, gb_level2, gb_chars = gb2312_chars()
    if len(gb_chars) != 6763:
        sys.exit(f"[luo] expected 6763 GB2312 chars, got {len(gb_chars)}")

    gb_set = {ord(ch) for ch in gb_chars}

    records: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    font_paths: list[Path] = []
    method = "disabled"
    face_count = 0
    if args.include_local_fonts:
        font_paths, method = discover_font_paths(args.root, args.method)
        for path in font_paths:
            inspected, error, faces = inspect_font_file(
                path, gb_set, args.root, args.min_cjk, args.min_gb
            )
            face_count += faces
            records.extend(inspected)
            if error:
                errors.append({"path": str(path), "error": error})

        records.sort(
            key=lambda item: (
                bool(item["is_likely_fixture"]),
                -int(item["gb2312_count"]),
                -int(item["cjk_count"]),
                str(item["relative_path"]).lower(),
                int(item["face_index"]),
            )
        )
    luo = load_luo_state(gb_chars)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scan_root": str(args.root),
        "retrieval": {
            "method": method,
            "font_files_seen": len(font_paths),
            "font_faces_seen": face_count,
            "min_cjk": args.min_cjk,
            "min_gb2312": args.min_gb,
            "errors": errors[:80],
            "error_count": len(errors),
        },
        "gb2312": {
            "count": len(gb_chars),
            "level1_count": len(gb_level1),
            "level2_count": len(gb_level2),
            "chars": gb_chars,
        },
        "luo": luo,
        "fonts": records,
    }

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(
        render_html(records, gb_level1, gb_level2, luo, report),
        encoding="utf-8",
    )
    args.preview_html.parent.mkdir(parents=True, exist_ok=True)
    args.preview_html.write_text(
        render_preview_html(records, gb_level1, luo, report),
        encoding="utf-8",
    )
    if args.no_preview:
        report["preview"] = {
            "ok": False,
            "reason": "disabled by --no-preview",
            "html": str(args.preview_html),
            "pdf": str(args.pdf),
            "png": str(args.png),
        }
    else:
        report["preview"] = render_preview(
            args.preview_html, args.pdf, args.png, args.preview_dpi
        )

    args.json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    args = parse_args()
    report = build_report(args)
    if args.include_local_fonts:
        print(
            "[luo] cataloged "
            f"{len(report['fonts'])} Chinese font faces from "
            f"{report['retrieval']['font_files_seen']} font files"
        )
    else:
        print("[luo] skipped local font catalog")
    print(f"[luo] wrote {args.json.relative_to(ROOT)}")
    print(f"[luo] wrote {args.html.relative_to(ROOT)}")
    print(f"[luo] wrote {args.preview_html.relative_to(ROOT)}")
    preview = report.get("preview", {})
    if preview.get("ok"):
        print(f"[luo] wrote {args.pdf.relative_to(ROOT)}")
        print(f"[luo] wrote {args.png.relative_to(ROOT)}")
    else:
        print(f"[luo] preview skipped: {preview.get('reason', 'unknown reason')}")


if __name__ == "__main__":
    main()
