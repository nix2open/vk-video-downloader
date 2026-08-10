"""VK video analyze / download via yt-dlp."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import yt_dlp

from vkvideodl.paths import ensure_ffmpeg_on_path

VK_HOSTS = {
    "vk.com",
    "www.vk.com",
    "m.vk.com",
    "vk.ru",
    "www.vk.ru",
    "vkvideo.ru",
    "www.vkvideo.ru",
    "live.vkvideo.ru",
}

VIDEO_ID_RE = re.compile(r"(?:video|clip)(-?\d+)_(\d+)", re.IGNORECASE)

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://vkvideo.ru/",
}


def validate_vk_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in VK_HOSTS:
        raise ValueError("Поддерживаются только ссылки VK / VK Video (vk.com, vkvideo.ru).")
    if not VIDEO_ID_RE.search(url):
        raise ValueError(
            "Не удалось распознать ID видео в ссылке. Пример: https://vkvideo.ru/video-123_456"
        )
    return url


def format_bytes(num: int | float | None) -> str | None:
    if num is None:
        return None
    num = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024:
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} TB"


def format_eta(seconds: float | int | None) -> str | None:
    if seconds is None:
        return None
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    if seconds < 60:
        return f"~{seconds} с"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"~{minutes} м {sec:02d} с"
    hours, minutes = divmod(minutes, 60)
    return f"~{hours} ч {minutes:02d} м"


def format_speed(bps: float | int | None) -> str | None:
    if not bps:
        return None
    return f"{format_bytes(bps)}/s"


def safe_filename(title: str, video_id: str) -> str:
    cleaned = re.sub(r"[^\w\s\-.\u0400-\u04FF]", "", title or "", flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = f"vk_{video_id}"
    return cleaned[:120]


def _is_video_format(fmt: dict[str, Any]) -> bool:
    vcodec = fmt.get("vcodec")
    return bool(vcodec and vcodec != "none")


def _is_audio_format(fmt: dict[str, Any]) -> bool:
    acodec = fmt.get("acodec")
    return bool(acodec and acodec != "none")


def _is_progressive(fmt: dict[str, Any]) -> bool:
    return _is_video_format(fmt) and _is_audio_format(fmt)


def build_quality_options(info: dict[str, Any]) -> list[dict[str, Any]]:
    formats = info.get("formats") or []
    by_height: dict[int, list[dict[str, Any]]] = {}
    for fmt in formats:
        if not _is_video_format(fmt):
            continue
        height = fmt.get("height")
        if not height:
            note = (fmt.get("format_note") or "").lower()
            match = re.search(r"(\d+)p", note)
            if match:
                height = int(match.group(1))
            else:
                continue
        by_height.setdefault(int(height), []).append(fmt)

    options: list[dict[str, Any]] = []
    for height in sorted(by_height.keys(), reverse=True):
        candidates = by_height[height]
        best = max(
            candidates,
            key=lambda f: (
                f.get("vbr") or f.get("tbr") or 0,
                f.get("filesize") or f.get("filesize_approx") or 0,
                1 if _is_progressive(f) else 0,
            ),
        )
        has_progressive = any(_is_progressive(f) for f in candidates)
        size = best.get("filesize") or best.get("filesize_approx")
        fps = best.get("fps")
        tbr = best.get("vbr") or best.get("tbr")
        details: list[str] = []
        if fps:
            details.append(f"{int(fps)} fps")
        vcodec = best.get("vcodec")
        if vcodec and vcodec not in {"unknown", "none"}:
            details.append(str(vcodec).split(".")[0])
        if tbr:
            details.append(f"{int(tbr)} kbps")
        if size:
            details.append(format_bytes(size) or "")
        details.append("MP4" if has_progressive else "merge → MP4")

        format_id = (
            f"bv*[height={height}]+ba/"
            f"b[height={height}]/"
            f"best[height={height}]"
        )
        options.append(
            {
                "format_id": format_id,
                "label": f"{height}p",
                "height": height,
                "ext": "mp4",
                "fps": fps,
                "filesize": size,
                "filesize_display": format_bytes(size),
                "needs_merge": not has_progressive,
                "description": " · ".join(d for d in details if d),
                "recommended": False,
            }
        )

    if options:
        options.insert(
            0,
            {
                "format_id": "bv*+ba/b",
                "label": "Лучшее доступное",
                "height": options[0]["height"],
                "ext": "mp4",
                "fps": options[0].get("fps"),
                "filesize": options[0].get("filesize"),
                "filesize_display": options[0].get("filesize_display"),
                "needs_merge": True,
                "description": "yt-dlp best video + best audio",
                "recommended": True,
            },
        )
    return options


def extract_info(url: str) -> dict[str, Any]:
    ensure_ffmpeg_on_path()
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "http_headers": HTTP_HEADERS,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError("Не удалось получить метаданные видео.")
    return info


def download_video(
    url: str,
    format_id: str,
    output_template: str,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    ensure_ffmpeg_on_path()

    def hook(d: dict[str, Any]) -> None:
        if not progress_cb:
            return
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0
            percent = 0.0
            if total:
                percent = max(0.0, min(100.0, downloaded * 100.0 / total))
            elif d.get("fragment_index") and d.get("fragment_count"):
                percent = d["fragment_index"] * 100.0 / max(1, d["fragment_count"])
            eta = d.get("eta")
            progress_cb(
                {
                    "status": "downloading",
                    "percent": round(percent, 1),
                    "speed": format_speed(d.get("speed")),
                    "eta": format_eta(eta),
                    "eta_seconds": eta,
                    "downloaded_bytes": downloaded,
                    "total_bytes": total,
                    "message": "Скачивание…",
                }
            )
        elif status == "finished":
            progress_cb(
                {
                    "status": "processing",
                    "percent": 99.0,
                    "message": "Обработка / склейка…",
                    "eta": None,
                    "speed": None,
                }
            )

    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": format_id,
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "prefer_ffmpeg": True,
        "http_headers": HTTP_HEADERS,
        "progress_hooks": [hook],
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise RuntimeError("Download returned empty info")
        path = Path(ydl.prepare_filename(info))
        if path.suffix != ".mp4":
            mp4_path = path.with_suffix(".mp4")
            if mp4_path.exists():
                path = mp4_path
        if not path.exists():
            job_dir = Path(output_template).parent
            files = [
                f
                for f in job_dir.iterdir()
                if f.is_file() and f.suffix.lower() in {".mp4", ".mkv", ".webm"}
            ]
            if not files:
                raise RuntimeError("Файл после скачивания не найден")
            path = max(files, key=lambda p: p.stat().st_size)
        return path
