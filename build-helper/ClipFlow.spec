# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


ROOT = Path(SPECPATH).resolve().parent
ENTRYPOINT = ROOT / "tools" / "clipflow_entry.py"
ICNS = ROOT / "build-helper" / "ClipFlow.icns"
ICO = ROOT / "build-helper" / "ClipFlow.ico"

# EXE icon must match the platform: .ico on Windows, .icns on macOS.
if sys.platform == "darwin":
    EXE_ICON = str(ICNS) if ICNS.exists() else None
elif sys.platform.startswith("win"):
    EXE_ICON = str(ICO) if ICO.exists() else None
else:
    EXE_ICON = None

datas = [
    (str(ROOT / "assets" / "icons" / "lucide"), "assets/icons/lucide"),
]
binaries = []
hiddenimports = []
unused_large_modules = [
    "PIL",
    "Image",
    "ImageTk",
    "numpy",
    "numpy.libs",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtQml",
    "PySide6.QtQmlModels",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
]
unused_qt_binaries = [
    "PySide6\\Qt6Pdf.dll",
    "PySide6\\Qt6Qml.dll",
    "PySide6\\Qt6QmlMeta.dll",
    "PySide6\\Qt6QmlModels.dll",
    "PySide6\\Qt6QmlWorkerScript.dll",
    "PySide6\\Qt6Quick.dll",
]


def without_unused_binaries(toc):
    filtered = []
    for item in toc:
        name = str(item[0]).replace("/", "\\").lower()
        if any(name.endswith(binary.lower()) for binary in unused_qt_binaries):
            continue
        filtered.append(item)
    return filtered

hiddenimports += collect_submodules("yt_dlp")
hiddenimports += ["PySide6.QtSvg", "tools.clipflow_analysis_process", "tools.clipflow_download_process", "tools.clipflow_qt"]

for package in ("imageio_ffmpeg", "yt_dlp_ejs", "curl_cffi"):
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
    excludes=["electron", *unused_large_modules],
    noarchive=False,
    optimize=0,
)
a.binaries = without_unused_binaries(a.binaries)
a.datas = without_unused_binaries(a.datas)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # macOS: onedir (faster startup + recommended for .app bundles).
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="ClipFlow",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=EXE_ICON,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="ClipFlow",
    )
    app = BUNDLE(
        coll,
        name="ClipFlow.app",
        icon=str(ICNS) if ICNS.exists() else None,
        bundle_identifier="com.clipflow.app",
    )
else:
    # Windows/Linux: onefile (single distributable executable).
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
        icon=EXE_ICON,
    )
