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
npm test                          # vitest, src/**/*.test.ts
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

CI: `backend-ci` runs `ruff check .` + `mypy` + `pytest` on Python 3.11; `frontend-ci` runs `npm run lint` (zero warnings) + `npm test` + `npm run build` on Node 20; `smoke-ci` has two jobs — one drives `scripts/smoke_test_app.py --source`, the other builds the wheel, installs it into a clean venv and drives the installed `redactpdf` console script. Between them they cover what pytest cannot see: `launch.py`, `redactpdf/paths.py`, same-origin serving of the built UI, and the end-to-end API path, without paying for a PyInstaller build. `release` fires on a `v*` tag: it checks the tag matches `version` in `backend/pyproject.toml`, builds the standalone binaries on Linux and Windows gated on the frozen `smoke_test_app.py`, builds and smoke-tests the wheel, attests the provenance of every artifact it produces (`actions/attest-build-provenance`, which needs `id-token: write` + `attestations: write` on the producing job), drafts a GitHub Release carrying the binaries, the distributions and a `SHA256SUMS.txt` — never publishing it on its own — and publishes the distributions to PyPI through Trusted Publishing (OIDC, environment `pypi`, no stored secret). The release notes tell readers how to check both: `sha256sum -c` for the bytes, `gh attestation verify` for the origin. That pair is the only trust story available without a paid code-signing certificate, so do not drop it.

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
- [audit.py](backend/redactpdf/audit.py) — text-level audit primitives and `build_whole_word_pattern`, shared with `search.py` so search semantics and audit semantics cannot drift apart. `audit_pdf_text` reads the output through **both** entries of `_EXTRACTORS` (PyMuPDF and `pypdf`) and unions their matches by `(pattern, occurrence index)`, so a match either engine sees refuses the export; `pypdf` is a runtime dependency for this reason, not a test-only one. Never reduce this to a single engine: reading back with the library that wrote the file correlates the redaction's blind spots with the audit's. A broken extractor is recorded in the report's `extractors` map rather than silently halving coverage, and `pipeline.audit_plan` propagates that map to the success report too.
- [regex_guard.py](backend/redactpdf/regex_guard.py) — every user-supplied pattern runs through here, on the `regex` engine rather than `re`, under a time budget **shared by the whole request** (`REDACT_REGEX_TIMEOUT`, 10s). Two reasons the guard has that exact shape, both easy to undo by accident: `re` does not release the GIL while matching, so a watchdog thread could never observe a runaway pattern — the interruption must come from inside the engine; and patterns run line by line, so a per-call timeout would be multiplied by the number of lines. `RegexTimeout` subclasses `ValueError` so it lands on the existing 400 path. Nothing in the package may compile a user-supplied pattern with `re` — only `re.escape`, which builds a pattern string without matching, is allowed. `mypy --strict` now enforces this: `types-regex` is a dev dependency precisely so a signature cannot claim `re.Pattern` on a path that must stay on the `regex` engine, which is how a stale annotation sat on that boundary until it was checked.
- [opaque.py](backend/redactpdf/opaque.py) — regions the text rules could not read: an image covering at least `MIN_PAGE_SHARE` of the page. That is the *only* criterion, and the second one was removed for cause: skipping an image with more than 5 % of its area under text blocks re-created the hybrid failure one level down, and a real transcript proved it (a full-page scan at 93.7 % page share, carrying the whole form in pixels, skipped for an 18.6 % text ratio). A ratio of area ignores shape, exactly like the 95 % coverage threshold before it; `text_ratio` is still reported, never filtered on. Each region carries the `digest` of its pixels so the UI can group a banner repeated across pages into one review screen, plus the `xref` and placement `transform`. `region_previews` ships the pixels of each distinct image base64 in the 409 (keyed by digest, resolution stepping down with the number of images) and `covered_in_image` maps already-covered rectangles into that image's own normalised coordinates through the **inverse** of the placement matrix — a rule of three on the bounding box picks the wrong quadrant on a rotated image and would paint "already covered" over pixels nothing covers; `test_opaque_regions.py` has a quarter-turn regression test. Purely geometric, and deliberately so: it never looks inside the image, so it cannot tell a scanned table from a photograph, and the honest answer in both cases is the same. Computed from `pipeline.readable_view` (the document with sanitation applied, redaction not) rather than the raw original, and filtered by `drop_covered` so a region a geometric rule already handles is not reported. The sanitised basis matters: an image living only in a deleted annotation's appearance is not in the export, so reviewing it means checking what is being erased — a real internship agreement put a scanned signature up as a fifth review screen. Redaction is still not applied first, since a blacked-out area would no longer answer the question. An image with no reachable object (inline, or inside an annotation appearance: both report `xref` 0) gets its preview from `_strip_text`, a copy whose text is removed via `apply_redactions(images=NONE, graphics=NONE)` while pixels and line art stay — never from the page as it stands, or page text lands back in the thumbnail. **Vector graphics are out of scope**: only raster images are examined, so a vector chart, a vector logo, and above all text converted to outlines are unread by the rules and unflagged here. `main.py` turns what is left into **HTTP 409** (distinct from the 400 that means content survived) according to `options.image_regions`. Testing "does the page have text" instead would miss every hybrid page, which is why the check is per image. The same module also flags **fonts the rules cannot read**: `Identity-H`/`Identity-V` or Type3 without `/ToUnicode`, where extraction returns glyph indices rather than text. The criterion is deliberately not "composite font without `/ToUnicode`" — a first version assumed that and would have fired on every CJK document, since registry CMaps like `/UniGB-UTF16-H` carry Unicode on their own. Those pages ride the same 409 under `unreliable_fonts` and are acknowledged by page number, because the tool does not know where the affected text sits.
- [sanitize.py](backend/redactpdf/sanitize.py) — everything carrying text outside the page content stream, all on by default: metadata and XMP, links, annotations, widgets, attachments, bookmark titles (`remove_outline`), and document JavaScript / `/OpenAction` / `/AA` / XFA (`remove_document_actions`). The carrier is dropped whole rather than searched for the target, so sanitation never needs to know the rules. `test_sanitize_carriers.py` asserts the target is absent from the **raw output bytes**, which no reader API can talk it out of. Annotations are removed twice: the PyMuPDF walk (which keeps `/AcroForm` bookkeeping straight when it works) and then `_drop_annot_references`, which cuts the page's `/Annots` and `/AcroForm/Fields` unconditionally — the net is what carries the guarantee, the walk is only the polite path to it. The walk *does* break: `delete_annot` returns the next link in the chain, and after deleting an annotation that owns a popup that next entry is the popup, now detached, so PyMuPDF raises `Annot is not bound to a page` and the whole request 500s. A single sticky note triggers it, and the loop in question is the documented one. `_drain` therefore stops at the first dead handle rather than continuing — the chain is not trustworthy once a link has failed.
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
- The `phone` preset is the exception, and deliberately so: [utils/phonePreview.ts](frontend/src/utils/phonePreview.ts) mirrors `_phone_post_filter` exactly, using `libphonenumber-js/max` (the `min` metadata diverges) and the backend's own default region, fetched from `/api/config`. A highlight reads as a promise: highlighting a number the backend will not touch produces a successful export with the data still in it, and the audit cannot catch that — it re-runs the same detector. Keep the two sides in step; `min` metadata and a hardcoded region both break the guarantee. That is no longer left to vigilance: `phoneParity.fixture.json` is generated from the backend and **both suites check it**, `backend/tests/test_phone_parity.py` against `_phone_post_filter` and `phonePreview.test.ts` against the browser mirror, so a drift on either side fails one of them. Verified that the guard bites: switching the import back to `libphonenumber-js/min` fails the frontend suite on `07 00 00 00 00`. Regenerate the fixture from the backend whenever the filter changes; never hand-edit it to make a test pass.
- `frontend/src/review/` is the pre-export review step. [reviewItems.ts](frontend/src/review/reviewItems.ts) holds all the logic and no DOM, which is what makes it testable; the components stay thin. Only what the engine could not read scrolls there, and it comes back in a 409. **Hand-drawn rectangles are not review items** — an earlier version made them one, and it was wrong: the rectangle *is* the instruction, the preview already shows it in place, and reconfirming it spends friction that is then unavailable where nothing else can check. They appear as `CoveredArea` overlays drawn on the thumbnail instead, so the decision is about what remains inside the region; OCR proposals will join them there, visually distinct, since a suggestion must never read as a decision. **The thumbnail shows the image, never the page region** — pdf.js rendering of the region composites the text layer, which is exactly what the rules *did* read, so it mixes handled with unhandled and invites "looks legible, nothing hidden" about the one object nothing can vouch for. Pixels come from the server; the pdf.js path survives only for `unreliable_fonts`, where there is no image and the unit is the whole page. Overlays are CSS percentages of the image box, so they follow the zoom toggle with no math. `reviewSteps` groups regions by pixel digest **and** identical coverage (one screen, one confirm, an acknowledgement per page) and never groups without a digest. `serverReviewItems` accepts the body both wrapped in FastAPI's `detail` and bare: it first read only the top level, the carousel never opened, and the unit test missed it because it was fed the shape I had imagined. A run through a real browser found it. One confirm button per screen, never a global one.
- i18n via [i18n.tsx](frontend/src/i18n.tsx) with flat key/value JSON in `locales/fr.json` and `locales/en.json`; default language is French. Both files must keep identical key sets — there is no fallback beyond echoing the key.
- [useHeartbeat.ts](frontend/src/useHeartbeat.ts) pings `/api/heartbeat` every 5s and `sendBeacon`s `/api/heartbeat/close` on `pagehide`, which is how `launch.py` knows to shut down.

