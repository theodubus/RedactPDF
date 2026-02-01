from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader


def extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join((p.extract_text() or "") for p in reader.pages)
