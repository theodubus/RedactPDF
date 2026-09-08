# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Backend (run from `backend/`, with `.venv` active — `pip install -e ".[dev]"`):

```bash
ruff check .                      # lint (line-length 100, rules E,F,I,UP,B)
mypy                              # --strict on redactpdf/ (config in pyproject)
pytest                            # full suite (testpaths=tests, pythonpath=.)
pytest tests/test_redact_apply.py::test_redact_apply_combines_search_and_presets_email
pytest -m unit                    # markers: unit, integration, e2e, slow
uvicorn redactpdf.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend (run from `frontend/`):

```bash
npm ci
npm run dev                       # Vite dev server on :5173, proxies /api/* -> :8000
npm run build                     # tsc -b && vite build -> frontend/dist
npm run lint                      # eslint, zero warnings tolerated (run by CI)
```

Desktop / single-process mode (from repo root, after `npm run build`):

```bash
python launch.py                  # free port + same-origin UI + heartbeat auto-shutdown
```

Python distributions — wheel + sdist (needs the `wheel` extra: `pip install -e "backend[dev,wheel]"`):

```bash
python scripts/build_package.py                 # npm build + stage + build -> backend/dist/
python scripts/build_package.py --skip-frontend # reuse the existing frontend/dist
python scripts/smoke_test_app.py --exe <venv>/bin/redactpdf   # check an installed wheel
```

Standalone build (needs the `packaging` extra: `pip install -e "backend[dev,packaging]"`):

```bash
python scripts/build_app.py                    # npm build + PyInstaller -> dist/redactpdf
python scripts/build_app.py --skip-frontend    # reuse the existing frontend/dist
python scripts/smoke_test_app.py               # end-to-end checks on the built app (one extra on Windows)
python scripts/smoke_test_app.py --source      # same checks against `python launch.py`
```

PyInstaller does not cross-compile — one build per target OS, and the Linux binary
requires a glibc at least as new as the build machine's. **Working on the Windows
build? Read [docs/WINDOWS_BUILD.md](docs/WINDOWS_BUILD.md) first** — it covers the
failure modes that produce no output at all, which is most of the difficulty.

Fixture regeneration (from **repo root**, not `backend/`):

```bash
python -m backend.tests.fixtures.generate_fixtures
```

CI: `backend-ci` runs `ruff check .` + `mypy` + `pytest` on Python 3.11; `frontend-ci` runs `npm run lint` (zero warnings) + `npm run build` on Node 20; `smoke-ci` has two jobs — one drives `scripts/smoke_test_app.py --source`, the other builds the wheel, installs it into a clean venv and drives the installed `redactpdf` console script. Between them they cover what pytest cannot see: `launch.py`, `redactpdf/paths.py`, same-origin serving of the built UI, and the end-to-end API path, without paying for a PyInstaller build. `release` fires on a `v*` tag: it checks the tag matches `version` in `backend/pyproject.toml`, builds the standalone binaries on Linux and Windows gated on the frozen `smoke_test_app.py`, builds and smoke-tests the wheel, attests the provenance of every artifact it produces (`actions/attest-build-provenance`, which needs `id-token: write` + `attestations: write` on the producing job), drafts a GitHub Release carrying the binaries, the distributions and a `SHA256SUMS.txt` — never publishing it on its own — and publishes the distributions to PyPI through Trusted Publishing (OIDC, environment `pypi`, no stored secret). The release notes tell readers how to check both: `sha256sum -c` for the bytes, `gh attestation verify` for the origin. That pair is the only trust story available without a paid code-signing certificate, so do not drop it.

## Architecture

Two halves: a FastAPI + PyMuPDF backend that does all redaction work, and a React/Vite SPA that renders the PDF with pdf.js and builds the rule payload. There is exactly one API call in the whole app: `POST /redact/apply` (multipart: `file` + a JSON `payload` string).

### Request flow: plan → apply → audit

[backend/redactpdf/pipeline.py](backend/redactpdf/pipeline.py) is the spine, and the ordering is a security invariant:

1. **`plan_redactions`** computes *all* rectangles (manual, search, regex, presets) from the **original** PDF bytes. Never re-derive rectangles from a partially-redacted document — a prior redaction would hide text a later rule needed to match. `test_redact_apply.py` has a regression test for this.
2. **`apply_plan`** runs redaction in up to two passes: full-page rects first in forced strict mode (`image_mode="remove"`, `apply_graphics=True`) regardless of what the user picked, then everything else in the user's mode. Sanitisation is deferred to the last pass so it runs once on the final document.
3. **`audit_plan`** re-runs every requested rule against the **output** PDF's extracted text. Any surviving match makes [main.py](backend/redactpdf/main.py) return HTTP 400 with a structured component report instead of the PDF. A successful export also carries the report base64'd in `X-Redaction-Audit-Report-B64` plus `X-Redaction-*-Occurrences` headers.

Never add a path that returns a PDF without passing the audit.

### Backend modules

- [redaction.py](backend/redactpdf/redaction.py) — the only place that touches PyMuPDF redaction primitives. `_tighten_rect_vertical` shrinks extracted line boxes so a rect doesn't eat the line below, and it runs **only** on rects flagged `from_horizontal_text`. For rotated text the height *is* the reading direction, so shrinking it cuts the first and last characters off the match; for a hand-drawn rectangle it would silently redact a smaller area than the user drew. The flag defaults to `False`, so a producer that says nothing gets its rect applied whole — over-redacting rather than under-redacting. Saves with `garbage=4` (required for metadata/image removal to be physical, not just unreferenced).
- [multiline_regex_engine.py](backend/redactpdf/multiline_regex_engine.py) — the real matching engine. Extracts words/lines/char boxes, carries each line's writing direction (`dir` from `rawdict`) so glyphs are ordered along the **reading** direction rather than left to right — on a quarter-turned line every glyph shares the same `x0`, and sorting by x yields the reverse of the reading order, which makes a partial-word match select the wrong glyphs. Maps regex spans back to geometry, and fuses lines only when they overlap horizontally enough (`min_x_overlap_ratio`), which is what prevents cross-column false fusions (fixture `009`). Accent folding (`_fold_keep_len`) is deliberately **length-preserving** so string indices stay valid for span→rect mapping — keep that property in any change here.
- [search.py](backend/redactpdf/search.py) — exact search. Fast path uses `page.search_for()`; `whole_word` or `ignore_accents` fall back to the regex engine with a generated pattern.
- [presets.py](backend/redactpdf/presets.py) — email / phone / credit_card. Regex candidates plus post-filters: Luhn for cards, `phonenumbers` validation for phones (default region from `REDACT_DEFAULT_REGION`, `FR`).
- [audit.py](backend/redactpdf/audit.py) — text-level audit primitives and `build_whole_word_pattern`, shared with `search.py` so search semantics and audit semantics cannot drift apart.
- [regex_guard.py](backend/redactpdf/regex_guard.py) — every user-supplied pattern runs through here, on the `regex` engine rather than `re`, under a time budget **shared by the whole request** (`REDACT_REGEX_TIMEOUT`, 10s). Two reasons the guard has that exact shape, both easy to undo by accident: `re` does not release the GIL while matching, so a watchdog thread could never observe a runaway pattern — the interruption must come from inside the engine; and patterns run line by line, so a per-call timeout would be multiplied by the number of lines. `RegexTimeout` subclasses `ValueError` so it lands on the existing 400 path. Nothing in the package may compile a user-supplied pattern with `re` — only `re.escape`, which builds a pattern string without matching, is allowed. `mypy --strict` now enforces this: `types-regex` is a dev dependency precisely so a signature cannot claim `re.Pattern` on a path that must stay on the `regex` engine, which is how a stale annotation sat on that boundary until it was checked.
- [sanitize.py](backend/redactpdf/sanitize.py) — metadata / annotations / widgets / attachments, on by default.
- [heartbeat.py](backend/redactpdf/heartbeat.py) — liveness singleton; inert unless `launch.py` started a watchdog thread.

### Packaging

[packaging/redactpdf.spec](packaging/redactpdf.spec) freezes `launch.py` into one executable. Three things there are load-bearing and easy to break: `phonenumbers` region metadata and uvicorn's protocol/loop implementations are both resolved by string at runtime, so they are pulled in with `collect_submodules`; and `frontend/dist` is embedded as data under that same relative name. Anything else resolved dynamically needs the same treatment, and the symptom is always a runtime `ModuleNotFoundError` in the frozen binary only — never in the test suite.

Because of that embedding, **no module may locate the UI from `__file__`**: once frozen, the code lives in a temporary extraction tree, not the repo. [redactpdf/paths.py](backend/redactpdf/paths.py) is the single place that knows the layouts (`frontend_dist()`, `is_frozen()`, `is_source_checkout()`); `main.py` and `launch.py` go through it.

There are **three** layouts, not two, and `frontend_dist()` tries them in this order: PyInstaller bundle (`sys._MEIPASS/frontend/dist`), source checkout (`<repo>/frontend/dist`), installed wheel (`redactpdf/_frontend`). The source checkout is tried before the package copy on purpose — on a machine that has already built a wheel, a stale `_frontend` must never shadow a freshly rebuilt `frontend/dist`.

setuptools cannot reach above the package root, so `frontend/dist` and the root `LICENSE.md` are **staged into** `backend/` by [scripts/build_package.py](scripts/build_package.py) before `python -m build`. Both copies are git-ignored build artefacts; nothing else should read them.

The console entry point is `redactpdf = "redactpdf.launch:run"`, so the launcher body lives in the package ([backend/redactpdf/launch.py](backend/redactpdf/launch.py)). Root [launch.py](launch.py) is a thin shim that puts `backend/` on `sys.path` for a source checkout and delegates — it stays the file `packaging/redactpdf.spec` analyses.

The release build is windowed (`console=False`), so on Windows a frozen app has no `sys.stdout`/`sys.stderr` at all and a crash would be completely silent. [launch.py](launch.py) therefore routes every startup failure through `_fatal()` (GUI dialog, falling back to a stream when there is one) and wraps `main()` in a catch-all. Never replace those with a bare `print`/`sys.exit(str)`. `REDACT_PORT` and `REDACT_NO_BROWSER` exist so the smoke test can drive the app deterministically without hijacking a browser.

### Routing and serving

[main.py](backend/redactpdf/main.py) includes the same router twice — bare (`/redact/apply`, used by tests and the Vite proxy, which strips the `/api` prefix) and under `/api` (used by same-origin production and `launch.py`). Static `frontend/dist` is mounted at `/` **after** the API routes, and only when the directory exists. If you add an endpoint, add it to `router`, not to `app`, or it will only exist on one of the two prefixes.

### Frontend

- [App.tsx](frontend/src/App.tsx) holds all state; rules are a discriminated union in [types/uiRules.ts](frontend/src/types/uiRules.ts) (`exact | regex | selection | page | rectangle`). Geometric kinds become `rects` / `full_page_rects`; textual kinds become `searches` / `regexes`.
- [api.ts](frontend/src/api.ts) is the UI↔API translation layer and inverts one flag: UI "sous-mot" (`allowSubwords`) maps to `whole_word: !allowSubwords`, and for regex rules it wraps the pattern in `(?<!\w)…(?!\w)` client-side. Changing whole-word semantics means touching both this file and `build_whole_word_pattern` in the backend.
- [components/PdfViewer.tsx](frontend/src/components/PdfViewer.tsx) renders pdf.js pages and draws **preview** highlights by re-implementing matching in the browser over the text layer. For exact and regex rules this is an approximation of the backend engine and will not always agree with it — the backend remains authoritative, and the preview is not a place to add redaction logic.
- The `phone` preset is the exception, and deliberately so: [utils/phonePreview.ts](frontend/src/utils/phonePreview.ts) mirrors `_phone_post_filter` exactly, using `libphonenumber-js/max` (the `min` metadata diverges) and the backend's own default region, fetched from `/api/config`. A highlight reads as a promise: highlighting a number the backend will not touch produces a successful export with the data still in it, and the audit cannot catch that — it re-runs the same detector. Keep the two sides in step; `min` metadata and a hardcoded region both break the guarantee.
- i18n via [i18n.tsx](frontend/src/i18n.tsx) with flat key/value JSON in `locales/fr.json` and `locales/en.json`; default language is French. Both files must keep identical key sets — there is no fallback beyond echoing the key.
- [useHeartbeat.ts](frontend/src/useHeartbeat.ts) pings `/api/heartbeat` every 5s and `sendBeacon`s `/api/heartbeat/close` on `pagehide`, which is how `launch.py` knows to shut down.

## Tests

`backend/tests/fixtures/generated/*.pdf` are a **contract**: deterministic ReportLab-generated PDFs whose exact bytes are asserted by `test_fixtures.py` (SHA-256 against a fresh regeneration). Do not hand-edit them; if you change `generate_fixtures.py`, regenerate and commit all of them in the same change. Each fixture targets a specific trap (whole-word `CAT`/`CATCH`, phone split across lines vs across columns, Luhn-invalid cards, accents, metadata+annotation, rotated margin text…), so prefer extending the corpus over inventing PDFs inside a test.

Tests import the app directly (`from redactpdf.main import app`) with `fastapi.testclient`. `tests/utils_pdf.py` holds the two output inspectors: `extract_text` (via `pypdf` — deliberately a different library than the one that produced the redaction) and `inspect_pdf` (via PyMuPDF — metadata, XMP xref, links/annots/widgets, attachments), used by the sanitation tests.

## Conventions

- Dependencies in [backend/pyproject.toml](backend/pyproject.toml) are pinned exactly, `pymupdf` especially — redaction behaviour is version-sensitive. Bump deliberately and re-run the suite.
- Comments and docstrings are a mix of French and English; match the file you are editing.
- The security model and its limitations live in [docs/SECURITY.md](docs/SECURITY.md); changes affecting image modes, sanitation, or audit behaviour should be reflected there.
- Documentation is part of the change, not a follow-up. A commit that alters behaviour updates the page that describes it, in the same commit. The README carried "no regex timeout" for a week after the budget landed; that is the failure mode to avoid.
- No em dashes in the documentation (`README.md`, `docs/*.md`). Use a comma, a colon, parentheses, or two sentences. This file is exempt.
- Prose is split by reader, and each piece has one home. `README.md` says what the project is and how to get it, and stays short. [docs/USAGE.md](docs/USAGE.md) documents rule types, image modes and matching behaviour. [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) covers setup, tests, builds and CI. `docs/SECURITY.md` is canonical for **limits** — the other files link to it rather than restating them, because a duplicated limit is a limit that will drift (the README claimed "no regex timeout" for a week after the budget landed).
- AGPL-3.0 (inherited from PyMuPDF) — keep it in mind before vendoring or extracting code.
