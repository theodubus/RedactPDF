# PDF Test Fixtures

This directory contains **deterministic PDF fixtures** used as the reference corpus
for all redaction and audit tests.

These files are **versioned** and must not be edited manually.

## Purpose

The fixtures cover common and problematic cases for PDF redaction:

- simple text with a known secret (`SECRET_ABC123`)
- email and phone number on one line
- phone number split across two lines
- embedded bitmap image
- vector graphics (shapes)
- multi-column layout
- whole-word behavior (`CAT` must not match inside `CATCH`)
- credit card numbers (valid vs invalid; Luhn filtering)
- cross-column trap: phone split across columns (must **not** be matched as multiline)
- metadata + annotation: non-empty PDF metadata and a link annotation (used for sanitize tests)
- apply combined: name with punctuation + email containing the name
- Ignore accents fixture ("Léo" vs "Leo")
- rotated margin text: a vertical title and a vertical amount whose
  decimals form a partial-word match (no vertical tightening, glyphs ordered
  along the reading direction)
- tight leading: two blocks at 9 pt, one at 3.5 mm of leading where the
  vertical tightening is what saves the line below, one at 2.5 mm where it no
  longer suffices. Every other fixture leaves at least 5 mm between lines, so
  this is the only one that makes `_tighten_rect_vertical` do any work. Do not
  widen its leading.

They serve as a **contract**: tests rely on their exact content and structure.

## Regenerating fixtures

Fixtures are generated programmatically using ReportLab.

To regenerate them:

```bash
python -m backend.tests.fixtures.generate_fixtures
```

## Important rule

If you modify `generate_fixtures.py`, you must regenerate the fixtures
and commit the updated PDFs.

This is enforced by tests: if the generator changes without regenerating
the PDFs, the test suite will fail.
