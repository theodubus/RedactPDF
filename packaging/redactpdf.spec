# PyInstaller spec for the RedactPDF desktop app.
#
# Do not run `pyinstaller` on this file directly -- use `python scripts/build_app.py`,
# which builds the frontend first and checks the prerequisites.
#
# One build per OS: PyInstaller does not cross-compile.
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821  (SPECPATH is injected by PyInstaller)

# The UI is served same-origin from inside the bundle; app/paths.py looks it up
# at "frontend/dist" relative to the extraction dir, so keep that layout here.
datas = [(str(ROOT / "frontend" / "dist"), "frontend/dist")]

hiddenimports = [
    # uvicorn resolves its protocol/loop/lifespan implementations by string at
    # runtime, so static analysis alone does not pull them in.
    *collect_submodules("uvicorn"),
    # phonenumbers loads per-region metadata modules lazily (phonenumbers.data.*),
    # and REDACT_DEFAULT_REGION means we cannot know which ones in advance.
    *collect_submodules("phonenumbers"),
]

binaries = collect_dynamic_libs("pymupdf")

a = Analysis(  # noqa: F821
    [str(ROOT / "launch.py")],
    pathex=[str(ROOT / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trimmed on purpose: PyMuPDF and reportlab can pull these in, and they add
    # tens of MB to a tool that never renders a GUI toolkit or plots anything.
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="redactpdf",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # onefile: a single artifact a non-technical user can download and run.
    # Costs a few seconds of extraction on each start.
    runtime_tmpdir=None,
    # The app's only UI is the browser tab; a terminal window would just be noise
    # on a double-click. Startup errors still reach a terminal when run from one.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
