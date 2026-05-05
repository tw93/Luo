"""
Download the source font into ./source/.

The source font is published under SIL OFL 1.1:
    https://github.com/lxgw/LxgwWenKai-Screen/releases

Run:
    python scripts/fetch_base_font.py
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "source"
TARGET = SOURCE_DIR / "LXGWWenKaiScreen-Regular.ttf"
VERSION = "v1.522"
EXPECTED_SHA256 = "cd1a6fa39c4ea42fd8f4e289945789b0e510cf7016435640f8893cdad9b220f3"

# Pin a known-good release. Bump as upstream publishes new builds.
URL = (
    "https://github.com/lxgw/LxgwWenKai-Screen/releases/download/"
    f"{VERSION}/LXGWWenKaiScreen.ttf"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    if TARGET.exists():
        digest = sha256(TARGET)
        if digest == EXPECTED_SHA256:
            print(f"[luo] already present: {TARGET}")
            print(f"[luo] verified {VERSION} sha256: {digest}")
            return
        print(f"[luo] existing source checksum differs from pinned {VERSION}:")
        print(f"[luo]   found:    {digest}")
        print(f"[luo]   expected: {EXPECTED_SHA256}")
        print("[luo] downloading pinned source font")

    print(f"[luo] downloading {URL}")
    tmp = TARGET.with_suffix(".tmp")
    try:
        with urllib.request.urlopen(URL) as resp, tmp.open("wb") as f:
            f.write(resp.read())
    except Exception as e:
        tmp.unlink(missing_ok=True)
        sys.exit(
            f"[luo] download failed: {e}\n"
            f"       Manually download the source font from\n"
            f"       https://github.com/lxgw/LxgwWenKai-Screen/releases\n"
            f"       and save it as: {TARGET}"
        )
    digest = sha256(tmp)
    if digest != EXPECTED_SHA256:
        tmp.unlink(missing_ok=True)
        sys.exit(
            "[luo] downloaded source checksum mismatch:\n"
            f"       expected: {EXPECTED_SHA256}\n"
            f"       found:    {digest}"
        )
    tmp.replace(TARGET)
    size_mb = TARGET.stat().st_size / 1024 / 1024
    print(f"[luo] saved {TARGET} ({size_mb:.1f} MB)")
    print(f"[luo] verified {VERSION} sha256: {digest}")


if __name__ == "__main__":
    main()
