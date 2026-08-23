# <img src="frontend/public/logo.png" alt="RedactPDF" width="40" align="center" /> RedactPDF

Local web app for redacting sensitive content from PDF files. Targets manual
rectangles, text search, regex (single- or multi-line), and presets (email,
phone, credit card). Every export passes a post-redaction audit before being
returned, if any targeted content remains in the output, the export is
blocked with a structured failure report.

For the security model and limitations, see [docs/SECURITY.md](docs/SECURITY.md).

<p align="center">
  <video src="https://github.com/user-attachments/assets/db585e59-6a00-43cc-ab6d-9ce19031541b" controls width="820">
    <a href="https://github.com/user-attachments/assets/db585e59-6a00-43cc-ab6d-9ce19031541b">▶ Watch the demo</a>
  </video>
</p>

---

## Requirements

- **Python 3.10 or newer** (CI runs 3.11)
- **Node.js 20 or newer** (for the frontend dev server / build)
- A POSIX-like shell (Linux, macOS, WSL). Windows native is not officially
  tested.

---

## Install

Clone the repo and set up the two halves:

```bash
git clone https://github.com/theodubus/RedactPDF.git
cd RedactPDF
```

### Backend (FastAPI + PyMuPDF)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`.[dev]` pulls runtime deps (FastAPI, PyMuPDF, `phonenumbers`, …) plus dev
tooling (pytest, ruff, reportlab, httpx, pypdf).

### Frontend (React + Vite)

```bash
cd ../frontend
npm ci
```

---

## Run locally

Two ways: one command to just use the app, two terminals to work on it.

### Just use it

Build the UI once:

```bash
cd frontend
npm run build
```

Then, from the repo root, with the backend venv active:

```bash
python launch.py
```

This picks a free local port, serves the UI and the API from a single process
(same-origin, so no CORS and no proxy), opens your default browser, and stops
the server a few seconds after you close the tab. Re-run `python launch.py`
whenever you want it again; you only need to rebuild the frontend after
changing the UI source.

### Work on it

Hot reload needs two terminals.

**Terminal 1 - backend:**

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 - frontend:**

```bash
cd frontend
npm run dev
```

Open the URL Vite prints (default: `http://localhost:5173`). The Vite dev
server proxies `/api/*` to the backend on `127.0.0.1:8000` (configured in
[frontend/vite.config.ts](frontend/vite.config.ts)), so you do not need to
worry about CORS in development.

---

## Use it

1. Drop a PDF into the upload area.
2. Add redaction rules in the right pane:
   - **Selection** : select text in the viewer and click "Redact selection" / "Censurer la sélection".
   - **Manual rectangle** : toggle the draw tool and trace rectangles.
   - **Whole page** : censor the current page.
   - **Exact / regex** : typed rules with options (case sensitivity,
     whole-word, ignore accents, multiline).
   - **Presets** : email, phone (libphonenumber-validated, default region
     `FR`), credit card (Luhn-filtered).
3. Pick an **image redaction mode** in the right pane (segmented control):
   - **Aucune** (None) : images and vector graphics are not modified, even
     if a redaction rectangle overlaps them. Only the text under the
     redaction is removed; visually a black overlay is drawn on top, but
     the underlying images/graphics still exist in the PDF and are
     recoverable by anyone who removes the overlay.
   - **Totale** (Full) : any image touched by a rectangle is removed
     entirely; any vector path touched is removed.
   - **Précise** (Precise) *(default)* : only the pixels inside the
     redaction rectangle are blackened in the underlying bitmap; the rest
     of the image stays visible. Vector paths touched by the rectangle are
     removed (per-path, not pixel-level, vector partial redaction is not
     supported). **This is the mode that makes flattened / scanned PDFs
     redactable**, without it, the only options on a scan would be "lose
     the whole page" or draw a fake black overlay. Re-encoding may be
     lossy on JPEG-backed images.

   The mode applies globally to the redaction request. **Exception**: any
   "Censurer la page" rule (full-page redaction) always uses strict mode
   for the page it covers, regardless of the chosen image mode, so a
   full-page rule cannot accidentally leave images or graphics under a
   black overlay. See [docs/SECURITY.md](docs/SECURITY.md) for details.
4. Click the submit button. The redacted PDF downloads automatically.
5. If the post-redaction audit finds any targeted content remaining, you
   get a 400 with a JSON report instead, fix the rule and retry.

### Phone preset region

The `phone` preset uses `phonenumbers` to validate candidates. Numbers
without a leading `+` are parsed against a default region. To change it:

```bash
export REDACT_DEFAULT_REGION=US
uvicorn app.main:app ...
```

---

## Run the tests

```bash
cd backend
source .venv/bin/activate
ruff check .
pytest
```

The test suite uses **versioned PDF fixtures** : see
[backend/tests/fixtures/README.md](backend/tests/fixtures/README.md). Do not
edit the generated PDFs by hand. If you change the fixture generator,
regenerate all of them in one go:

```bash
python -m backend.tests.fixtures.generate_fixtures
```

---

## Production deployment

This project is built for local single-user usage. **Exposing the API to
untrusted networks or multiple users is unsafe out of the box**, there is
no auth, no rate limiting, no upload size cap, no regex timeout. If you
plan to host it for others, read
[docs/SECURITY.md → Production / Multi-user Deployment](docs/SECURITY.md)
first and put the recommended protections in your reverse proxy /
container.

A typical setup is: build the frontend (`npm run build` produces a static
bundle in `frontend/dist`), serve it from a reverse proxy that also
proxies `/api/*` to the backend (Uvicorn or Gunicorn-with-Uvicorn-workers
behind nginx/Caddy). With same-origin serving, you do not need CORS.

---

## License

RedactPDF is licensed under the **GNU Affero General Public License v3.0**
(AGPL-3.0) — see [LICENSE.md](LICENSE.md) for the full text.

In short: you may use, study, modify, and redistribute it freely, but any
redistributed or network-hosted (SaaS) version, including modified ones,
must make its **complete corresponding source available under the same
AGPL-3.0 terms**. This copyleft is also required by the core dependency
PyMuPDF, which is itself AGPL-3.0 (or commercial).
