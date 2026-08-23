#!/usr/bin/env python3
"""RedactPDF desktop launcher.

Starts the backend on a free local port, serves the built UI same-origin, opens
it in the default browser, and shuts down a few seconds after the tab is closed
(heartbeat watchdog).

    python launch.py

Prerequisite -- build the frontend once so the backend has something to serve:

    cd frontend && npm run build

Environment variables (both exist for the automated smoke test, and are useful
when a fixed address is wanted):

    REDACT_PORT=8765     bind this port instead of picking a free one
    REDACT_NO_BROWSER=1  do not open a browser
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import NoReturn

import uvicorn
from uvicorn.config import LOGGING_CONFIG

if not getattr(sys, "frozen", False):
    # Source checkout: make the backend package importable without installing it.
    # In a PyInstaller bundle the package is already on the frozen import path.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.heartbeat import start_watchdog  # noqa: E402  (must follow sys.path tweak)
from app.main import app  # noqa: E402
from app.paths import frontend_dist, is_frozen  # noqa: E402


def _write(message: str) -> None:
    """Print without assuming a usable stream.

    A windowed PyInstaller build (console=False, how the release is built) has
    sys.stdout and sys.stderr set to None, where a bare print() raises.
    """
    stream = sys.stderr or sys.stdout
    if stream is not None:
        try:
            print(message, file=stream)
        except Exception:
            pass


def _show_error_dialog(message: str) -> bool:
    """Best-effort GUI error box; returns False when none could be shown."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        mb_ok_iconerror = 0x10
        ctypes.windll.user32.MessageBoxW(None, message, "RedactPDF", mb_ok_iconerror)
        return True
    except Exception:
        return False


def _fatal(message: str) -> NoReturn:
    """Report a startup failure through whatever channel this build has.

    Without this, a windowed build that fails to start is completely silent: no
    console, no window, a double-click that appears to do nothing at all.
    """
    if not _show_error_dialog(message):
        _write(message)
    raise SystemExit(1)


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _resolve_port(host: str) -> int:
    raw = os.getenv("REDACT_PORT", "").strip()
    if not raw:
        return _free_port(host)
    try:
        port = int(raw)
    except ValueError:
        _fatal(f"REDACT_PORT must be a whole number, got {raw!r}.")
    if not 0 < port < 65536:
        _fatal(f"REDACT_PORT must be between 1 and 65535, got {port}.")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
    except OSError as e:
        _fatal(f"Cannot bind port {port}: {e}")
    return port


def main() -> None:
    if not (frontend_dist() / "index.html").is_file():
        # In a bundle this means the build forgot to embed the UI, which the user
        # can do nothing about; in a checkout it is just a missing npm build.
        _fatal(
            "Frontend build missing from this bundle -- rebuild it with scripts/build_app.py"
            if is_frozen()
            else "Frontend build not found (frontend/dist).\n"
            "Build it once:  cd frontend && npm run build"
        )

    host = "127.0.0.1"
    port = _resolve_port(host)
    url = f"http://{host}:{port}"

    # A windowed build (console=False) has no sys.stdout, and uvicorn's default
    # log config asks sys.stdout.isatty() which colours to use -- which raises
    # before the server ever starts. Nothing could read those logs anyway, so
    # skip the logging setup entirely when there is no stream to write to.
    has_streams = sys.stdout is not None and sys.stderr is not None
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            log_config=LOGGING_CONFIG if has_streams else None,
        )
    )

    def _open_when_ready() -> None:
        for _ in range(100):  # wait up to ~10s for uvicorn to accept connections
            if server.started:
                webbrowser.open(url)
                return
            time.sleep(0.1)

    start_watchdog(on_idle=lambda: setattr(server, "should_exit", True))
    if os.getenv("REDACT_NO_BROWSER", "").strip():
        _write(f"RedactPDF running at {url}  -  browser not opened (REDACT_NO_BROWSER).")
    else:
        threading.Thread(target=_open_when_ready, name="open-browser", daemon=True).start()
        _write(f"RedactPDF running at {url}  -  close the browser tab to stop.")

    server.run()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001  (last resort: a silent crash is the worst outcome)
        _fatal("RedactPDF failed to start.\n\n" + traceback.format_exc())
