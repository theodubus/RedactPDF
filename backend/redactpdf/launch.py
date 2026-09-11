"""Lanceur applicatif de RedactPDF.

Démarre le backend sur un port local libre, sert l'UI construite en
same-origin, ouvre le navigateur, et s'arrête quelques secondes après la
fermeture de l'onglet (watchdog de heartbeat).

Deux façons de l'appeler :

    redactpdf              point d'entrée console installé par le paquet
    python launch.py       depuis un dépôt source, via le lanceur racine

Prérequis en dépôt source -- construire l'UI une fois pour que le backend ait
quelque chose à servir :

    cd frontend && npm run build

Variables d'environnement (les deux existent pour le smoke test automatisé, et
servent quand on veut une adresse fixe) :

    REDACT_PORT=8765     utiliser ce port au lieu d'en choisir un libre
    REDACT_NO_BROWSER=1  ne pas ouvrir de navigateur
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from typing import NoReturn

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from redactpdf.heartbeat import start_watchdog
from redactpdf.main import app
from redactpdf.paths import frontend_dist, is_frozen, is_source_checkout


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
    ui = frontend_dist()
    if not (ui / "index.html").is_file():
        # Trois causes possibles selon la disposition, et l'utilisateur ne peut
        # agir que sur l'une d'elles. On nomme le chemin cherché dans tous les
        # cas : c'est la seule information qui distingue les trois.
        if is_frozen():
            reason = (
                "Frontend build missing from this bundle -- rebuild it with "
                "scripts/build_app.py"
            )
        elif not is_source_checkout():
            reason = (
                "Frontend build missing from this installation -- the wheel was built "
                "without staging the UI (scripts/build_package.py does it)."
            )
        else:
            reason = (
                "Frontend build not found.\nBuild it once:  cd frontend && npm run build"
            )
        _fatal(f"{reason}\n\nLooked for index.html in: {ui}")

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


def run() -> None:
    """Point d'entrée console (`redactpdf`) et cible du lanceur racine.

    Enveloppe `main()` dans un attrape-tout : une construction fenêtrée
    (`console=False`) n'a ni stdout ni stderr, et un plantage y serait
    totalement silencieux.
    """
    try:
        main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001  (last resort: a silent crash is the worst outcome)
        _fatal("RedactPDF failed to start.\n\n" + traceback.format_exc())
