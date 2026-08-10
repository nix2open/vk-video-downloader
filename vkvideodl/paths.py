"""Path helpers for development and frozen (PyInstaller) builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def app_dir() -> Path:
    """Directory with VERSION, config, and writable data next to the executable."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Bundled read-only resources (static, ffmpeg, config)."""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def static_dir() -> Path:
    bundled = resource_dir() / "static"
    if bundled.is_dir():
        return bundled
    return app_dir() / "static"


def downloads_dir() -> Path:
    path = app_dir() / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def updates_dir() -> Path:
    path = app_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def version_file() -> Path:
    for candidate in (app_dir() / "VERSION", resource_dir() / "VERSION"):
        if candidate.is_file():
            return candidate
    return app_dir() / "VERSION"


def read_version() -> str:
    path = version_file()
    if path.is_file():
        return path.read_text(encoding="utf-8").strip() or "0.0.0"
    return "0.0.0"


def ffmpeg_binary() -> str | None:
    """Return path to bundled or system ffmpeg."""
    names = ("ffmpeg.exe", "ffmpeg")
    search_roots = [
        app_dir() / "ffmpeg",
        resource_dir() / "ffmpeg",
        app_dir() / "bin",
        resource_dir() / "bin",
    ]
    for root in search_roots:
        for name in names:
            candidate = root / name
            if candidate.is_file():
                return str(candidate)
    # Also allow PATH
    from shutil import which

    return which("ffmpeg")


def ensure_ffmpeg_on_path() -> None:
    binary = ffmpeg_binary()
    if not binary:
        return
    bin_dir = str(Path(binary).parent)
    path = os.environ.get("PATH", "")
    if bin_dir not in path.split(os.pathsep):
        os.environ["PATH"] = bin_dir + os.pathsep + path
