from __future__ import annotations

import threading
import time
from collections.abc import Callable


class Heartbeat:
    """Shared liveness state between the ``/api/heartbeat`` endpoint and the
    desktop launcher's watchdog.

    Inert unless a watchdog is running (i.e. the app was started via
    ``launch.py``): the endpoint only records a timestamp, which nothing reads
    under a plain ``uvicorn`` (dev / reverse-proxy production) run.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last = time.monotonic()
        self._count = 0
        self._closing = False

    def touch(self) -> None:
        with self._lock:
            self._last = time.monotonic()
            self._count += 1

    def request_close(self) -> None:
        with self._lock:
            self._closing = True

    def snapshot(self) -> tuple[int, float, bool]:
        with self._lock:
            return self._count, time.monotonic() - self._last, self._closing


# Module-level singleton shared by the API and the launcher.
heartbeat = Heartbeat()


def start_watchdog(
    *,
    on_idle: Callable[[], None],
    timeout: float = 30.0,
    startup_grace: float = 60.0,
    poll: float = 1.0,
) -> threading.Thread:
    """Run a daemon thread that calls ``on_idle`` exactly once when the UI is gone:

    - immediately if the page asked to close (``sendBeacon`` on tab close), or
    - after ``timeout`` seconds without a heartbeat once beats have started, or
    - after ``startup_grace`` seconds if the first heartbeat never arrives
      (browser failed to open) -- this avoids leaving a zombie server.

    The thread stops itself after firing.
    """

    def _run() -> None:
        started = time.monotonic()
        while True:
            time.sleep(poll)
            count, since, closing = heartbeat.snapshot()
            if closing:
                on_idle()
                return
            if count == 0:
                if time.monotonic() - started > startup_grace:
                    on_idle()
                    return
                continue
            if since > timeout:
                on_idle()
                return

    thread = threading.Thread(target=_run, name="heartbeat-watchdog", daemon=True)
    thread.start()
    return thread
