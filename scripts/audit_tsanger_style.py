"""Six-dimension style audit: Luo vs the private typographic-kai reference.

Raster IoU saturated as a progress metric for the v0.4 print-kai pivot: the
30-anchor Luo↔W04 IoU sits inside its target band while the eye still reads
Luo as "not the reference gesture". The gap lives in dimensions IoU barely
sees: vertical posture, overall ink density, and H/V stroke contrast. This
script measures those directly, per glyph, across every homepage char.

Per glyph we render Luo, the private reference (LUO_PRIVATE_KAI_REF) and the
LXGW source at the same em size on a shared baseline, binarise, and compute:

    bot   bottom ink edge above baseline (em; negative = descends below)
    cy    ink centroid height above baseline (em)
    bh/bw ink bbox height / width (em)
    dens  ink density inside the bbox (ink pixels / bbox pixels)
    hv    H/V stroke contrast: median horizontal-stroke thickness divided by
          median vertical-stroke width (run-length method, runs < 0.22em)

The queue entry for each char carries the Luo-minus-reference deltas plus a
composite score (|delta| / population sd, weighted toward the three gap
dimensions). All outputs are aggregate scalars; no outline data from the
private reference is ever written.

Optional second reference via LUO_PRIVATE_KAI_REF_W05 marks glyphs whose ink
density exceeds the heavier weight's ceiling (`over_w05`).

Reports are private-reference products and must stay under local/ref/.

Run:
    LUO_PRIVATE_KAI_REF=/path/to/ref.ttf .venv/bin/python scripts/audit_tsanger_style.py
    ... audit_tsanger_style.py --baseline local/ref/baselines/v0411.ttf
    ... audit_tsanger_style.py --chars 落文书 --top 40
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FONT = ROOT / "source" / "LXGWWenKaiScreen-Regular.ttf"
LUO_FONT = ROOT / "dist" / "Luo-Regular.ttf"
INDEX_HTML = ROOT / "index.html"
LOCAL_REF_DIR = ROOT / "local" / "ref"
DEFAULT_OUTPUT = LOCAL_REF_DIR / "metrics" / "tsanger_style_audit.json"

PRIVATE_REF = os.environ.get("LUO_PRIVATE_KAI_REF")
PRIVATE_REF_W05 = os.environ.get("LUO_PRIVATE_KAI_REF_W05")

EM = 300
# Canvas geometry (px, at EM=300): baseline sits low enough that CJK
# descenders (~ -0.16em) stay inside the raster.
CANVAS_W_RATIO = 1.4
CANVAS_H_RATIO = 1.5
BASELINE_RATIO = 1.1  # baseline y from canvas top, in em
LEFT_RATIO = 0.2

# Stroke runs longer than this fraction of the em are treated as "along the
# stroke" rather than "across the stroke" and excluded from thickness stats.
STROKE_RUN_MAX_EM = 0.22
# Below this many run samples the H/V contrast is statistically meaningless
# (single-stem or no-stem chars like 一/乙); flag instead of trusting it.
HV_MIN_SAMPLES = 40

# Composite score weights: the three measured gap dimensions dominate.
SCORE_WEIGHTS = {
    "d_bot": 1.0,
    "d_cy": 1.0,
    "d_dens": 1.0,
    "d_hv": 1.0,
    "d_bh": 0.5,
    "d_bw": 0.5,
}
SD_FLOOR = 1e-4

METRIC_KEYS = ("bot", "cy", "bh", "bw", "dens", "hv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Per-glyph style-vector audit vs the private kai reference."
    )
    parser.add_argument("--luo", type=Path, default=LUO_FONT)
    parser.add_argument("--lxgw", type=Path, default=SOURCE_FONT)
    parser.add_argument(
        "--private",
        type=Path,
        default=Path(PRIVATE_REF) if PRIVATE_REF else None,
        help="Private reference font. Defaults to LUO_PRIVATE_KAI_REF.",
    )
    parser.add_argument(
        "--w05",
        type=Path,
        default=Path(PRIVATE_REF_W05) if PRIVATE_REF_W05 else None,
        help="Heavier private weight for the over_w05 ceiling check "
        "(LUO_PRIVATE_KAI_REF_W05). Optional.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Older Luo build to diff against (per-char score delta).",
    )
    parser.add_argument(
        "--chars",
        type=str,
        default=None,
        help="Explicit char string. Default: every CJK char in index.html.",
    )
    parser.add_argument("--chars-file", type=Path, default=None)
    parser.add_argument("--em", type=int, default=EM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top", type=int, default=20, help="Rows to print.")
    return parser.parse_args()


def load_index_chars() -> list[str]:
    text = INDEX_HTML.read_text("utf-8")
    seen: list[str] = []
    seen_set: set[str] = set()
    for ch in re.findall(r"[㐀-鿿]", text):
        if ch not in seen_set:
            seen.append(ch)
            seen_set.add(ch)
    return seen


def ensure_private_output(path: Path) -> None:
    try:
        path.resolve().relative_to(LOCAL_REF_DIR.resolve())
    except ValueError:
        sys.exit("[audit] private-reference reports must stay under local/ref/")


class GlyphRasteriser:
    def __init__(self, font_path: Path, em: int) -> None:
        from PIL import ImageFont

        self.em = em
        self.font = ImageFont.truetype(str(font_path), em)
        self.canvas_w = int(em * CANVAS_W_RATIO)
        self.canvas_h = int(em * CANVAS_H_RATIO)
        self.baseline_y = int(em * BASELINE_RATIO)
        self.left_x = int(em * LEFT_RATIO)
        from fontTools.ttLib import TTFont

        tf = TTFont(str(font_path), lazy=True)
        self.cmap = tf.getBestCmap() or {}
        tf.close()

    def render(self, char: str):
        """Binary numpy array (rows, cols), or None if the char is missing."""
        import numpy as np
        from PIL import Image, ImageDraw

        if ord(char) not in self.cmap:
            return None
        img = Image.new("L", (self.canvas_w, self.canvas_h), 0)
        ImageDraw.Draw(img).text(
            (self.left_x, self.baseline_y),
            char,
            font=self.font,
            fill=255,
            anchor="ls",
        )
        arr = np.asarray(img) > 127
        if not arr.any():
            return None
        return arr


def _run_lengths(mask, axis: int, max_len: int):
    """Ink run lengths along `axis` (0 = vertical runs, 1 = horizontal),
    keeping only runs shorter than max_len px."""
    import numpy as np

    a = mask if axis == 0 else mask.T
    # Pad each column with zeros so run boundaries are explicit.
    padded = np.zeros((a.shape[0] + 2, a.shape[1]), dtype=bool)
    padded[1:-1, :] = a
    flat = padded.T.reshape(-1)  # column-major walk keeps runs within columns
    diff = np.diff(flat.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)
    lengths = ends - starts
    return lengths[lengths < max_len]


def measure(mask, em: int, baseline_y: int) -> dict | None:
    import numpy as np

    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        return None
    top_px, bot_px = rows[0], rows[-1]
    left_px, right_px = cols[0], cols[-1]
    bh_px = bot_px - top_px + 1
    bw_px = right_px - left_px + 1
    ink = int(mask.sum())

    ys, _ = np.nonzero(mask)
    cy = (baseline_y - ys.mean()) / em

    max_run = int(STROKE_RUN_MAX_EM * em)
    v_runs = _run_lengths(mask, axis=0, max_len=max_run)  # cross horizontals
    h_runs = _run_lengths(mask, axis=1, max_len=max_run)  # cross verticals
    hv = None
    hv_reliable = v_runs.size >= HV_MIN_SAMPLES and h_runs.size >= HV_MIN_SAMPLES
    if hv_reliable:
        h_thick = float(np.median(v_runs))
        v_width = float(np.median(h_runs))
        if v_width > 0:
            hv = h_thick / v_width
    if hv is None:
        hv_reliable = False

    return {
        "bot": (baseline_y - bot_px) / em,
        "top": (baseline_y - top_px) / em,
        "cy": cy,
        "bh": bh_px / em,
        "bw": bw_px / em,
        "dens": ink / float(bh_px * bw_px),
        "hv": hv,
        "hv_reliable": hv_reliable,
    }


def measure_font(font_path: Path, chars: list[str], em: int) -> dict[str, dict]:
    r = GlyphRasteriser(font_path, em)
    out: dict[str, dict] = {}
    for ch in chars:
        mask = r.render(ch)
        if mask is None:
            continue
        m = measure(mask, em, r.baseline_y)
        if m is not None:
            out[ch] = m
    return out


def population_mean(metrics: dict[str, dict], key: str) -> float | None:
    vals = [m[key] for m in metrics.values() if m.get(key) is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def build_queue(
    luo: dict[str, dict],
    ref: dict[str, dict],
    w05: dict[str, dict] | None,
) -> tuple[list[dict], dict]:
    import numpy as np

    common = [ch for ch in luo if ch in ref]
    deltas_by_key: dict[str, list[float]] = {f"d_{k}": [] for k in METRIC_KEYS}
    rows: list[dict] = []
    for ch in common:
        lm, rm = luo[ch], ref[ch]
        d: dict[str, float | None] = {}
        for k in METRIC_KEYS:
            if lm.get(k) is None or rm.get(k) is None:
                d[f"d_{k}"] = None
                continue
            if k == "hv" and not (lm["hv_reliable"] and rm["hv_reliable"]):
                d["d_hv"] = None
                continue
            val = lm[k] - rm[k]
            d[f"d_{k}"] = val
            deltas_by_key[f"d_{k}"].append(val)
        over = None
        if w05 is not None and ch in w05:
            over = bool(lm["dens"] > w05[ch]["dens"])
        rows.append({"char": ch, "deltas": d, "over_w05": over, "luo": lm, "ref": rm})

    sds = {
        key: max(float(np.std(vals)), SD_FLOOR) if vals else None
        for key, vals in deltas_by_key.items()
    }
    for row in rows:
        score = 0.0
        for key, weight in SCORE_WEIGHTS.items():
            val = row["deltas"].get(key)
            if val is None or sds.get(key) is None:
                continue
            score += weight * abs(val) / sds[key]
        if row["over_w05"]:
            score += 1.0
        row["score"] = round(score, 3)
    rows.sort(key=lambda r: r["score"], reverse=True)

    stats = {
        "char_count": len(rows),
        "mean_deltas": {
            key: round(sum(vals) / len(vals), 4) if vals else None
            for key, vals in deltas_by_key.items()
        },
        "delta_sd": {k: round(v, 4) if v else None for k, v in sds.items()},
        "over_w05_ratio": (
            round(
                sum(1 for r in rows if r["over_w05"]) / len(rows), 3
            )
            if w05 is not None and rows
            else None
        ),
    }
    return rows, stats


def _round_metrics(m: dict) -> dict:
    out = {}
    for k, v in m.items():
        out[k] = round(v, 4) if isinstance(v, float) else v
    return out


def main() -> None:
    args = parse_args()
    if args.private is None:
        sys.exit("[audit] set LUO_PRIVATE_KAI_REF to the private reference font")
    if not args.private.exists():
        sys.exit(f"[audit] private reference font missing: {args.private}")
    if not args.luo.exists():
        sys.exit(f"[audit] Luo font missing: {args.luo} (run scripts/build.py)")
    ensure_private_output(args.out)

    if args.chars:
        chars = list(dict.fromkeys(args.chars))
    elif args.chars_file:
        chars = list(dict.fromkeys(re.findall(r"[㐀-鿿]", args.chars_file.read_text("utf-8"))))
    else:
        chars = load_index_chars()

    em = args.em
    luo = measure_font(args.luo, chars, em)
    ref = measure_font(args.private, chars, em)
    lxgw = measure_font(args.lxgw, chars, em) if args.lxgw.exists() else {}
    w05 = measure_font(args.w05, chars, em) if args.w05 and args.w05.exists() else None

    queue, stats = build_queue(luo, ref, w05)

    lxgw_means = {
        k: round(population_mean(lxgw, k), 4) if lxgw and population_mean(lxgw, k) is not None else None
        for k in METRIC_KEYS
    }
    payload = {
        "version": 1,
        "em": em,
        "luo": str(args.luo.name),
        "reference": "private",  # never write the private font path
        "population_stats": {
            **stats,
            "luo_means": {k: round(population_mean(luo, k), 4) for k in METRIC_KEYS if population_mean(luo, k) is not None},
            "ref_means": {k: round(population_mean(ref, k), 4) for k in METRIC_KEYS if population_mean(ref, k) is not None},
            "lxgw_means": lxgw_means,
        },
        "queue": [
            {
                "char": r["char"],
                "score": r["score"],
                "over_w05": r["over_w05"],
                "deltas": _round_metrics(r["deltas"]),
                "luo": _round_metrics({k: r["luo"][k] for k in METRIC_KEYS if r["luo"].get(k) is not None}),
                "ref": _round_metrics({k: r["ref"][k] for k in METRIC_KEYS if r["ref"].get(k) is not None}),
            }
            for r in queue
        ],
    }

    if args.baseline:
        if not args.baseline.exists():
            sys.exit(f"[audit] baseline font missing: {args.baseline}")
        base = measure_font(args.baseline, chars, em)
        base_queue, base_stats = build_queue(base, ref, w05)
        base_scores = {r["char"]: r["score"] for r in base_queue}
        payload["baseline"] = {
            "font": str(args.baseline.name),
            "population_stats_before": base_stats,
            "score_regressions": sorted(
                (
                    {
                        "char": r["char"],
                        "before": base_scores[r["char"]],
                        "after": r["score"],
                    }
                    for r in queue
                    if r["char"] in base_scores
                    and r["score"] > base_scores[r["char"]] + 0.5
                ),
                key=lambda e: e["after"] - e["before"],
                reverse=True,
            ),
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    md = stats["mean_deltas"]
    print(
        f"[audit] {stats['char_count']} glyphs | "
        f"d_bot={md['d_bot']:+.4f} d_cy={md['d_cy']:+.4f} "
        f"d_bh={md['d_bh']:+.4f} d_bw={md['d_bw']:+.4f} "
        f"d_dens={md['d_dens']:+.4f} "
        f"d_hv={md['d_hv']:+.3f}" if md.get("d_hv") is not None else "",
    )
    if stats.get("over_w05_ratio") is not None:
        print(f"[audit] over_w05 ratio: {stats['over_w05_ratio']:.1%}")
    print(f"[audit] top {args.top} queue:")
    for r in queue[: args.top]:
        d = r["deltas"]
        parts = " ".join(
            f"{k}={d[k]:+.3f}" for k in ("d_bot", "d_cy", "d_dens", "d_hv") if d.get(k) is not None
        )
        flag = " over_w05" if r["over_w05"] else ""
        print(f"  {r['char']} score={r['score']:.2f} {parts}{flag}")
    rel = args.out.resolve().relative_to(ROOT.resolve())
    print(f"[audit] wrote {rel}")
    if args.baseline and payload["baseline"]["score_regressions"]:
        regs = payload["baseline"]["score_regressions"]
        print(f"[audit] {len(regs)} score regressions vs baseline: " + "".join(e["char"] for e in regs[:20]))


if __name__ == "__main__":
    main()
