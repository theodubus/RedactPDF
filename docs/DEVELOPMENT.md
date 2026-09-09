# Development

Two halves: a FastAPI + PyMuPDF backend that does every bit of redaction work,
and a React/Vite SPA that renders the PDF with pdf.js and builds the rule
payload. They talk over exactly one endpoint, `POST /redact/apply`.

- [Requirements](#requirements)
- [Setup](#setup)
- [Running it](#running-it)
- [Tests](#tests)
- [Building a distribution](#building-a-distribution)
- [CI](#ci)
- [Serving it to more than one user](#serving-it-to-more-than-one-user)

---

## Requirements

- **Python 3.10 or newer**. CI runs 3.11.
- **Node.js 20 or newer**, for the frontend dev server and build.
- Linux, macOS or Windows. The commands below assume a POSIX shell; on Windows
  activate the venv with `.\.venv\Scripts\Activate.ps1`. The test suite and the
  desktop launcher are exercised on Linux and on Windows.

---

## Setup

```bash
git clone https://github.com/theodubus/RedactPDF.git
cd RedactPDF
```

**Backend.** `.[dev]` pulls the runtime dependencies (FastAPI, PyMuPDF,
`phonenumbers`, `regex`) plus the tooling (pytest, ruff, reportlab, httpx,
pypdf).

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**Frontend.**

```bash
cd ../frontend
npm ci
```

---

## Running it

### One process, the way a user runs it

```bash
cd frontend && npm run build && cd ..
python launch.py
```

`launch.py` picks a free local port, serves the UI and the API from a single
process (same origin, so no CORS and no proxy), opens your browser, and shuts
the server down a few seconds after you close the tab.

**`git pull` does not update the interface.** `frontend/dist` is a build
artefact and is git-ignored, so a pull changes the sources under `frontend/src`
and leaves the bundle `launch.py` actually serves untouched. Run `npm run build`
after every pull that touched the frontend, or you will be testing the previous
version of the UI against the new backend and wondering why nothing changed.
This has cost a full round trip at least once.

`REDACT_PORT` and `REDACT_NO_BROWSER` exist so the smoke test can drive the app
deterministically; they work by hand too.

### Two processes, with hot reload

**Terminal 1, backend:**

```bash
cd backend
source .venv/bin/activate
uvicorn redactpdf.main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2, frontend:**

```bash
cd frontend
npm run dev
```

Open the URL Vite prints (`http://localhost:5173` by default). The dev server
proxies `/api/*` to `127.0.0.1:8000`, configured in
[frontend/vite.config.ts](../frontend/vite.config.ts), so CORS never comes up in
development.

---

## Tests

```bash
cd backend
source .venv/bin/activate
ruff check .          # line-length 100, rules E,F,I,UP,B
mypy                  # --strict over redactpdf/, configured in pyproject.toml
pytest                # markers: unit, integration, e2e, slow
```

`mypy` runs strict over the package and not over `tests/`, where the only
findings are unparameterised `dict`s. Two dependencies have no published types:
PyMuPDF is waived by an override, so anything coming from it arrives as `Any`
and it is on us to annotate wherever we rely on its shape; `regex` gets real
stubs (`types-regex`, pinned to the same version) rather than a waiver, because
that is what makes the ReDoS guard's boundary checkable. It caught a signature
declaring `re.Pattern` on a path that must stay on the `regex` engine.

```bash
cd frontend
npm run lint          # zero warnings tolerated, CI enforces it
npm test              # vitest
npm run build
```

### Tests that need Tesseract

`tests/test_ocr_proposals.py` skips itself when no system Tesseract is installed,
which is the case in CI and for most users, since the app never bundles one. To
run them locally on Debian or Ubuntu:

```bash
apt install tesseract-ocr tesseract-ocr-fra
```

Skipping is the honest default here: the feature disables itself the same way in
the app, so a machine without Tesseract exercises the disabled path, which is
also worth having covered.

### The phone preview is checked against the backend, not trusted

`utils/phonePreview.ts` mirrors the backend's `_phone_post_filter`, and a
highlight reads as a promise: highlighting a number the backend will not remove
produces a successful export with the data still in it, and the audit cannot
catch that because it re-runs the same detector.

Two languages cannot be tested in one process, so the contract is a committed
corpus that **both suites verify**. `phoneParity.fixture.json` is generated from
the backend; `backend/tests/test_phone_parity.py` checks it still matches
`_phone_post_filter`, and `phonePreview.test.ts` checks the browser mirror agrees
with it. A drift on either side fails one of the two. When the filter changes,
regenerate the corpus from the backend rather than editing it by hand.

### PDF fixtures are a contract

`backend/tests/fixtures/generated/*.pdf` are deterministic ReportLab output
whose exact bytes are asserted by `test_fixtures.py`, SHA-256 against a fresh
regeneration. Each one targets a specific trap: whole-word `CAT` versus `CATCH`,
a phone split across lines versus across columns, Luhn-invalid cards, accents,
metadata plus annotation, rotated margin text, a pattern that backtracks.

Do not hand-edit them. If you change the generator, regenerate and commit all of
them in the same change, **from the repository root**:

```bash
python -m backend.tests.fixtures.generate_fixtures
```

Prefer extending the corpus over inventing a PDF inside a test. Each fixture and
the trap it covers is listed in
[backend/tests/fixtures/README.md](../backend/tests/fixtures/README.md).

### Property-based tests

`tests/test_properties.py` runs invariants over generated input rather than
chosen examples, with `hypothesis`. Two of them are load-bearing:

- **`_fold_keep_len` preserves length.** Text is matched character by character
  against glyph boxes extracted from the page, so an offset of one does not
  redact *more*, it redacts *elsewhere*: the target stays visible and a
  neighbour is destroyed. The naive implementation (NFKD then drop combining
  marks) breaks on the first ligature, and `hypothesis` finds one in seconds.
- **`build_whole_word_pattern` holds its boundaries.** It must find its token
  standing alone and inside punctuation, and refuse it glued to a word
  character. That is what makes the whole-word default safe rather than leaky.

Output is read back with a library that did not write it: `pypdf` for text,
PyMuPDF only for structural inspection (metadata, XMP, annotations,
attachments). See [backend/tests/utils_pdf.py](../backend/tests/utils_pdf.py).

---

## Building a distribution

### Wheel and sdist

```bash
pip install -e "backend[dev,wheel]"
python scripts/build_package.py                 # npm build + stage + build -> backend/dist/
python scripts/build_package.py --skip-frontend # reuse the existing frontend/dist
python scripts/smoke_test_app.py --exe <venv>/bin/redactpdf
```

setuptools cannot reach above the package root, so `frontend/dist` and the root
`LICENSE.md` are **staged into** `backend/` by the build script before
`python -m build`. Both copies are git-ignored build artefacts.

### Standalone binary

```bash
pip install -e "backend[dev,packaging]"
python scripts/build_app.py                    # -> dist/redactpdf
python scripts/build_app.py --skip-frontend
python scripts/smoke_test_app.py               # end-to-end checks on the result
python scripts/smoke_test_app.py --source      # same checks against `python launch.py`
```

PyInstaller does not cross-compile: one build per target OS, and the Linux
binary requires a glibc at least as new as the build machine's. **Working on the
Windows build? Read [WINDOWS_BUILD.md](WINDOWS_BUILD.md) first**: it covers the
failure modes that produce no output at all, which is most of the difficulty.

### Release

A `v*` tag fires `release.yml`, which checks the tag matches `version` in
[backend/pyproject.toml](../backend/pyproject.toml), builds the binaries on
Linux and Windows gated on a frozen smoke test, builds and smoke-tests the
wheel, attests the provenance of every artifact, drafts a GitHub Release
carrying the binaries, the distributions and `SHA256SUMS.txt` (never publishing
it on its own), and publishes to PyPI through Trusted Publishing (OIDC, no
stored secret).

Checksums and attestations are the only trust story available without a paid
code-signing certificate. Do not drop either.

---

## CI

| Workflow | What it runs |
| --- | --- |
| `backend-ci` | `ruff check .` + `mypy` + `pytest` on Python 3.11 |
| `frontend-ci` | `npm run lint` (zero warnings) + `npm run build` on Node 20 |
| `smoke-ci` | two jobs: one drives `smoke_test_app.py --source`, the other builds the wheel, installs it into a clean venv and drives the installed console script |
| `release` | on a `v*` tag, see above |

`smoke-ci` covers what pytest cannot see: `launch.py`, `redactpdf/paths.py`,
same-origin serving of the built UI and the end-to-end API path, without paying
for a PyInstaller build on every push.

---

## Serving it to more than one user

RedactPDF is built for local, single-user usage. **Exposing the API to untrusted
networks or multiple users is unsafe out of the box**: no auth, no rate
limiting, no upload size cap. Regex execution *is* bounded, in the application,
because the main way to run this tool is a local binary with no reverse proxy in
front of it.

A typical hosted setup builds the frontend (`npm run build` produces a static
bundle in `frontend/dist`) and serves it from a reverse proxy that also proxies
`/api/*` to Uvicorn. Same-origin serving means no CORS.

Read [SECURITY.md → Production / Multi-user Deployment](SECURITY.md#production--multi-user-deployment)
first and put the recommended protections in the proxy or the container. They
are deliberately not implemented in the application.
