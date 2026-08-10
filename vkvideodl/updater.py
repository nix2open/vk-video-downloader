"""GitHub Releases based auto-updater."""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from vkvideodl.paths import app_dir, is_frozen, read_version, resource_dir, updates_dir

ProgressCb = Callable[[dict[str, Any]], None]


def load_config() -> dict[str, Any]:
    for candidate in (
        resource_dir() / "vkvideodl" / "config.json",
        resource_dir() / "config.json",
        Path(__file__).with_name("config.json"),
    ):
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return {
        "name": "VK Video Downloader",
        "github_repo": "nix2open/vk-video-downloader",
        "github_api": "https://api.github.com",
        "default_port": 8787,
        "update_asset_prefix": "VKVideoDownloader",
    }


def parse_version(value: str) -> tuple[int, ...]:
    value = value.strip().lstrip("vV")
    parts = re.findall(r"\d+", value)
    return tuple(int(p) for p in parts) if parts else (0,)


def platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        return "windows-x64"
    if system == "darwin":
        return "macos-arm64" if machine in {"arm64", "aarch64"} else "macos-x64"
    return "linux-x64"


def _api_get(url: str) -> Any:
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "VKVideoDownloader-Updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_for_updates() -> dict[str, Any]:
    cfg = load_config()
    repo = cfg["github_repo"]
    api = cfg.get("github_api", "https://api.github.com").rstrip("/")
    current = read_version()
    result: dict[str, Any] = {
        "current_version": current,
        "latest_version": current,
        "update_available": False,
        "release_url": None,
        "asset_name": None,
        "asset_url": None,
        "asset_size": None,
        "notes": None,
        "platform": platform_tag(),
        "frozen": is_frozen(),
        "can_auto_update": is_frozen(),
    }
    try:
        release = _api_get(f"{api}/repos/{repo}/releases/latest")
    except HTTPError as exc:
        if exc.code == 404:
            result["message"] = "Релизы ещё не опубликованы."
            return result
        raise RuntimeError(f"GitHub API error: HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Нет связи с GitHub: {exc.reason}") from exc

    tag = (release.get("tag_name") or "").strip()
    latest = tag.lstrip("vV") or current
    result["latest_version"] = latest
    result["release_url"] = release.get("html_url")
    result["notes"] = release.get("body") or ""
    result["update_available"] = parse_version(latest) > parse_version(current)

    prefix = cfg.get("update_asset_prefix", "VKVideoDownloader")
    tag_platform = platform_tag()
    assets = release.get("assets") or []
    chosen = None
    for asset in assets:
        name = asset.get("name") or ""
        lower = name.lower()
        if not lower.endswith(".zip"):
            continue
        if prefix.lower() in lower and tag_platform in lower:
            chosen = asset
            break
    if not chosen:
        for asset in assets:
            name = (asset.get("name") or "").lower()
            if name.endswith(".zip") and tag_platform.split("-")[0] in name:
                chosen = asset
                break

    if chosen:
        result["asset_name"] = chosen.get("name")
        result["asset_url"] = chosen.get("browser_download_url")
        result["asset_size"] = chosen.get("size")

    if result["update_available"] and not result["asset_url"]:
        result["message"] = (
            f"Доступна версия {latest}, но нет сборки для {tag_platform}. "
            "Скачайте вручную со страницы релиза."
        )
    elif result["update_available"]:
        result["message"] = f"Доступна версия {latest}."
    else:
        result["message"] = "Установлена актуальная версия."

    return result


