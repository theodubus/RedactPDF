#!/usr/bin/env python3
"""Build the standalone RedactPDF desktop app.

    python scripts/build_app.py

Produces a single executable in ``dist/``. Requires the ``packaging`` extra
(``pip install -e "backend[dev,packaging]"``) and a working Node toolchain for
the frontend build.

PyInstaller does not cross-compile: run this on the OS you are targeting.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "redactpdf.spec"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def _fail(message: str) -> None:
    sys.exit(f"error: {message}")


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"\n$ {' '.join(cmd)}  (in {cwd.relative_to(ROOT)})", flush=True)
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        _fail(f"command failed with exit code {result.returncode}: {' '.join(cmd)}")


def build_frontend() -> None:
    npm = shutil.which("npm")
    if npm is None:
        _fail("npm not found on PATH; Node 20+ is required to build the frontend")

    frontend = ROOT / "frontend"
    if not (frontend / "node_modules").is_dir():
        _fail(f"frontend dependencies missing; run `npm ci` in {frontend}")

    _run([npm, "run", "build"], cwd=frontend)

    if not (frontend / "dist" / "index.html").is_file():
        _fail("frontend build produced no dist/index.html")


def build_executable(clean: bool) -> Path:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        _fail('PyInstaller missing; install it with: pip install -e "backend[dev,packaging]"')

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC),
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--noconfirm",
    ]
    if clean:
        cmd.append("--clean")
    _run(cmd, cwd=ROOT)

    # The spec's `name` carries no extension; PyInstaller appends .exe on Windows.
    exe = DIST / ("redactpdf.exe" if sys.platform == "win32" else "redactpdf")
    if not exe.is_file():
        _fail(f"expected executable not found at {exe}")
    return exe


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="reuse the existing frontend/dist instead of rebuilding it",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="discard PyInstaller's cache before building",
    )
    args = parser.parse_args()

    if args.skip_frontend:
        if not (ROOT / "frontend" / "dist" / "index.html").is_file():
            _fail("--skip-frontend given but frontend/dist/index.html does not exist")
        print("skipping frontend build, reusing frontend/dist")
    else:
        build_frontend()

    exe = build_executable(clean=args.clean)
    size_mb = exe.stat().st_size / (1024 * 1024)
    prefix = ".\\" if sys.platform == "win32" else "./"
    print(f"\nBuilt {exe.relative_to(ROOT)} ({size_mb:.1f} MB)")
    print(f"Run it with:  {prefix}{exe.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
