# PyInstaller recipe for the installed Windows app (TradingApp.exe).
#
# It bundles Python itself, every package in requirements.txt, the engine, the
# screens (ui/), config/ and the example scripts into one folder, so the owner
# needs nothing else installed. Build it with packaging\build_windows.bat, or
# let GitHub build it (.github/workflows/windows-app.yml).
#
#   pyinstaller --noconfirm packaging/trading_app.spec

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent          # the project folder (SPECPATH is this file's folder)

# Read-only app files, placed in the bundle at the same relative paths that
# engine/paths.py resource_dir() expects.
datas = [
    (str(ROOT / "ui"), "ui"),
    (str(ROOT / "config"), "config"),
    (str(ROOT / "scripts" / "examples"), "scripts/examples"),
]
datas += collect_data_files("tzdata")          # time zones (Windows has none for Python)
datas += collect_data_files("webview")         # pywebview's own scripts and the WebView2 bridge

hiddenimports = []
# The engine is started by name and loads its parts as it goes; include all of it.
hiddenimports += collect_submodules("engine")
hiddenimports += collect_submodules("desktop")
# The web server picks its pieces at run time.
hiddenimports += collect_submodules("uvicorn")
# Passwords live in Windows Credential Manager through keyring's Windows backend.
hiddenimports += collect_submodules("keyring.backends")
# Modules the owner's scripts may import (engine/scripting/sandbox.py ALLOWED_MODULES)
# that the engine itself might not, so they must be bundled explicitly.
hiddenimports += [
    "math", "statistics", "numpy", "pandas", "datetime", "collections",
    "itertools", "functools", "random", "dataclasses", "typing",
]
# MetaTrader 5 is optional: include it when it was installed for this build.
try:
    import MetaTrader5  # noqa: F401
    hiddenimports.append("MetaTrader5")
except ImportError:
    pass

a = Analysis(
    [str(ROOT / "desktop" / "entry.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "matplotlib", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TradingApp",
    icon=str(ROOT / "packaging" / "app_icon.ico"),
    console=False,                     # a normal window app, no black console box
    upx=False,                         # UPX-packed files upset antivirus programs
    version=str(ROOT / "packaging" / "version_info.txt") if (ROOT / "packaging" / "version_info.txt").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="TradingApp",
)
