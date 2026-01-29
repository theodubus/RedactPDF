from __future__ import annotations

import hashlib
from pathlib import Path

from pypdf import PdfReader  # type: ignore

from tests.fixtures.generate_fixtures import GENERATED_DIR, SECRET, SPECS, generate_all


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def test_fixtures_exist_and_non_empty() -> None:
    expected = [GENERATED_DIR / spec.filename for spec in SPECS]
    for p in expected:
        assert p.exists(), f"Missing fixture: {p}"
        assert p.stat().st_size > 0, f"Empty fixture: {p}"


def test_sanity_extract_text_contains_secret() -> None:
    pdf_path = GENERATED_DIR / "001_secret_text.pdf"
    reader = PdfReader(str(pdf_path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert SECRET in text


def test_fixtures_are_deterministic_and_up_to_date(tmp_path: Path) -> None:
    """
    Regenerate fixtures into a temp directory and compare hashes with committed fixtures.
    This enforces: if the generator changes, fixtures must be regenerated and committed.
    """
    regenerated_dir = tmp_path / "generated"
    generate_all(output_dir=regenerated_dir)

    for spec in SPECS:
        committed = GENERATED_DIR / spec.filename
        regen = regenerated_dir / spec.filename
        assert committed.exists()
        assert regen.exists()

        committed_hash = _sha256(committed)
        regen_hash = _sha256(regen)

        if committed_hash != regen_hash:
            msg = (
                "Fixture out of date or non-deterministic: "
                f"{spec.filename}\n"
                f"committed={committed_hash}\n"
                f"regen={regen_hash}"
            )
            raise AssertionError(msg)
