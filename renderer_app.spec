# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH)
ICON = ROOT / "assets" / "downmix_renderer_logo.ico"
DIST_NAME = os.environ.get("DOWNMIX_RENDERER_DIST_NAME", "Finalised Version")

VERSION_INFO = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(0, 1, 0, 0),
        prodvers=(0, 1, 0, 0),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Taran"),
                        StringStruct("FileDescription", "Downmix Renderer"),
                        StringStruct("FileVersion", "0.1.0.0"),
                        StringStruct("InternalName", "Downmixrenderer"),
                        StringStruct("OriginalFilename", "Downmixrenderer.exe"),
                        StringStruct("ProductName", "Downmix Renderer"),
                        StringStruct("ProductVersion", "0.1.0.0"),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

a = Analysis(
    ["renderer_app.py"],
    pathex=[str(ROOT)],
    binaries=[(str(ROOT / "downmix_renderer" / "downmix_renderer_native.dll"), "downmix_renderer")],
    datas=[
        (str(ROOT / "assets" / "downmix_renderer_logo.png"), "assets"),
        (str(ROOT / "assets" / "downmix_renderer_logo.ico"), "assets"),
    ],
    hiddenimports=["pythoncom", "pywintypes", "win32com", "win32com.client"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="Downmixrenderer",
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
    icon=str(ICON) if ICON.exists() else None,
    version=VERSION_INFO,
    exclude_binaries=True,
    contents_directory="_internal",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=DIST_NAME,
)
