# Windows Build

How to produce and validate the Windows executable, and what shipping it
unsigned means for users.

The hard parts of a Windows PyInstaller build are not the compilation, they are
the failure modes that produce no output at all — a double-click that appears to
do nothing. Read the whole file before changing anything here, and change code
only in response to an actual failure: the codebase is OS-agnostic by design, so
a pre-emptive rewrite is far more likely to break Linux than to fix Windows.

## Status

Verified on Windows 11 (23 August 2026, Python 3.11.9, Node 22.23.2,
PyInstaller 6.22.2):

- `pytest` (47 tests) and `ruff check .` pass in `backend/`.
- The smoke test passes all 20 checks (one is Windows-only) against both
  `python launch.py` and `dist\redactpdf.exe`.
- The executable is ~37 MB, answers in ~1 s, serves the bundled UI, and both of
  its processes exit on the close beacon.
- Manual checks 1, 2, 5 and 6 below pass. Check 3, SmartScreen, was reproduced
  with a hand-attached Mark-of-the-Web: the prompt appears and *Run anyway*
  starts the app — see "Shipping unsigned" for what that means for releases.
  Defender, with real-time protection on, does not flag the file on the build
  machine.

Two things cannot be answered without publishing a release: SmartScreen's
reputation verdict on a genuinely downloaded file, and antivirus behaviour on a
machine other than the one that built it. Both are cloud- and
machine-dependent, so the first release is itself the test.

macOS is deliberately not built: no Mac is available to the project. Should that
change, the `console=False` trap documented below applies there too — a windowed
macOS build has the same missing standard streams.

## Setup

Prerequisites: Python 3.11+, Node 20+, git. What actually worked on a Windows 11
box with none of the three installed, per-user and without administrator rights
except where noted:

```powershell
winget install --id Python.Python.3.11 --scope user --silent `
  --accept-package-agreements --accept-source-agreements

# winget's Node package is a machine-scope MSI and prompts for elevation; the
# official zip does not. Any 20+ works, 22.23.2 is what was used here.
$programs = "$env:LOCALAPPDATA\Programs"
Invoke-WebRequest https://nodejs.org/dist/v22.23.2/node-v22.23.2-win-x64.zip -OutFile node.zip
Expand-Archive node.zip $programs
Rename-Item "$programs\node-v22.23.2-win-x64" nodejs
[Environment]::SetEnvironmentVariable(
  "PATH", [Environment]::GetEnvironmentVariable("PATH", "User") + ";$programs\nodejs", "User")

winget install --id Git.Git --scope user --silent   # this one does ask for elevation
```

Then, in a **new** shell so those PATH changes are visible:

```powershell
git clone <repo-url>
cd RedactPDF

py -m venv .venv        # `python -m venv .venv` if the py launcher is missing
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
close-beacon shutdown. On Windows it then starts the app once more with no
standard streams at all, which is the double-click path. It is the objective
part of the validation.

## What the smoke test cannot check

These need a human looking at a screen, which is why the first Windows build
was done on a real install rather than in CI.

1. **Double-click from Explorer.** Not from a terminal — that is a different
   working directory and a different console situation, and it is how the actual
   user will launch it. The browser should open on the app. The console-less
   start it relies on is now covered by the smoke test; the browser actually
   opening is not.
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
   A locally built file carries no such mark, so nothing happens on a plain
   double-click. Attaching the mark by hand gives the same prompt without a round
   trip through a server:
   ```powershell
   Set-Content .\dist\redactpdf.exe -Stream Zone.Identifier -Value "[ZoneTransfer]","ZoneId=3"
   # double-click it from Explorer, then:
   Unblock-File .\dist\redactpdf.exe          # removes the mark again
   ```
   The prompt is driven by that mark, but the reputation verdict behind it is a
   cloud lookup on the file's hash and signature, so only a real download of a
   real release tells you exactly what users will see.
4. **Antivirus.** One-file PyInstaller executables are a frequent heuristic
   false positive. Check Defender does not quarantine it, ideally on a machine
   other than the build one.
5. **Closing the tab stops the process.** Watch Task Manager: both
   `redactpdf.exe` entries (bootloader plus child) must disappear within ~30 s.
   No orphan process may survive, or repeated launches will pile up.
