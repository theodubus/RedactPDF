# RedactPDF
Local, verifiable PDF redaction (removes content instead of masking).

## Backend

Install dev dependencies:
```bash
pip install -e "backend[dev]"
````

Run tests:

```bash
cd backend
pytest
```

Run the API locally:

```bash
cd backend
uvicorn app.main:app --reload
```

## Security

See `docs/SECURITY.md`.

## Fixtures

See `backend/tests/fixtures/README.md`.
