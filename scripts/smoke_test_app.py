#!/usr/bin/env python3
"""End-to-end smoke test for the RedactPDF desktop app.

Starts the app, drives the real HTTP API through it, and checks the output PDFs,
then verifies it shuts itself down. Works against the frozen executable or the
source launcher, on Linux and Windows.

    python scripts/smoke_test_app.py                 # dist/redactpdf[.exe]
    python scripts/smoke_test_app.py --source        # python launch.py
    python scripts/smoke_test_app.py --exe path/to/redactpdf.exe

Exits non-zero if any check fails. Needs the dev extra (httpx, pypdf) and the
generated test fixtures, so run it from a checkout.

What this cannot cover, and a human must still check on Windows: SmartScreen and
antivirus behaviour, and whether a double-click from Explorer really opens the
browser -- only the console-less start it relies on is checked here. See
docs/WINDOWS_BUILD.md.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "generated"

BASE_OPTIONS = {
    "image_mode": "pixels",
    "apply_graphics": True,
    "sanitize_metadata": True,
    "remove_annotations": True,
    "remove_attachments": True,
}

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}{'  -- ' + detail if detail else ''}", flush=True)
    if not ok:
        _failures.append(label)
    return ok


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def default_exe() -> Path:
    name = "redactpdf.exe" if sys.platform == "win32" else "redactpdf"
    return ROOT / "dist" / name


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def redact(client: httpx.Client, fixture: str, payload: dict) -> httpx.Response:
    pdf = (FIXTURES / fixture).read_bytes()
    return client.post(
        "/api/redact/apply",
        files={"file": (fixture, pdf, "application/pdf")},
        data={"payload": json.dumps(payload)},
        timeout=60.0,
    )


def wait_until_up(client: httpx.Client, proc: subprocess.Popen, timeout: float) -> bool:
    """Frozen one-file builds extract themselves first, so allow a slow start."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            if client.get("/api/health", timeout=2.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    return False


def run_checks(client: httpx.Client) -> None:
    # --- the UI is served from the app itself (bundled copy when frozen)
    resp = client.get("/")
    ok = check(
        "UI served at /",
        resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""),
        f"http={resp.status_code}",
    )
    if ok:
        # index.html references a hashed bundle; fetching it proves the whole
        # static tree shipped, not just the entry page.
        asset = ""
        for chunk in resp.text.split('src="')[1:]:
            candidate = chunk.split('"')[0]
            if candidate.endswith(".js"):
                asset = candidate
                break
        if asset:
            a = client.get(asset)
            check(
                f"JS bundle served ({asset})",
                a.status_code == 200 and len(a.content) > 10_000,
                f"http={a.status_code} bytes={len(a.content)}",
            )
        else:
            check("JS bundle referenced by index.html", False, "no .js src found")

    # --- both router prefixes stay reachable behind the static mount
    for path in ("/api/health", "/health"):
        r = client.get(path)
        check(
            f"API reachable at {path}",
            r.status_code == 200 and r.json().get("status") == "ok",
            f"http={r.status_code}",
        )

    check("heartbeat accepted", client.post("/api/heartbeat").status_code == 204)

    # --- exact search: the core redaction path
    r = redact(
        client,
        "001_secret_text.pdf",
        {
            "rects": [],
            "searches": [
                {
                    "query": "SECRET_ABC123",
                    "options": {
                        "case_sensitive": False,
                        "whole_word": True,
                        "ignore_accents": False,
                    },
                    "scope": {"pages": None},
                }
            ],
            "regexes": [],
            "presets": None,
            "options": BASE_OPTIONS,
            "audit": None,
        },
    )
    if check("search redaction returns a PDF", r.status_code == 200, f"http={r.status_code}"):
        check(
            "search: audit passed",
            r.headers.get("x-redaction-audit-status") == "pass",
            r.headers.get("x-redaction-audit-status", "?"),
        )
        check("search: secret removed from output", "SECRET_ABC123" not in pdf_text(r.content))

    # --- presets: exercises the lazily-imported phonenumbers region metadata,
    # the classic thing a bundle silently loses.
    r = redact(
        client,
        "002_email_phone_one_line.pdf",
        {
            "rects": [],
            "searches": [],
            "regexes": [],
            "presets": {"presets": ["email", "phone"], "scope": {"pages": None}},
            "options": BASE_OPTIONS,
            "audit": None,
        },
    )
    if check("email+phone presets return a PDF", r.status_code == 200, f"http={r.status_code}"):
        text = pdf_text(r.content)
        check("presets: audit passed", r.headers.get("x-redaction-audit-status") == "pass")
        check(
            "presets: phonenumbers metadata bundled",
            int(r.headers.get("x-redaction-presets-occurrences", "0")) >= 2,
            f"occurrences={r.headers.get('x-redaction-presets-occurrences')}",
        )
        check("presets: email removed", "@example.com" not in text)

    # --- credit card: the Luhn post-filter must keep the invalid PAN, which is
    # what distinguishes a working filter from a regex that matches everything.
    r = redact(
        client,
        "008_credit_card_luhn.pdf",
        {
            "rects": [],
            "searches": [],
            "regexes": [],
            "presets": {"presets": ["credit_card"], "scope": {"pages": None}},
            "options": BASE_OPTIONS,
            "audit": None,
        },
    )
    if check("credit_card preset returns a PDF", r.status_code == 200, f"http={r.status_code}"):
        text = pdf_text(r.content)
        check("credit_card: valid PAN redacted", "4111 1111 1111 1111" not in text)
        check("credit_card: Luhn-invalid PAN preserved", "4111 1111 1111 1112" in text)

    # --- multiline regex: the geometric engine, PyMuPDF-heavy
    r = redact(
        client,
        "003_phone_two_lines.pdf",
        {
            "rects": [],
            "searches": [],
            "regexes": [
                {
                    "patterns": [r"0[1-9](?:[ .-]?[0-9]{2}){4}"],
                    "case_sensitive": False,
                    "multiline": True,
                    "ignore_accents": False,
                    "scope": {"pages": None},
                }
            ],
            "presets": None,
            "options": BASE_OPTIONS,
            "audit": None,
        },
    )
    if check("multiline regex returns a PDF", r.status_code == 200, f"http={r.status_code}"):
        check(
            "multiline: matched across the line break",
            int(r.headers.get("x-redaction-regex-occurrences", "0")) >= 1,
            f"occurrences={r.headers.get('x-redaction-regex-occurrences')}",
        )


