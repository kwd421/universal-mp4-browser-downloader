# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


ROOT = Path(SPECPATH).resolve().parent
ENTRYPOINT = ROOT / "tools" / "clipflow_qt.py"

datas = [
    (str(ROOT / "assets" / "icons" / "lucide"), "assets/icons/lucide"),
]
binaries = []
hiddenimports = []

hiddenimports += collect_submodules("yt_dlp")
hiddenimports += ["PySide6.QtSvg", "tools.clipflow_download_process"]

for package in ("imageio_ffmpeg", "yt_dlp_ejs", "PIL", "curl_cffi"):
    tmp_ret = collect_all(package)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]


a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["electron"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ClipFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="ClipFlow.app",
        bundle_identifier="com.clipflow.app",
    )
