"""Desktop entrypoint: local server + browser/webview UI."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _patch_stdio_for_windowed() -> Path | None:
    """PyInstaller console=False leaves sys.stdout/stderr as None on Windows.

    Uvicorn's ColorFormatter calls stdout.isatty() and crashes without this.
    """
    log_path: Path | None = None
    try:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(__file__).resolve().parent
        log_path = base / "vk-video-downloader.log"
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    except OSError:
        log_file = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        log_path = None

    class _Stream:
        def __init__(self, *streams):
            self._streams = streams

        def write(self, data):
            for stream in self._streams:
                try:
                    stream.write(data)
                except Exception:
                    pass
            return len(data) if isinstance(data, str) else 0

        def flush(self):
            for stream in self._streams:
                try:
                    stream.flush()
                except Exception:
                    pass

        def isatty(self):
            return False

        def fileno(self):
            raise OSError("no fileno")

        @property
        def encoding(self):
            return "utf-8"

        def readable(self):
            return False

        def writable(self):
            return True

        def seekable(self):
            return False

    if sys.stdout is None:
        sys.stdout = _Stream(log_file)
    if sys.stderr is None:
        sys.stderr = _Stream(log_file)

    # Also attach a basic file logger for unexpected errors
    if log_path is not None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            handlers=[logging.FileHandler(log_path, encoding="utf-8")],
            force=False,
        )
    return log_path


_patch_stdio_for_windowed()

import uvicorn

from vkvideodl.paths import ensure_ffmpeg_on_path, read_version
from vkvideodl.updater import load_config

# Avoid uvicorn ColorFormatter (uses stdout.isatty) entirely.
SAFE_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "logging.Formatter",
            "fmt": "%(levelname)s:     %(message)s",
        },
        "access": {
            "()": "logging.Formatter",
            "fmt": '%(levelname)s:     %(client_addr)s - "%(request_line)s" %(status_code)s',
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
    },
}


def _free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


def _wait_ready(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def main(argv: list[str] | None = None) -> int:
    ensure_ffmpeg_on_path()
    cfg = load_config()
    parser = argparse.ArgumentParser(description="VK Video Downloader")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(cfg.get("default_port", 8787)))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--webview", action="store_true", help="Use native WebView2 window when available")
    args = parser.parse_args(argv)

    host = args.host
    port = _free_port(args.port)
    url = f"http://{host}:{port}/"

    config = uvicorn.Config(
        "vkvideodl.server:app",
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        log_config=SAFE_LOG_CONFIG,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if not _wait_ready(host, port):
        print("Failed to start local server", file=sys.stderr)
        return 1

    print(f"VK Video Downloader v{read_version()}")
    print(f"UI: {url}")

    use_webview = args.webview
    if use_webview or sys.platform.startswith("win"):
        try:
            import webview  # type: ignore

            webview.create_window(
                f"VK Video Downloader v{read_version()}",
                url,
                width=980,
                height=820,
                background_color="#0f1412",
            )
            webview.start()
            server.should_exit = True
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"WebView unavailable ({exc}), opening system browser…")

    if not args.no_browser:
        webbrowser.open(url)

    try:
        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
