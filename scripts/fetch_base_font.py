"""
Download the source font into ./source/.

The source font is published under SIL OFL 1.1:
    https://github.com/lxgw/LxgwWenKai-Screen/releases

Run:
    python scripts/fetch_base_font.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "source"
TARGET = SOURCE_DIR / "LXGWWenKaiScreen-Regular.ttf"

# Pin a known-good release. Bump as upstream publishes new builds.
URL = (
    "https://github.com/lxgw/LxgwWenKai-Screen/releases/download/"
    "v1.501/LXGWWenKaiScreen.ttf"
)


def main() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    if TARGET.exists():
        print(f"[luo] already present: {TARGET}")
        return
    print(f"[luo] downloading {URL}")
    try:
        with urllib.request.urlopen(URL) as resp, open(TARGET, "wb") as f:
            f.write(resp.read())
    except Exception as e:
        sys.exit(
            f"[luo] download failed: {e}\n"
            f"       Manually download the source font from\n"
            f"       https://github.com/lxgw/LxgwWenKai-Screen/releases\n"
            f"       and save it as: {TARGET}"
        )
    size_mb = TARGET.stat().st_size / 1024 / 1024
    print(f"[luo] saved {TARGET} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
