from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

try:
    import pymupdf
except Exception:  # pragma: no cover
    import fitz as pymupdf  # type: ignore


def _read_fixture(name: str) -> bytes:
    # À adapter si votre helper existe déjà / chemin différent
    from pathlib import Path

    return (Path("tests/fixtures/generated") / name).read_bytes()


def _count_links_annots_widgets(pdf_bytes: bytes) -> tuple[int, int, int]:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        links = 0
        annots = 0
        widgets = 0
        for pno in range(doc.page_count):
            page = doc.load_page(pno)

            # links
            try:
                links += len(page.get_links())
            except Exception:
                pass

            # annots
            annot = getattr(page, "first_annot", None) or getattr(page, "firstAnnot", None)
            while annot:
                annots += 1
                annot = annot.next  # type: ignore[attr-defined]

            # widgets
            widget = getattr(page, "first_widget", None) or getattr(page, "firstWidget", None)
            while widget:
                widgets += 1
                widget = widget.next  # type: ignore[attr-defined]

        return links, annots, widgets
    finally:
        doc.close()


@pytest.mark.integration
def test_sanitize_metadata_and_annotations_via_regex_endpoint() -> None:
    pdf_in = _read_fixture("010_metadata_and_annotation.pdf")

    # Pré-conditions : metadata non vide + au moins un lien/annot/widget (selon votre fixture)
    doc0 = pymupdf.open(stream=pdf_in, filetype="pdf")
    try:
        md0 = dict(doc0.metadata or {})
        assert md0.get("title") not in (None, "", "none")
    finally:
        doc0.close()

    links0, annots0, widgets0 = _count_links_annots_widgets(pdf_in)
    assert (links0 + annots0 + widgets0) > 0

    client = TestClient(app)

    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": [r"THIS_WILL_NOT_MATCH_123456789"],
                "case_sensitive": True,
                "multiline": False,
                "scope": {"pages": None},
            }
        ],
        "options": {
            "apply_images": False,
            "apply_graphics": False,
            "sanitize_metadata": True,
            "remove_annotations": True,
            "remove_attachments": False,
        },
        "audit": {
            # pattern improbable pour forcer un PASS (0 match)
            "patterns": ["AUDIT_SHOULD_NOT_FIND_THIS_123456"],
            "regex": False,
            "case_sensitive": True,
        },
    }

    files = {
        "file": ("in.pdf", pdf_in, "application/pdf"),
        "payload": (None, json.dumps(payload), "application/json"),
    }

    resp = client.post("/redact/apply", files=files)
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/pdf")

    pdf_out = resp.content

    # Post-conditions : metadata “cleared” + plus aucune annotation/lien/widget
    doc1 = pymupdf.open(stream=pdf_out, filetype="pdf")
    try:
        md1 = dict(doc1.metadata or {})
        # doc.set_metadata({}) met les champs à "none" selon la doc PyMuPDF
        for k in (
            "title",
            "author",
            "subject",
            "keywords",
            "creator",
            "producer",
            "creationDate",
            "modDate",
        ):
            # PyMuPDF selon versions met "" ou "none" après set_metadata({})
            assert md1.get(k) in ("", "none", None)
        if hasattr(doc1, "xml_metadata_xref"):
            assert int(doc1.xml_metadata_xref()) == 0
    finally:
        doc1.close()

    links1, annots1, widgets1 = _count_links_annots_widgets(pdf_out)
    assert (links1 + annots1 + widgets1) == 0
