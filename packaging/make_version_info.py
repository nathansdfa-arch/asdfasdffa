"""Write packaging/version_info.txt (the version shown in Windows' file Properties)
and print the app version, for the build script and the installer.

    python packaging/make_version_info.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import __version__  # noqa: E402

numbers = [int(part) for part in __version__.split(".")[:3]] + [0]
version_tuple = tuple((numbers + [0, 0, 0, 0])[:4])

(ROOT / "packaging" / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={version_tuple}, prodvers={version_tuple}),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Trading App'),
      StringStruct('FileDescription', 'Trading App'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'TradingApp'),
      StringStruct('OriginalFilename', 'TradingApp.exe'),
      StringStruct('ProductName', 'Trading App'),
      StringStruct('ProductVersion', '{__version__}'),
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
""", encoding="utf-8")
print(__version__)