## Tests

`backend/tests/fixtures/generated/*.pdf` are a **contract**: deterministic ReportLab-generated PDFs whose exact bytes are asserted by `test_fixtures.py` (SHA-256 against a fresh regeneration). Do not hand-edit them; if you change `generate_fixtures.py`, regenerate and commit all of them in the same change. Each fixture targets a specific trap (whole-word `CAT`/`CATCH`, phone split across lines vs across columns, Luhn-invalid cards, accents, metadata+annotation, rotated margin text, tight leading…), so prefer extending the corpus over inventing PDFs inside a test. `015_tight_leading.pdf` is the only one that makes `_tighten_rect_vertical` do anything: every other fixture leaves at least 5 mm between lines, where the tightening is a no-op. Keep it that way when adding fixtures, and do not widen its leading.

Tests import the app directly (`from redactpdf.main import app`) with `fastapi.testclient`. `tests/test_properties.py` runs `hypothesis` over two invariants whose input space is the whole of Unicode: `_fold_keep_len` preserves length (an offset redacts the wrong glyphs rather than more of them) and `build_whole_word_pattern` holds its boundaries. `tests/utils_pdf.py` holds the two output inspectors: `extract_text` (via `pypdf` — deliberately a different library than the one that produced the redaction) and `inspect_pdf` (via PyMuPDF — metadata, XMP xref, links/annots/widgets, attachments), used by the sanitation tests.

