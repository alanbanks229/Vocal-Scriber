# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH).resolve().parents[1]
assets_dir = project_root / "build" / "windows-app" / "assets"
icon_path = assets_dir / "vocal_scriber.ico"
version_path = assets_dir / "version_info.txt"
python_base = Path(sys.base_prefix)
tcl_root = python_base / "tcl"
tcl_library = tcl_root / "tcl8.6"
tk_library = tcl_root / "tk8.6"

if tcl_library.exists():
    os.environ.setdefault("TCL_LIBRARY", str(tcl_library))
if tk_library.exists():
    os.environ.setdefault("TK_LIBRARY", str(tk_library))

datas = []
binaries = []
hiddenimports = ["tkinter", "_tkinter"]
collect_trees = []

for package_name in (
    "whisper",
    "torch",
    "tiktoken",
    "regex",
    "pystray",
    "PIL",
    "numpy",
    "scipy",
    "sounddevice",
    "pyperclip",
    "pynput",
):
    collected = collect_all(package_name)
    datas += collected[0]
    binaries += collected[1]
    hiddenimports += collected[2]

if tcl_root.exists():
    collect_trees.append(Tree(str(tcl_root), prefix="tcl"))

a = Analysis(
    [str(project_root / "packaging" / "windows" / "app_launcher.py")],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Vocal-Scriber",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon_path),
    version=str(version_path),
)

coll = COLLECT(
    exe,
    *collect_trees,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Vocal-Scriber",
)