def check_no_stdio_start(cmd: list[str], env: dict, timeout: float) -> None:
    """Start the app the way Explorer does: with no standard streams at all.

    A windowed build (console=False) started from a double-click has sys.stdout
    and sys.stderr set to None, and that is a genuinely different path -- uvicorn's
    default log config asks sys.stdout.isatty() which colours to use and used to
    crash there, silently, before the server started. Windows only: console=False
    has no effect elsewhere, and STARTF_USESTDHANDLES with NULL handles is what
    reproduces it. Inheriting a terminal's streams does not.
    """
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESTDHANDLES  # hStd* stay None -> NULL

    port = free_port()
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env={**env, "REDACT_PORT": str(port)},
        startupinfo=startupinfo,
    )
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}")
    try:
        started = wait_until_up(client, proc, timeout)
        check("starts with no console (double-click path)", started, f"exit={proc.returncode}")
        if started:
            client.post("/api/heartbeat/close")
    finally:
        client.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, help="executable to test (default: dist/redactpdf)")
    parser.add_argument(
        "--source",
        action="store_true",
        help="test `python launch.py` from this checkout instead of a built executable",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=60.0,
        help="seconds to wait for the app to answer (default: 60)",
    )
    args = parser.parse_args()

    if not FIXTURES.is_dir():
        print(f"error: fixtures not found at {FIXTURES}; run this from a checkout", file=sys.stderr)
        return 2

    if args.source:
        cmd = [sys.executable, str(ROOT / "launch.py")]
        label = "source launcher (python launch.py)"
    else:
        exe = args.exe or default_exe()
        if not exe.is_file():
            print(f"error: executable not found: {exe}", file=sys.stderr)
            print("build it first:  python scripts/build_app.py", file=sys.stderr)
            return 2
        cmd = [str(exe)]
        label = f"executable ({exe.name})"

    port = free_port()
    env = {
        **os.environ,
        "REDACT_PORT": str(port),
        # Otherwise every run would pop a browser tab open on the tester's desktop.
        "REDACT_NO_BROWSER": "1",
    }

    print(f"Smoke test: {label}")
    print(f"  port {port}, startup timeout {args.startup_timeout:.0f}s\n")

    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env)
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}")
    started = time.monotonic()

    try:
        if not wait_until_up(client, proc, args.startup_timeout):
            if proc.poll() is not None:
                print(f"  [FAIL] app exited during startup (code {proc.returncode})")
            else:
                print(f"  [FAIL] app did not answer within {args.startup_timeout:.0f}s")
            return 1
        check("app started", True, f"{time.monotonic() - started:.1f}s")

        run_checks(client)

        # --- shutdown: the tab-close beacon must actually stop the process
        client.post("/api/heartbeat/close")
        stopped = False
        for _ in range(150):
            if proc.poll() is not None:
                stopped = True
                break
            time.sleep(0.1)
        check("close beacon stops the app", stopped, f"exit code {proc.returncode}")

        if sys.platform == "win32":
            check_no_stdio_start(cmd, env, args.startup_timeout)
    finally:
        client.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)

    print()
    if _failures:
        print(f"FAILED ({len(_failures)}): " + ", ".join(_failures))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