## Conventions

- Dependencies in [backend/pyproject.toml](backend/pyproject.toml) are pinned exactly, `pymupdf` especially — redaction behaviour is version-sensitive. Bump deliberately and re-run the suite.
- Comments and docstrings are a mix of French and English; match the file you are editing.
- The security model and its limitations live in [docs/SECURITY.md](docs/SECURITY.md); changes affecting image modes, sanitation, or audit behaviour should be reflected there.
- Documentation is part of the change, not a follow-up. A commit that alters behaviour updates the page that describes it, in the same commit. The README carried "no regex timeout" for a week after the budget landed; that is the failure mode to avoid.
- No em dashes in the documentation (`README.md`, `docs/*.md`). Use a comma, a colon, parentheses, or two sentences. This file is exempt.
- Prose is split by reader, and each piece has one home. `README.md` says what the project is and how to get it, and stays short. [docs/USAGE.md](docs/USAGE.md) documents rule types, image modes and matching behaviour. [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) covers setup, tests, builds and CI. `docs/SECURITY.md` is canonical for **limits** — the other files link to it rather than restating them, because a duplicated limit is a limit that will drift (the README claimed "no regex timeout" for a week after the budget landed).
- AGPL-3.0 (inherited from PyMuPDF) — keep it in mind before vendoring or extracting code.
