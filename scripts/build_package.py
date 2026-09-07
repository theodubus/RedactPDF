#!/usr/bin/env python3
"""Build the RedactPDF wheel and sdist.

    python scripts/build_package.py

Produces ``backend/dist/*.whl`` and ``backend/dist/*.tar.gz``. Requires the
``wheel`` extra (``pip install -e "backend[dev,wheel]"``) and, unless
``--skip-frontend`` is passed, a working Node toolchain.

Two files have to be staged inside the package root before building, because
setuptools cannot reach above it:

- ``frontend/dist``  -> ``backend/redactpdf/_frontend`` (the UI, served
  same-origin by the launcher; ``redactpdf/paths.py`` looks it up there once
  installed);
- ``LICENSE.md``     -> ``backend/LICENSE.md`` (AGPL-3.0: the licence text
  travels with the distribution).

Both copies are build artefacts and are git-ignored.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PACKAGE = BACKEND / "redactpdf"
FRONTEND = ROOT / "frontend"
STAGED_UI = PACKAGE / "_frontend"
STAGED_LICENSE = BACKEND / "LICENSE.md"
DIST = BACKEND / "dist"


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

    if not (FRONTEND / "node_modules").is_dir():
        _fail(f"frontend dependencies missing; run `npm ci` in {FRONTEND}")

    _run([npm, "run", "build"], cwd=FRONTEND)


def stage_package_data() -> None:
    """Copy the UI and the licence into the package root."""
    built_ui = FRONTEND / "dist"
    if not (built_ui / "index.html").is_file():
        _fail(
            f"frontend build not found at {built_ui}; run it first "
            "(or drop --skip-frontend)"
        )

    if STAGED_UI.exists():
        shutil.rmtree(STAGED_UI)
    shutil.copytree(built_ui, STAGED_UI)
    print(f"staged UI      -> {STAGED_UI.relative_to(ROOT)}")

    licence = ROOT / "LICENSE.md"
    if not licence.is_file():
        _fail(f"licence not found at {licence}")
    shutil.copy2(licence, STAGED_LICENSE)
    print(f"staged licence -> {STAGED_LICENSE.relative_to(ROOT)}")


def build_distributions(clean: bool) -> list[Path]:
    try:
        import build  # noqa: F401
    except ImportError:
        _fail('`build` missing; install it with: pip install -e "backend[dev,wheel]"')

    if clean and DIST.exists():
        shutil.rmtree(DIST)

    _run([sys.executable, "-m", "build"], cwd=BACKEND)

    produced = sorted(DIST.glob("*"))
    if not produced:
        _fail(f"no distribution produced in {DIST}")
    return produced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="reuse the existing frontend/dist instead of rebuilding it",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="keep whatever is already in backend/dist",
    )
    args = parser.parse_args()

    if not args.skip_frontend:
        build_frontend()

    stage_package_data()
    produced = build_distributions(clean=not args.no_clean)

    print("\nBuilt:")
    for path in produced:
        size_kb = path.stat().st_size / 1024
        print(f"  {path.relative_to(ROOT)}  ({size_kb:.0f} kB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
