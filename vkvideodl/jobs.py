"""In-memory download / update job progress registry."""

from __future__ import annotations

import threading
import time
from typing import Any


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, job_id: str, kind: str = "download") -> dict[str, Any]:
        job = {
            "id": job_id,
            "kind": kind,
            "status": "queued",
            "percent": 0.0,
            "speed": None,
            "eta": None,
            "eta_seconds": None,
            "downloaded_bytes": 0,
            "total_bytes": None,
            "message": "В очереди…",
            "filename": None,
            "download_url": None,
            "size": None,
            "size_display": None,
            "error": None,
            "updated_at": time.time(),
        }
        with self._lock:
            self._jobs[job_id] = job
        return job

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(fields)
            job["updated_at"] = time.time()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        return self.get(job_id)


jobs = JobStore()
