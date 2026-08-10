#!/usr/bin/env python3
"""Download a portable ffmpeg build into ./ffmpeg for bundling."""

from __future__ import annotations

import argparse
import io
import platform
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ffmpeg"

# BtbN GPL shared builds — essentials-like binaries
URLS = {
    "windows-x64": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip",
    "linux-x64": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl-shared.zip",
}


def platform_key() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "windows-x64"
    if system == "linux":
        return "linux-x64"
    if system == "darwin":
        return "macos"
    return system


def find_ffmpeg(root: Path) -> Path | None:
    for name in ("ffmpeg.exe", "ffmpeg"):
        matches = list(root.rglob(name))
        if matches:
            return matches[0]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", default=platform_key())
    args = parser.parse_args()

    if args.platform == "macos":
        # Prefer brew binary copy when available
        brew = shutil.which("ffmpeg")
        if not brew:
            print("On macOS install ffmpeg (brew install ffmpeg) or pass a windows/linux CI build.")
            return 1
        OUT.mkdir(parents=True, exist_ok=True)
        target = OUT / "ffmpeg"
        shutil.copy2(brew, target)
        print(f"Copied {brew} -> {target}")
        return 0

    url = URLS.get(args.platform)
    if not url:
        print(f"Unsupported platform: {args.platform}", file=sys.stderr)
        return 1

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    print(f"Downloading {url}")
    with urlopen(url, timeout=180) as resp:
        data = resp.read()

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(OUT)

    binary = find_ffmpeg(OUT)
    if not binary:
        print("ffmpeg binary not found in archive", file=sys.stderr)
        return 1

    # Flatten: put binary (+ sibling dll/so) into ffmpeg/
    flat = OUT / "_flat"
    flat.mkdir(exist_ok=True)
    bin_dir = binary.parent
    for item in bin_dir.iterdir():
        shutil.copy2(item, flat / item.name)

    for child in list(OUT.iterdir()):
        if child.name != "_flat":
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

    for item in flat.iterdir():
        item.rename(OUT / item.name)
    flat.rmdir()

    print(f"ffmpeg ready at {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
