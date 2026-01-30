# Testing

This project relies on automated tests and deterministic PDF fixtures to guarantee
that redaction is verifiable and does not silently regress.

## Test suites

Tests are organized using pytest markers:

- `unit`: pure unit tests (fast)
- `integration`: tests involving PDF processing and the API
- `e2e`: end-to-end tests (API + UI) (planned)
- `slow`: long-running tests

## Run tests locally

From the `backend/` directory:

Run everything:
```bash
pytest
```

Run unit tests only:
```bash
pytest -m unit
```

Run integration tests only:
```bash
pytest -m integration
```

Exclude integration tests:
```bash
pytest -m "not integration"
```

## Lint
From the `backend/` directory:
```bash
ruff check .
```

## Fixtures
PDF fixtures are deterministic and versioned.

See:
- [backend/tests/fixtures/README.md](../tests/fixtures/README.md)

Key rule:
- if you change `generate_fixtures.py`, regenerate fixtures and commit the updated PDFs
- the test suite enforces this rule