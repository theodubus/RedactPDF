#!/usr/bin/env python3
"""RedactPDF desktop launcher.

Starts the backend on a free local port, serves the built UI same-origin, opens
it in the default browser, and shuts down a few seconds after the tab is closed
(heartbeat watchdog).

    python launch.py

Prerequisite -- build the frontend once so the backend has something to serve:

    cd frontend && npm run build
"""
from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
# Make the backend package importable without installing it.
sys.path.insert(0, str(ROOT / "backend"))

from app.heartbeat import start_watchdog  # noqa: E402  (must follow sys.path tweak)
from app.main import app  # noqa: E402


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def main() -> None:
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        sys.exit(
            "Frontend build not found (frontend/dist).\n"
            "Build it once:  cd frontend && npm run build"
        )

    host = "127.0.0.1"
    port = _free_port(host)
    url = f"http://{host}:{port}"

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))

    def _open_when_ready() -> None:
        for _ in range(100):  # wait up to ~10s for uvicorn to accept connections
            if server.started:
                webbrowser.open(url)
                return
            time.sleep(0.1)

    start_watchdog(on_idle=lambda: setattr(server, "should_exit", True))
    threading.Thread(target=_open_when_ready, name="open-browser", daemon=True).start()

    print(f"RedactPDF running at {url}  -  close the browser tab to stop.")
    server.run()


if __name__ == "__main__":
    main()
