"""FastAPI application."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from vkvideodl import downloader, settings, updater
from vkvideodl.jobs import jobs
from vkvideodl.paths import (
    ensure_ffmpeg_on_path,
    ffmpeg_binary,
    is_frozen,
    read_version,
    static_dir,
)

ensure_ffmpeg_on_path()

app = FastAPI(
    title="VK Video Downloader",
    version=read_version(),
    description="Local content manager for downloading VK / VK Video clips.",
)


class AnalyzeRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("URL is empty")
        if not value.startswith(("http://", "https://")):
            value = "https://" + value
        return value


class DownloadRequest(AnalyzeRequest):
    format_id: str = Field(..., min_length=1, max_length=256)


class UpdateApplyRequest(BaseModel):
    asset_url: str = Field(..., min_length=8, max_length=2048)
    asset_name: str | None = None


class SettingsPatch(BaseModel):
    download_dir: str | None = None


class OpenPathRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)


def _cleanup_job(job_dir: Path) -> None:
    shutil.rmtree(job_dir, ignore_errors=True)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    cfg = updater.load_config()
    return {
        "status": "ok",
        "version": read_version(),
        "yt_dlp": yt_dlp.version.__version__,
        "ffmpeg": "available" if ffmpeg_binary() else "missing",
        "github_repo": cfg.get("github_repo"),
        "platform": updater.platform_tag(),
        "frozen": is_frozen(),
        "download_dir": str(settings.get_download_dir()),
    }


@app.get("/api/version")
async def version_info() -> dict[str, Any]:
    cfg = updater.load_config()
    return {
        "version": read_version(),
        "name": cfg.get("name"),
        "github_repo": cfg.get("github_repo"),
        "platform": updater.platform_tag(),
        "frozen": is_frozen(),
        "about": {
            "product": "VK Video Downloader",
            "dedication": "Сделано для Vadimus от NIX",
            "org": "NIX",
        },
    }


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    return settings.load_settings()


@app.post("/api/settings")
async def patch_settings(payload: SettingsPatch) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True)
    try:
        return await asyncio.to_thread(settings.save_settings, patch)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось сохранить папку: {exc}") from exc


@app.post("/api/settings/choose-dir")
async def choose_dir() -> dict[str, Any]:
    selected = await asyncio.to_thread(settings.choose_download_dir)
    if not selected:
        return {"cancelled": True, **settings.load_settings()}
    data = await asyncio.to_thread(settings.save_settings, {"download_dir": selected})
    return {"cancelled": False, **data}


@app.post("/api/settings/open-path")
async def open_path(payload: OpenPathRequest) -> dict[str, Any]:
    path = Path(payload.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Путь не найден")
    await asyncio.to_thread(settings.open_in_file_manager, path)
    return {"ok": True}


@app.post("/api/analyze")
async def analyze(payload: AnalyzeRequest) -> dict[str, Any]:
    try:
        url = downloader.validate_vk_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        info = await asyncio.to_thread(downloader.extract_info, url)
    except yt_dlp.utils.DownloadError as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка извлечения: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    qualities = downloader.build_quality_options(info)
    if not qualities:
        raise HTTPException(status_code=404, detail="Доступные форматы видео не найдены.")

    video_id = info.get("id") or "unknown"
    title = info.get("title") or f"VK Video {video_id}"
    return {
        "id": video_id,
        "title": title,
        "uploader": info.get("uploader") or info.get("channel") or info.get("creator"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "webpage_url": info.get("webpage_url") or url,
        "qualities": qualities,
        "raw_format_count": len(info.get("formats") or []),
    }


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for idx in range(2, 1000):
        alt = directory / f"{stem} ({idx}){suffix}"
        if not alt.exists():
            return alt
    return directory / f"{stem}-{uuid.uuid4().hex[:6]}{suffix}"


def _run_download_job(job_id: str, url: str, format_id: str) -> None:
    target_dir = settings.get_download_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    work_dir = target_dir / f".tmp-{job_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(work_dir / "%(title).80B [%(id)s].%(ext)s")
    jobs.update(job_id, status="downloading", message="Скачивание…", percent=0)

    def on_progress(fields: dict[str, Any]) -> None:
        jobs.update(job_id, **fields)

    try:
        path = downloader.download_video(url, format_id, output_template, progress_cb=on_progress)
        final_name = downloader.safe_filename(path.stem, job_id) + path.suffix
        final_path = _unique_path(target_dir, final_name)
        shutil.move(str(path), str(final_path))
        _cleanup_job(work_dir)
        size = final_path.stat().st_size
        jobs.update(
            job_id,
            status="done",
            percent=100,
            message="Готово",
            filename=final_path.name,
            saved_path=str(final_path),
            size=size,
            size_display=downloader.format_bytes(size),
            download_url=None,
            eta=None,
            speed=None,
        )
    except Exception as exc:  # noqa: BLE001
        _cleanup_job(work_dir)
        jobs.update(
            job_id,
            status="error",
            message=str(exc),
            error=str(exc),
            percent=0,
        )


@app.post("/api/download")
async def start_download(payload: DownloadRequest) -> dict[str, Any]:
    try:
        url = downloader.validate_vk_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    format_id = payload.format_id.strip()
    if not re.fullmatch(r"[\w+\-./\[\]*=<>]+", format_id):
        raise HTTPException(status_code=400, detail="Некорректный format_id")

    job_id = uuid.uuid4().hex[:12]
    jobs.create(job_id, kind="download")
    asyncio.create_task(asyncio.to_thread(_run_download_job, job_id, url, format_id))
    return {
        "job_id": job_id,
        "download_dir": str(settings.get_download_dir()),
        "status_url": f"/api/jobs/{job_id}",
        "events_url": f"/api/jobs/{job_id}/events",
    }


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return job


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    if not jobs.get(job_id):
        raise HTTPException(status_code=404, detail="Задача не найдена")

    async def event_stream():
        last = None
        while True:
            job = jobs.get(job_id)
            if not job:
                yield f"data: {json.dumps({'status': 'error', 'message': 'gone'})}\n\n"
                break
            payload = json.dumps(job, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if job.get("status") in {"done", "error"}:
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/files/{job_id}")
async def fetch_file(job_id: str) -> dict[str, Any]:
    # Legacy endpoint kept for compatibility; new downloads save to chosen folder.
    raise HTTPException(
        status_code=410,
        detail="Файл сохраняется в выбранную папку. Используйте «Открыть папку».",
    )


@app.get("/api/updates/check")
async def updates_check() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(updater.check_for_updates)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/updates/apply")
async def updates_apply(payload: UpdateApplyRequest) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:12]
    jobs.create(job_id, kind="update")

    def run() -> None:
        def on_progress(fields: dict[str, Any]) -> None:
            jobs.update(job_id, **fields)

        try:
            result = updater.download_and_apply_update(
                payload.asset_url,
                asset_name=payload.asset_name,
                progress_cb=on_progress,
            )
            jobs.update(
                job_id,
                status="done",
                percent=100,
                message="Обновление готово. Перезапуск…",
                **{k: v for k, v in result.items() if k != "message"},
            )
            import time

            time.sleep(1.5)
            __import__("os")._exit(0)
        except Exception as exc:  # noqa: BLE001
            jobs.update(job_id, status="error", error=str(exc), message=str(exc))

    asyncio.create_task(asyncio.to_thread(run))
    return {"job_id": job_id, "events_url": f"/api/jobs/{job_id}/events"}


app.mount("/", StaticFiles(directory=str(static_dir()), html=True), name="static")
