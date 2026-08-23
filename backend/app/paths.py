from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than a source checkout."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def frontend_dist() -> Path:
    """Directory holding the built UI.

    Source checkout: ``<repo>/frontend/dist``, produced by ``npm run build``.
    Frozen bundle: the copy embedded at build time, under the same relative
    name inside PyInstaller's extraction directory (``sys._MEIPASS``).

    Resolving this from ``__file__`` alone would break once frozen, since the
    module then lives in a temporary extraction tree, not in the repo.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle is not None:
        return Path(bundle) / "frontend" / "dist"
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"