def _download_file(url: str, dest: Path, progress_cb: ProgressCb | None = None) -> None:
    req = Request(url, headers={"User-Agent": "VKVideoDownloader-Updater"})
    with urlopen(req, timeout=120) as resp, dest.open("wb") as out:
        total = resp.headers.get("Content-Length")
        total_bytes = int(total) if total and total.isdigit() else None
        downloaded = 0
        chunk = 1024 * 256
        while True:
            data = resp.read(chunk)
            if not data:
                break
            out.write(data)
            downloaded += len(data)
            if progress_cb:
                percent = 0.0
                if total_bytes:
                    percent = downloaded * 100.0 / total_bytes
                progress_cb(
                    {
                        "status": "downloading",
                        "percent": round(percent, 1),
                        "downloaded_bytes": downloaded,
                        "total_bytes": total_bytes,
                        "message": "Скачивание обновления…",
                    }
                )


def _write_windows_updater(install_dir: Path, staging: Path, exe_name: str) -> Path:
    script = updates_dir() / "apply_update.bat"
    # Escape for batch
    install = str(install_dir)
    stage = str(staging)
    lines = [
        "@echo off",
        "setlocal",
        "echo Applying VK Video Downloader update...",
        "timeout /t 2 /nobreak >nul",
        f'xcopy /E /Y /I "{stage}\\*" "{install}\\"',
        f'cd /d "{install}"',
        f'start "" "{install}\\{exe_name}"',
        f'rmdir /S /Q "{stage}"',
        "endlocal",
        "del \"%~f0\"",
    ]
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return script


def _write_unix_updater(install_dir: Path, staging: Path, exe_name: str) -> Path:
    script = updates_dir() / "apply_update.sh"
    content = f"""#!/bin/bash
set -e
sleep 2
rsync -a --delete "{staging}/" "{install_dir}/" 2>/dev/null || cp -R "{staging}/." "{install_dir}/"
cd "{install_dir}"
if [ -x "./{exe_name}" ]; then
  nohup "./{exe_name}" >/dev/null 2>&1 &
elif [ -x "./launcher" ]; then
  nohup "./launcher" >/dev/null 2>&1 &
fi
rm -rf "{staging}"
rm -f "$0"
"""
    script.write_text(content, encoding="utf-8")
    script.chmod(0o755)
    return script


def apply_downloaded_update(zip_path: Path, progress_cb: ProgressCb | None = None) -> dict[str, Any]:
    if not is_frozen():
        raise RuntimeError(
            "Автообновление доступно только в собранном приложении. "
            "В режиме разработки обновите код через git pull."
        )

    install_dir = app_dir()
    staging = updates_dir() / "staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    if progress_cb:
        progress_cb({"status": "processing", "percent": 90, "message": "Распаковка…"})

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(staging)

    # If zip contains a single root folder, use its contents
    children = [p for p in staging.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        inner = children[0]
        tmp = updates_dir() / "staging_flat"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        inner.rename(tmp)
        shutil.rmtree(staging, ignore_errors=True)
        tmp.rename(staging)

    exe_name = Path(sys.executable).name
    if platform.system() == "Windows":
        script = _write_windows_updater(install_dir, staging, exe_name)
        subprocess.Popen(["cmd", "/c", str(script)], close_fds=True)
    else:
        script = _write_unix_updater(install_dir, staging, exe_name)
        subprocess.Popen(["/bin/bash", str(script)], close_fds=True, start_new_session=True)

    if progress_cb:
        progress_cb(
            {
                "status": "done",
                "percent": 100,
                "message": "Обновление установлено. Приложение перезапускается…",
            }
        )

    return {"ok": True, "restarting": True, "script": str(script)}


def download_and_apply_update(
    asset_url: str,
    asset_name: str | None = None,
    progress_cb: ProgressCb | None = None,
) -> dict[str, Any]:
    updates_dir().mkdir(parents=True, exist_ok=True)
    name = asset_name or "update.zip"
    dest = updates_dir() / name
    if progress_cb:
        progress_cb({"status": "downloading", "percent": 0, "message": "Скачивание обновления…"})
    _download_file(asset_url, dest, progress_cb=progress_cb)
    return apply_downloaded_update(dest, progress_cb=progress_cb)


def open_release_page(url: str | None) -> None:
    if not url:
        return
    import webbrowser

    webbrowser.open(url)
