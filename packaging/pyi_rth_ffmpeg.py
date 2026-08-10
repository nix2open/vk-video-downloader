"""PyInstaller runtime hook — ensure bundled ffmpeg is preferred."""

import os
import sys
from pathlib import Path


def _bootstrap() -> None:
    if not getattr(sys, "frozen", False):
        return
    meipass = Path(getattr(sys, "_MEIPASS", ""))
    candidates = [
        meipass / "ffmpeg",
        Path(sys.executable).resolve().parent / "ffmpeg",
    ]
    for folder in candidates:
        if folder.is_dir():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            break


_bootstrap()
