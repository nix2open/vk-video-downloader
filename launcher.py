"""Desktop entrypoint: local server + visible host window / browser UI."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path


def _app_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _patch_stdio_for_windowed() -> Path:
    """PyInstaller console=False leaves sys.stdout/stderr as None on Windows."""
    base = _app_base()
    log_path = base / "vk-video-downloader.log"
    try:
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    except OSError:
        log_file = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        log_path = base / "vk-video-downloader.log"

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

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
    return log_path


LOG_PATH = _patch_stdio_for_windowed()
log = logging.getLogger("launcher")

import uvicorn

from vkvideodl.paths import ensure_ffmpeg_on_path, read_version
from vkvideodl.server import app as fastapi_app
from vkvideodl.updater import load_config

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


def _message_box(title: str, text: str) -> None:
    if not sys.platform.startswith("win"):
        print(f"{title}: {text}")
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10 if "ошиб" in text.lower() or "fail" in text.lower() else 0x40)
    except Exception:
        pass


def _free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


def _wait_ready(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _run_status_window(url: str, version: str, server: uvicorn.Server) -> None:
    """Visible host window so the process stays alive and the user sees something."""
    import tkinter as tk
    from tkinter import font as tkfont

    root = tk.Tk()
    root.title(f"VK Video Downloader v{version}")
    root.geometry("460x220")
    root.configure(bg="#0f1412")
    root.resizable(False, False)

    title_font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
    body_font = tkfont.Font(family="Segoe UI", size=10)

    tk.Label(
        root,
        text="VK Video Downloader",
        fg="#e8f0ea",
        bg="#0f1412",
        font=title_font,
    ).pack(pady=(22, 6))

    tk.Label(
        root,
        text=f"Сервер запущен\n{url}",
        fg="#9aafa3",
        bg="#0f1412",
        font=body_font,
        justify="center",
    ).pack(pady=4)

    tk.Label(
        root,
        text="Закройте это окно, чтобы остановить программу.",
        fg="#9aafa3",
        bg="#0f1412",
        font=body_font,
    ).pack(pady=(4, 12))

    btn_row = tk.Frame(root, bg="#0f1412")
    btn_row.pack(pady=8)

    def open_ui() -> None:
        webbrowser.open(url)

    def quit_app() -> None:
        server.should_exit = True
        root.destroy()

    tk.Button(
        btn_row,
        text="Открыть интерфейс",
        command=open_ui,
        bg="#2f9e78",
        fg="#04140e",
        activebackground="#3bb589",
        relief="flat",
        padx=14,
        pady=8,
        font=body_font,
    ).pack(side="left", padx=6)

    tk.Button(
        btn_row,
        text="Выход",
        command=quit_app,
        bg="#1f2924",
        fg="#e8f0ea",
        activebackground="#2a3831",
        relief="flat",
        padx=14,
        pady=8,
        font=body_font,
    ).pack(side="left", padx=6)

    root.protocol("WM_DELETE_WINDOW", quit_app)
    root.after(400, open_ui)
    root.mainloop()


def main(argv: list[str] | None = None) -> int:
    log.info("Starting VK Video Downloader v%s (frozen=%s)", read_version(), getattr(sys, "frozen", False))
    ensure_ffmpeg_on_path()
    cfg = load_config()
    parser = argparse.ArgumentParser(description="VK Video Downloader")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(cfg.get("default_port", 8787)))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--webview", action="store_true", help="Use native WebView window instead of browser")
    args = parser.parse_args(argv)

    host = args.host
    port = _free_port(args.port)
    url = f"http://{host}:{port}/"
    version = read_version()

    config = uvicorn.Config(
        fastapi_app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        log_config=SAFE_LOG_CONFIG,
    )
    server = uvicorn.Server(config)

    # Non-daemon: keep process semantics clearer while UI loop runs
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    if not _wait_ready(host, port):
        msg = (
            "Не удалось запустить локальный сервер.\n\n"
            f"Подробности в файле:\n{LOG_PATH}"
        )
        log.error("Server failed to become ready on %s:%s", host, port)
        _message_box("VK Video Downloader", msg)
        return 1

    log.info("Server ready at %s", url)
    print(f"VK Video Downloader v{version}")
    print(f"UI: {url}")

    if args.webview:
        try:
            import webview  # type: ignore

            webview.create_window(
                f"VK Video Downloader v{version}",
                url,
                width=980,
                height=820,
                background_color="#0f1412",
            )
            webview.start()
            server.should_exit = True
            return 0
        except Exception as exc:  # noqa: BLE001
            log.exception("WebView failed: %s", exc)
            _message_box(
                "VK Video Downloader",
                f"WebView недоступен ({exc}).\nОткрываю через браузер.",
            )

    # Default reliable path: status window + system browser
    try:
        if not args.no_browser:
            # Also opened from the status window; open once early for faster UX
            webbrowser.open(url)
        _run_status_window(url, version, server)
    except Exception as exc:  # noqa: BLE001
        log.exception("UI host failed: %s", exc)
        if not args.no_browser:
            webbrowser.open(url)
        _message_box(
            "VK Video Downloader",
            f"Окно статуса недоступно ({exc}).\n"
            f"Интерфейс: {url}\n"
            f"Лог: {LOG_PATH}\n\n"
            "Сервер работает, пока этот процесс жив. Закройте его в Диспетчере задач для остановки.",
        )
        try:
            while thread.is_alive():
                thread.join(timeout=0.5)
        except KeyboardInterrupt:
            pass

    server.should_exit = True
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        details = traceback.format_exc()
        log.error("Fatal error:\n%s", details)
        _message_box(
            "VK Video Downloader — ошибка",
            f"Критическая ошибка при запуске.\n\n{details[-800:]}\n\nЛог:\n{LOG_PATH}",
        )
        raise
