# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — portable Windows/Linux/macOS build."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
root = Path(SPECPATH).resolve().parent

datas = [
    (str(root / "static"), "static"),
    (str(root / "VERSION"), "."),
    (str(root / "vkvideodl" / "config.json"), "vkvideodl"),
]

ffmpeg_dir = root / "ffmpeg"
if ffmpeg_dir.is_dir():
    datas.append((str(ffmpeg_dir), "ffmpeg"))

binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "vkvideodl",
    "vkvideodl.server",
    "vkvideodl.downloader",
    "vkvideodl.updater",
    "vkvideodl.jobs",
    "vkvideodl.paths",
    "vkvideodl.settings",
    "tkinter",
    "tkinter.font",
    "webview",
]

for pkg in ("yt_dlp", "uvicorn", "anyio", "starlette", "fastapi", "tkinter"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    [str(root / "launcher.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(root / "packaging" / "pyi_rth_ffmpeg.py")],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VKVideoDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # Windows GUI subsystem — no console flash
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root / "packaging" / "icon.ico") if (root / "packaging" / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VKVideoDownloader",
)