6. **A path containing spaces or non-ASCII characters**, e.g.
   `C:\Users\<name>\Mes Documents\`. Non-obvious paths are where quoting bugs
   surface.

## Shipping unsigned: what every user will see

Confirmed on 23 August 2026 with a hand-attached Mark-of-the-Web: the prompt
appears, and *More info → Run anyway* starts the app normally.

This is not a first-user-only annoyance. SmartScreen's reputation is keyed on the
exact file hash for an unsigned binary, so it never really accumulates — and even
if it did, every new release is a new hash and starts from zero. Assume **every
user, on every version**, gets "Windows protected your PC" and has to click
through it. Chromium browsers may additionally warn at download time that the
file "isn't commonly downloaded", for the same underlying reason. Shipping inside
a ZIP changes nothing: Explorer propagates the mark to the extracted files.

Three ways out, in increasing cost:

- **Document it.** Tell users what they will see and what to click, in the README
  and in the release notes. Free, honest, and what most unsigned open-source
  tools do. This is the current choice.
- **A code-signing certificate** (OV or EV). Reputation then attaches to the
  certificate rather than to each file, so it carries across releases: an EV
  certificate is trusted immediately, an OV one still needs to build reputation
  up. Since mid-2023 the private key must live on a hardware token or an HSM,
  which is most of the practical friction.
- **A managed signing service**, such as Azure Trusted Signing, which is
  substantially cheaper than a traditional certificate but has its own identity
  verification requirements — check current eligibility before counting on it.

Ready to paste into release notes, and already in the README:

> Windows will show "Windows protected your PC" the first time you run the app,
> because the executable is not signed with a paid code-signing certificate.
> Click **More info → Run anyway**.

## Likely problems, and what to do

**The app dies instantly when it has no console, but runs fine from a terminal.**
A windowed build has `sys.stdout` and `sys.stderr` set to `None`, so anything
touching them without checking raises before the server starts -- and there is
nowhere left to print. uvicorn's default log config does exactly that, calling
`sys.stdout.isatty()` to choose colours, which is why `launch.py` passes
`log_config=None` when the streams are missing. Both terminal runs and redirected
streams hide this; the smoke test's "starts with no console" check is what
catches it.

**Fixture hashes differ, on Windows only.** `test_fixtures.py` asserts exact
bytes, and a checkout with `core.autocrlf=true` used to rewrite the generated
PDFs' LFs -- they contain no NUL byte, so git classified them as text.
`.gitattributes` now marks `*.pdf` and `*.png` as binary; a clone made before
that needs the files restored (delete them, then `git checkout -- "*.pdf"`).

**Missing module at runtime, works fine in tests.** The classic PyInstaller
failure: something imported by string is invisible to static analysis. The spec
already collects `uvicorn` and `phonenumbers` submodules for this reason. Add
the offending package the same way in `packaging/redactpdf.spec` — do not
disable the collection that is already there.

**The UI does not load but the API answers.** The bundled `frontend/dist` was
not found. It is embedded as data and resolved by `backend/redactpdf/paths.py`; keep
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
  should not need to change anything under `backend/redactpdf/` except, at most,
  `paths.py`.
- Keep `launch.py` working on Linux: it is the same entry point for both the
  frozen app and people running from source. Guard anything Windows-specific
  with `sys.platform == "win32"`.
- Do not commit `dist/` or `build/`.

## Record of the first Windows build (23 August 2026)

Windows 11 Home 22631, Python 3.11.9, Node 22.23.2, npm 10.9.8, PyInstaller
6.22.2. Result: `dist\redactpdf.exe`, 36.7 MB, starts in ~1 s, all 20 smoke
checks green against both the source launcher and the frozen binary, `pytest`
47/47 and `ruff check .` clean. Nothing under `backend/redactpdf/` changed, `paths.py`
included, and neither CI workflow is affected.

Three things were broken, in the order they surfaced.

**1. Every generated fixture was corrupt in the working tree.**
`test_fixtures.py` was the only failure on the first `pytest` run. The committed
blobs were fine; the checkout was not. `.gitattributes` said `* text=auto`, git's
global `core.autocrlf` was `true`, and the ReportLab fixtures contain no NUL byte
— so git classified all twelve as text and rewrote their LFs to CRLF on checkout
(001: 1562 bytes in the blob, 1630 in the tree, exactly 68 injected CRs).
`git status` stayed clean the whole time, because the conversion round-trips.
Fix: mark `*.pdf` and `*.png` as `binary` in `.gitattributes`, then delete the
files and `git checkout --` them. `docs/demo-invoice.pdf` and
`frontend/public/logo.png` were never affected: they do contain NUL bytes, so
git had already detected them as binary.

**2. `build_app.py` reported failure on a successful build.**
It looked for `dist/redactpdf`, and PyInstaller appends `.exe` on Windows. Fixed
the same way `smoke_test_app.py` already did it, in `default_exe()`.

**3. The frozen app could not start without a console — the double-click path.**
The one that mattered. From the `MessageBoxW` dialog `launch.py` puts up for
exactly this situation:

```
File "uvicorn\logging.py", line 42, in __init__
AttributeError: 'NoneType' object has no attribute 'isatty'
...
ValueError: Unable to configure formatter 'default'
```

A windowed build (`console=False`) has `sys.stdout` and `sys.stderr` set to
`None`, and uvicorn's default log config calls `sys.stdout.isatty()` to decide
whether to colour its output. That raised inside `uvicorn.Config(...)`, before a
server object even existed, so a double-click died instantly with nothing but
that dialog. Fix: `launch.py` passes `log_config=None` when the streams are
missing; runs that do have streams are unchanged, on any OS.

What made it slippery is that it only reproduces when the process genuinely has
no standard handles. Launching the exe from PowerShell works — PowerShell hands
its own handles to the child, and returns immediately rather than waiting, since
a GUI-subsystem app does not block the prompt — and so does any run with stdout
redirected to a file. Both hide the bug. `scripts/smoke_test_app.py` now creates
the condition deliberately on Windows, with `STARTF_USESTDHANDLES` and NULL
handles: the "starts with no console (double-click path)" check.

Manual checks: 1 (no-console start, now automated; the browser really opening
still wants a human), 2 (the dialog appears, titled "RedactPDF", and blocks the
process until dismissed), 5 (both processes exit on the close beacon) and 6 (a
path with spaces and accents) pass. Defender, real-time protection on, never
flagged the executable across a dozen builds and runs on the build machine.

Check 3, SmartScreen, was run with a hand-attached Mark-of-the-Web rather than a
real download: the prompt appears as expected and *Run anyway* starts the app.
What a real download would add is the reputation verdict itself, which is a cloud
lookup on the released file — see "Shipping unsigned" above. Check 4, antivirus,
is only meaningful on a machine other than the one that built the file, so it
stays open too.
