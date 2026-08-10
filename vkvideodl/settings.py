"""User settings persisted next to the application."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from vkvideodl.paths import app_dir


def settings_path() -> Path:
    return app_dir() / "settings.json"


def default_download_dir() -> Path:
    home = Path.home()
    for candidate in (
        home / "Downloads",
        home / "Загрузки",
        home / "Desktop",
        home / "Рабочий стол",
        app_dir() / "downloads",
    ):
        if candidate.is_dir():
            return candidate
    path = app_dir() / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_settings() -> dict[str, Any]:
    path = settings_path()
    data: dict[str, Any] = {"download_dir": str(default_download_dir())}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
    download_dir = Path(str(data.get("download_dir") or default_download_dir()))
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        download_dir = default_download_dir()
        download_dir.mkdir(parents=True, exist_ok=True)
    data["download_dir"] = str(download_dir.resolve())
    return data


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    data = load_settings()
    if "download_dir" in patch and patch["download_dir"]:
        target = Path(str(patch["download_dir"])).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        data["download_dir"] = str(target.resolve())
    settings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def get_download_dir() -> Path:
    return Path(load_settings()["download_dir"])


def choose_download_dir(initial: str | None = None) -> str | None:
    """Native folder picker (Tk)."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    selected = filedialog.askdirectory(
        parent=root,
        initialdir=initial or str(get_download_dir()),
        title="Папка для сохранения видео",
        mustexist=True,
    )
    root.destroy()
    return selected or None


def open_in_file_manager(path: str | Path) -> None:
    target = Path(path)
    if target.is_file():
        folder = target.parent
        file_path = target
    else:
        folder = target
        file_path = None
    folder.mkdir(parents=True, exist_ok=True)

    if sys.platform.startswith("win"):
        if file_path and file_path.exists():
            subprocess.Popen(["explorer", "/select,", str(file_path)])
        else:
            os.startfile(str(folder))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        if file_path and file_path.exists():
            subprocess.Popen(["open", "-R", str(file_path)])
        else:
            subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def open_default_browser(url: str) -> None:
    """Open URL with the real OS default browser (not Edge via webbrowser quirks)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes

            # ShellExecute respects the user default HTTP handler (e.g. Yandex).
            rc = ctypes.windll.shell32.ShellExecuteW(None, "open", url, None, None, 1)
            if rc > 32:
                return
        except Exception:
            pass
        subprocess.Popen(
            ["cmd", "/c", "start", "", url],
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", url])
        return
    subprocess.Popen(["xdg-open", url])
