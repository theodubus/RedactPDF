# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Backend (run from `backend/`, with `.venv` active — `pip install -e ".[dev]"`):

```bash
ruff check .                      # lint (line-length 100, rules E,F,I,UP,B)
pytest                            # full suite (testpaths=tests, pythonpath=.)
pytest tests/test_redact_apply.py::test_redact_apply_combines_search_and_presets_email
pytest -m unit                    # markers: unit, integration, e2e, slow
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend (run from `frontend/`):

```bash
npm ci
npm run dev                       # Vite dev server on :5173, proxies /api/* -> :8000
npm run build                     # tsc -b && vite build -> frontend/dist
npm run lint                      # eslint (not run by CI; CI only builds)
```

Desktop / single-process mode (from repo root, after `npm run build`):

```bash
python launch.py                  # free port + same-origin UI + heartbeat auto-shutdown
```

Standalone build (needs the `packaging` extra: `pip install -e "backend[dev,packaging]"`):

```bash
python scripts/build_app.py                    # npm build + PyInstaller -> dist/redactpdf
python scripts/build_app.py --skip-frontend    # reuse the existing frontend/dist
```

PyInstaller does not cross-compile — one build per target OS, and the Linux binary
requires a glibc at least as new as the build machine's.

Fixture regeneration (from **repo root**, not `backend/`):

```bash
python -m backend.tests.fixtures.generate_fixtures
```

CI: `backend-ci` runs `ruff check .` + `pytest` on Python 3.11; `frontend-ci` runs `npm run build` on Node 20.

## Architecture

Two halves: a FastAPI + PyMuPDF backend that does all redaction work, and a React/Vite SPA that renders the PDF with pdf.js and builds the rule payload. There is exactly one API call in the whole app: `POST /redact/apply` (multipart: `file` + a JSON `payload` string).

### Request flow: plan → apply → audit

[backend/app/pipeline.py](backend/app/pipeline.py) is the spine, and the ordering is a security invariant:

1. **`plan_redactions`** computes *all* rectangles (manual, search, regex, presets) from the **original** PDF bytes. Never re-derive rectangles from a partially-redacted document — a prior redaction would hide text a later rule needed to match. `test_redact_apply.py` has a regression test for this.
2. **`apply_plan`** runs redaction in up to two passes: full-page rects first in forced strict mode (`image_mode="remove"`, `apply_graphics=True`) regardless of what the user picked, then everything else in the user's mode. Sanitisation is deferred to the last pass so it runs once on the final document.
3. **`audit_plan`** re-runs every requested rule against the **output** PDF's extracted text. Any surviving match makes [main.py](backend/app/main.py) return HTTP 400 with a structured component report instead of the PDF. A successful export also carries the report base64'd in `X-Redaction-Audit-Report-B64` plus `X-Redaction-*-Occurrences` headers.

Never add a path that returns a PDF without passing the audit.

### Backend modules

- [redaction.py](backend/app/redaction.py) — the only place that touches PyMuPDF redaction primitives. `_tighten_rect_vertical` shrinks extracted line boxes so a rect doesn't eat the line below; saves with `garbage=4` (required for metadata/image removal to be physical, not just unreferenced).
- [multiline_regex_engine.py](backend/app/multiline_regex_engine.py) — the real matching engine. Extracts words/lines/char boxes, maps regex spans back to geometry, and fuses lines only when they overlap horizontally enough (`min_x_overlap_ratio`), which is what prevents cross-column false fusions (fixture `009`). Accent folding (`_fold_keep_len`) is deliberately **length-preserving** so string indices stay valid for span→rect mapping — keep that property in any change here.
- [search.py](backend/app/search.py) — exact search. Fast path uses `page.search_for()`; `whole_word` or `ignore_accents` fall back to the regex engine with a generated pattern.
- [presets.py](backend/app/presets.py) — email / phone / credit_card. Regex candidates plus post-filters: Luhn for cards, `phonenumbers` validation for phones (default region from `REDACT_DEFAULT_REGION`, `FR`).
- [audit.py](backend/app/audit.py) — text-level audit primitives and `build_whole_word_pattern`, shared with `search.py` so search semantics and audit semantics cannot drift apart.
- [sanitize.py](backend/app/sanitize.py) — metadata / annotations / widgets / attachments, on by default.
- [heartbeat.py](backend/app/heartbeat.py) — liveness singleton; inert unless `launch.py` started a watchdog thread.

### Packaging

[packaging/redactpdf.spec](packaging/redactpdf.spec) freezes `launch.py` into one executable. Three things there are load-bearing and easy to break: `phonenumbers` region metadata and uvicorn's protocol/loop implementations are both resolved by string at runtime, so they are pulled in with `collect_submodules`; and `frontend/dist` is embedded as data under that same relative name. Anything else resolved dynamically needs the same treatment, and the symptom is always a runtime `ModuleNotFoundError` in the frozen binary only — never in the test suite.

Because of that embedding, **no module may locate the UI from `__file__`**: once frozen, the code lives in a temporary extraction tree, not the repo. [app/paths.py](backend/app/paths.py) is the single place that knows both layouts (`frontend_dist()`, `is_frozen()`); `main.py` and `launch.py` go through it.

### Routing and serving

[main.py](backend/app/main.py) includes the same router twice — bare (`/redact/apply`, used by tests and the Vite proxy, which strips the `/api` prefix) and under `/api` (used by same-origin production and `launch.py`). Static `frontend/dist` is mounted at `/` **after** the API routes, and only when the directory exists. If you add an endpoint, add it to `router`, not to `app`, or it will only exist on one of the two prefixes.

### Frontend

- [App.tsx](frontend/src/App.tsx) holds all state; rules are a discriminated union in [types/uiRules.ts](frontend/src/types/uiRules.ts) (`exact | regex | selection | page | rectangle`). Geometric kinds become `rects` / `full_page_rects`; textual kinds become `searches` / `regexes`.
- [api.ts](frontend/src/api.ts) is the UI↔API translation layer and inverts one flag: UI "sous-mot" (`allowSubwords`) maps to `whole_word: !allowSubwords`, and for regex rules it wraps the pattern in `(?<!\w)…(?!\w)` client-side. Changing whole-word semantics means touching both this file and `build_whole_word_pattern` in the backend.
- [components/PdfViewer.tsx](frontend/src/components/PdfViewer.tsx) renders pdf.js pages and draws **preview** highlights by re-implementing matching in the browser over the text layer. This is an approximation of the backend engine and will not always agree with it — the backend remains authoritative, and the preview is not a place to add redaction logic.
- i18n via [i18n.tsx](frontend/src/i18n.tsx) with flat key/value JSON in `locales/fr.json` and `locales/en.json`; default language is French. Both files must keep identical key sets — there is no fallback beyond echoing the key.
- [useHeartbeat.ts](frontend/src/useHeartbeat.ts) pings `/api/heartbeat` every 5s and `sendBeacon`s `/api/heartbeat/close` on `pagehide`, which is how `launch.py` knows to shut down.

## Tests

`backend/tests/fixtures/generated/*.pdf` are a **contract**: deterministic ReportLab-generated PDFs whose exact bytes are asserted by `test_fixtures.py` (SHA-256 against a fresh regeneration). Do not hand-edit them; if you change `generate_fixtures.py`, regenerate and commit all of them in the same change. Each fixture targets a specific trap (whole-word `CAT`/`CATCH`, phone split across lines vs across columns, Luhn-invalid cards, accents, metadata+annotation…), so prefer extending the corpus over inventing PDFs inside a test.

Tests import the app directly (`from app.main import app`) with `fastapi.testclient`. `tests/utils_pdf.py` holds the two output inspectors: `extract_text` (via `pypdf` — deliberately a different library than the one that produced the redaction) and `inspect_pdf` (via PyMuPDF — metadata, XMP xref, links/annots/widgets, attachments), used by the sanitation tests.

## Conventions

- Dependencies in [backend/pyproject.toml](backend/pyproject.toml) are pinned exactly, `pymupdf` especially — redaction behaviour is version-sensitive. Bump deliberately and re-run the suite.
- Comments and docstrings are a mix of French and English; match the file you are editing.
- The security model and its limitations live in [docs/SECURITY.md](docs/SECURITY.md); changes affecting image modes, sanitation, or audit behaviour should be reflected there.
- AGPL-3.0 (inherited from PyMuPDF) — keep it in mind before vendoring or extracting code.
