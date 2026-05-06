"""Group-level Luo↔LXGW similarity audit.

The public ``compare_to.py`` report stays at the 30-glyph anchor set used by
CI and the README badge. This script answers a different question: when we
look at *every* glyph the user sees on the homepage / proof page, how does
similarity to LXGW WenKai split across the existing pass-specific
whitelists?

We bucket each char by membership in:

    frame    -> IDENTITY_FRAME_CHARS
    walk     -> WALK_FINAL_CHARS / STRAIGHTEN_SKIP_CHARS walk subset
    heart    -> HEART_CHARS
    stack    -> KAI_BALANCE_STACK_CHARS
    roof     -> KAI_BALANCE_ROOF_CHARS
    water    -> KAI_BALANCE_WATER_CHARS
    speech   -> KAI_BALANCE_SPEECH_CHARS
    side     -> KAI_BALANCE_SIDE_SPLIT_CHARS
    core_v2  -> IDENTITY_CORE_V2_CHARS
    hook     -> HOOK_FINAL_CHARS
    turn     -> TURN_FINAL_CHARS
    generic  -> none of the above

Each bucket's average raster IoU + bbox-centered IoU + count is printed and
written to ``local/ref/metrics/site_grouped_iou.json``. Run before/after a
new topology pass to verify the generic bucket dropped without breaking the
specials.

Run:
    .venv/bin/python scripts/measure_groups.py
    .venv/bin/python scripts/measure_groups.py --chars-file proof/page_chars.txt
    .venv/bin/python scripts/measure_groups.py --baseline /tmp/luo_baseline_v046.ttf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from fontTools.ttLib import TTFont  # noqa: E402

import build  # noqa: E402  -- shares whitelist constants with the build pipeline
from compare_to import render_glyph, iou, center_mask  # noqa: E402


SOURCE_FONT = ROOT / "source" / "LXGWWenKaiScreen-Regular.ttf"
LUO_FONT = ROOT / "dist" / "Luo-Regular.ttf"
DEFAULT_CHARS_FILE = ROOT / "proof" / "page_chars.txt"
DEFAULT_OUTPUT = ROOT / "local" / "ref" / "metrics" / "site_grouped_iou.json"


def load_chars(path: Path) -> list[str]:
    text = path.read_text("utf-8")
    seen: list[str] = []
    seen_set: set[str] = set()
    for ch in text:
        if 0x3400 <= ord(ch) <= 0x9FFF and ch not in seen_set:
            seen.append(ch)
            seen_set.add(ch)
    return seen


def build_buckets() -> dict[str, set[str]]:
    """Per-char bucket assignment. Each char goes to AT MOST one bucket.

    Priority order roughly follows "more specialised passes first" so a char
    that belongs to multiple whitelists shows up in the bucket whose pass
    actually dominates its final geometry. Generic catches everything else.
    """
    walk_chars = set(build.WALK_FINAL_CHARS)
    walk_skip = set(c for c in build.STRAIGHTEN_SKIP_CHARS if c in walk_chars)
    heart_skip = set(c for c in build.STRAIGHTEN_SKIP_CHARS if c in build.HEART_CHARS)

    return {
        "frame": set(build.IDENTITY_FRAME_CHARS),
        "walk": walk_chars | walk_skip,
        "heart": set(build.HEART_CHARS) | heart_skip,
        "stack": set(build.KAI_BALANCE_STACK_CHARS),
        "roof": set(build.KAI_BALANCE_ROOF_CHARS),
        "water": set(build.KAI_BALANCE_WATER_CHARS),
        "speech": set(build.KAI_BALANCE_SPEECH_CHARS),
        "side": set(build.KAI_BALANCE_SIDE_SPLIT_CHARS),
        "core_v2": set(build.IDENTITY_CORE_V2_CHARS),
        "hook": set(build.HOOK_FINAL_CHARS),
        "turn": set(build.TURN_FINAL_CHARS),
    }


BUCKET_ORDER = (
    "frame", "walk", "heart", "stack", "roof",
    "water", "speech", "side", "core_v2", "hook", "turn",
    "generic",
)


def assign_bucket(ch: str, buckets: dict[str, set[str]]) -> str:
    for name in BUCKET_ORDER[:-1]:
        if ch in buckets[name]:
            return name
    return "generic"


def measure(luo_path: Path, src_path: Path, chars: list[str], raster: int) -> dict:
    luo = TTFont(str(luo_path))
    src = TTFont(str(src_path))
    buckets = build_buckets()
    rows: list[dict] = []
    errors = 0
    for ch in chars:
        try:
            r = render_glyph(src, ch, raster)
            l = render_glyph(luo, ch, raster)
        except Exception:
            errors += 1
            continue
        if r is None or l is None:
            continue
        raw = iou(r.mask, l.mask)
        rc = center_mask(r.mask, r.bbox, raster)
        lc = center_mask(l.mask, l.bbox, raster)
        ctr = iou(rc, lc)
        rows.append({
            "char": ch,
            "cp": f"U+{ord(ch):04X}",
            "raw": round(raw, 4),
            "ctr": round(ctr, 4),
            "bucket": assign_bucket(ch, buckets),
        })
    return {"errors": errors, "rows": rows}


def summarise(rows: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for name in BUCKET_ORDER:
        bucket_rows = [r for r in rows if r["bucket"] == name]
        if not bucket_rows:
            out[name] = {"count": 0, "avg_raw": None, "avg_ctr": None}
            continue
        avg_raw = sum(r["raw"] for r in bucket_rows) / len(bucket_rows)
        avg_ctr = sum(r["ctr"] for r in bucket_rows) / len(bucket_rows)
        out[name] = {
            "count": len(bucket_rows),
            "avg_raw": round(avg_raw, 4),
            "avg_ctr": round(avg_ctr, 4),
        }
    overall = {
        "count": len(rows),
        "avg_raw": round(sum(r["raw"] for r in rows) / len(rows), 4) if rows else None,
        "avg_ctr": round(sum(r["ctr"] for r in rows) / len(rows), 4) if rows else None,
    }
    return {"per_bucket": out, "overall": overall}


def print_table(label: str, summary: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"{'bucket':<10} {'count':>5} {'avg_raw':>9} {'avg_ctr':>9}")
    print("-" * 36)
    for name in BUCKET_ORDER:
        b = summary["per_bucket"][name]
        if b["count"] == 0:
            print(f"{name:<10} {0:>5}        --        --")
            continue
        print(f"{name:<10} {b['count']:>5} {b['avg_raw']:>9.4f} {b['avg_ctr']:>9.4f}")
    o = summary["overall"]
    print("-" * 36)
    print(f"{'OVERALL':<10} {o['count']:>5} {o['avg_raw']:>9.4f} {o['avg_ctr']:>9.4f}")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--luo", type=Path, default=LUO_FONT)
    ap.add_argument("--source", type=Path, default=SOURCE_FONT)
    ap.add_argument("--baseline", type=Path, default=None,
                    help="Optional second Luo font (e.g. before-pass snapshot) for diff.")
    ap.add_argument("--chars-file", type=Path, default=DEFAULT_CHARS_FILE)
    ap.add_argument("--raster-size", type=int, default=256)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--anchor-only", action="store_true",
                    help="Use the 30-char anchor set instead of the full chars file.")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    if args.anchor_only:
        chars = list("落文字书心清骨风纸印国回月雨霜藏魔赢道远家亭序集章兰永天玄黄")
    else:
        chars = load_chars(args.chars_file)

    print(f"[measure-groups] {len(chars)} chars from "
          f"{'(anchor)' if args.anchor_only else args.chars_file.relative_to(ROOT)} "
          f"@ {args.raster_size}px")

    main_meas = measure(args.luo, args.source, chars, args.raster_size)
    main_sum = summarise(main_meas["rows"])
    print_table(f"Luo {args.luo.name} vs LXGW", main_sum)

    payload = {
        "luo": str(args.luo.relative_to(ROOT)) if args.luo.is_relative_to(ROOT) else str(args.luo),
        "source": str(args.source.relative_to(ROOT)) if args.source.is_relative_to(ROOT) else str(args.source),
        "raster": args.raster_size,
        "chars_total": len(chars),
        "errors": main_meas["errors"],
        "summary": main_sum,
        "rows": main_meas["rows"],
    }

    if args.baseline is not None:
        base_meas = measure(args.baseline, args.source, chars, args.raster_size)
        base_sum = summarise(base_meas["rows"])
        print_table(f"baseline {args.baseline.name} vs LXGW", base_sum)
        print("\n=== diff (current - baseline) ===")
        print(f"{'bucket':<10} {'Δ_raw':>9} {'Δ_ctr':>9}")
        print("-" * 30)
        for name in BUCKET_ORDER:
            b = base_sum["per_bucket"][name]
            m = main_sum["per_bucket"][name]
            if b["avg_raw"] is None or m["avg_raw"] is None:
                continue
            d_raw = m["avg_raw"] - b["avg_raw"]
            d_ctr = m["avg_ctr"] - b["avg_ctr"]
            arrow = " ↓" if d_raw < -0.001 else (" ↑" if d_raw > 0.001 else "  ")
            print(f"{name:<10} {d_raw:+9.4f} {d_ctr:+9.4f}{arrow}")
        d_raw = main_sum["overall"]["avg_raw"] - base_sum["overall"]["avg_raw"]
        d_ctr = main_sum["overall"]["avg_ctr"] - base_sum["overall"]["avg_ctr"]
        print("-" * 30)
        print(f"{'OVERALL':<10} {d_raw:+9.4f} {d_ctr:+9.4f}")
        payload["baseline_summary"] = base_sum
        payload["diff"] = {"raw": round(d_raw, 4), "ctr": round(d_ctr, 4)}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n[measure-groups] wrote {args.output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
