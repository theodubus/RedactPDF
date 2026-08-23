# Windows Build Playbook

Everything needed to produce and validate the Windows executable. The Linux
build already works; this is the second target.

**Read this whole file before starting.** The tricky parts of a Windows
PyInstaller build are not the compilation, they are the failure modes that
produce no output at all.

## State of play

Done and verified on Linux:

- `python launch.py` runs the app as one process (UI + API, same origin), opens
  the browser, stops a few seconds after the tab closes.
- `python scripts/build_app.py` freezes it into a single ~44 MB executable.
- `python scripts/smoke_test_app.py` drives 19 checks against the built app and
  passes on both the source launcher and the frozen binary.

Not done: the Windows executable has never been built or run. That is this task.

The code is expected to be OS-agnostic already, so **start by simply building
it**. Do not pre-emptively rewrite things. Change code only in response to an
actual failure, and prefer the smallest fix.

## Setup

Prerequisites: Python 3.11+ (from python.org, "Add python.exe to PATH" ticked),
Node 20+, git.

```powershell
git clone <repo-url>
cd RedactPDF
git checkout distribution

py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".\backend[dev,packaging]"

cd frontend
npm ci
cd ..
```

Sanity check before packaging anything — this must pass first:

```powershell
cd backend
pytest
ruff check .
cd ..
python scripts\smoke_test_app.py --source
```

If the source launcher fails on Windows, fix that before touching PyInstaller;
a packaging problem is much harder to diagnose on top of a runtime one.

## Build and verify

```powershell
python scripts\build_app.py
python scripts\smoke_test_app.py
```

The build writes `dist\redactpdf.exe` (the spec's `name` has no extension;
PyInstaller adds `.exe` on Windows). `dist\` and `build\` are gitignored.

The smoke test starts the app on a fixed port with the browser suppressed, then
checks the bundled UI, both API prefixes, an exact-search redaction, the
email/phone presets, the credit-card Luhn filter, a multiline regex, and the
close-beacon shutdown. It is the objective part of the validation.

## What the smoke test cannot check

These need a human looking at a screen. They are the reason this work is being
done on a real Windows install rather than in CI.

1. **Double-click from Explorer.** Not from a terminal — that is a different
   working directory and a different console situation, and it is how the actual
   user will launch it. The browser should open on the app.
2. **The app is silent on failure.** The release build is windowed
   (`console=False`), so a crash has nowhere to print. `launch.py` routes fatal
   errors to a `MessageBoxW` dialog for exactly this reason. Verify that path
   works, or a future crash will be invisible:
   ```powershell
   $env:REDACT_PORT="notanumber"; .\dist\redactpdf.exe
   ```
   An error dialog must appear. Then `Remove-Item Env:REDACT_PORT`.
3. **SmartScreen.** An unsigned executable downloaded through a browser carries
   the Mark-of-the-Web and triggers "Windows protected your PC" on first run.
   Expected without a code-signing certificate. Confirm that
   *More info → Run anyway* works, and note it for the release instructions.
   Testing a file built locally may not reproduce this: to see what a real user
   sees, upload it somewhere and download it again.
4. **Antivirus.** One-file PyInstaller executables are a frequent heuristic
   false positive. Check Defender does not quarantine it, ideally on a machine
   other than the build one.
5. **Closing the tab stops the process.** Watch Task Manager: both
   `redactpdf.exe` entries (bootloader plus child) must disappear within ~30 s.
   No orphan process may survive, or repeated launches will pile up.
6. **A path containing spaces or non-ASCII characters**, e.g.
   `C:\Users\<name>\Mes Documents\`. Non-obvious paths are where quoting bugs
   surface.

## Likely problems, and what to do

**Missing module at runtime, works fine in tests.** The classic PyInstaller
failure: something imported by string is invisible to static analysis. The spec
already collects `uvicorn` and `phonenumbers` submodules for this reason. Add
the offending package the same way in `packaging/redactpdf.spec` — do not
disable the collection that is already there.

**The UI does not load but the API answers.** The bundled `frontend/dist` was
not found. It is embedded as data and resolved by `backend/app/paths.py`; keep
the bundle-relative layout and never resolve it from `__file__`.

**Nothing happens at all on launch.** Run it from PowerShell rather than by
double-click to see whether anything is printed, and check item 2 above. If the
error dialog does not appear either, the failure is before `launch.py` runs —
build with `console=True` in the spec temporarily to see the traceback, then put
it back.

**Defender quarantines the file.** Options, in order of preference: switch the
spec from one-file to one-directory (much lower false-positive rate, but ships a
folder instead of a single file), get a code-signing certificate, or document an
exclusion. This is a product decision — report it rather than deciding alone.

**Firewall prompt on first run.** The server binds `127.0.0.1` only, so a prompt
should not appear; if it does, declining it is harmless since nothing needs to
be reachable from outside the machine.

## Do not break

- Redaction rectangles are always computed from the original PDF, and no path
  returns a PDF without passing the post-redaction audit. Packaging must not
  touch that pipeline. See [CLAUDE.md](../CLAUDE.md).
- `pytest` and `ruff check .` in `backend/` must stay green. The Windows work
  should not need to change anything under `backend/app/` except, at most,
  `paths.py`.
- Keep `launch.py` working on Linux: it is the same entry point for both the
  frozen app and people running from source. Guard anything Windows-specific
  with `sys.platform == "win32"`.
- Do not commit `dist/` or `build/`.

## When done

Report: what was built, what the smoke test said, the result of each manual
check above, and any code that had to change and why. The branch is
`distribution`; the review, push and PR happen from the other machine.
