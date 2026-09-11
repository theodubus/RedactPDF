"""Un document signé qu'on caviarde n'est plus signé, et il faut le dire.

Une signature couvre les octets du fichier ; caviarder les réécrit. Aucune
implémentation ne peut préserver les deux, ce n'est pas un compromis mais une
définition. Ce qui était perfectible, c'est tout le reste. Mesuré sur un PDF
portant un champ de signature, avant les correctifs de ce module :

    entrée   get_sigflags() = 3   <</SigFlags 3/Fields[7 0 R]>>
    sortie   get_sigflags() = 3   <</SigFlags 3/Fields null>>
    rapport  aucune mention

Deux défauts et un manque :
  - `/Fields null` est malformé, la clé est obligatoire et doit être un tableau ;
  - `/SigFlags 3` survivait à la disparition du seul champ de signature, donc un
    lecteur annonçait un document signé sans plus rien à vérifier ;
  - l'utilisateur repartait avec un 200 et découvrait la perte chez le
    destinataire.
"""
from __future__ import annotations

import base64
import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from redactpdf.main import app
from redactpdf.pipeline import signatures_in

client = TestClient(app)


def _signed(field_name: str = "Signature1") -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Contrat signe par Jean Dupont", fontname="helv", fontsize=12)
    widget = pymupdf.Widget()
    widget.field_name = field_name
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
    widget.rect = pymupdf.Rect(72, 300, 300, 360)
    page.add_widget(widget)
    out = doc.tobytes()
    doc.close()
    return out


def _apply(pdf: bytes, payload: dict[str, object]):
    return client.post(
        "/redact/apply",
        files={"file": ("input.pdf", pdf, "application/pdf")},
        data={"payload": json.dumps(payload)},
    )


@pytest.mark.unit
def test_a_signature_field_is_seen_on_the_input() -> None:
    assert signatures_in(_signed("Signature1")) == ["Signature1"]


@pytest.mark.unit
def test_an_unsigned_document_reports_nothing() -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Jean Dupont", fontname="helv", fontsize=12)
    raw = doc.tobytes()
    doc.close()

    assert signatures_in(raw) == []


@pytest.mark.integration
def test_the_output_no_longer_claims_to_be_signed() -> None:
    """Le défaut : `/SigFlags` restait à 3 sur un document sans plus aucun champ."""
    resp = _apply(_signed(), {"searches": [{"query": "Dupont"}]})
    assert resp.status_code == 200, resp.text

    doc = pymupdf.open(stream=resp.content, filetype="pdf")
    try:
        assert doc.get_sigflags() == -1
        assert doc.xref_get_key(doc.pdf_catalog(), "AcroForm")[0] == "null"
        assert list(doc[0].widgets()) == []
    finally:
        doc.close()


@pytest.mark.integration
def test_the_report_says_the_signature_is_gone() -> None:
    resp = _apply(_signed("Signature1"), {"searches": [{"query": "Dupont"}]})
    assert resp.status_code == 200, resp.text
    assert resp.headers["X-Redaction-Signatures-Removed"] == "1"

    report = json.loads(base64.b64decode(resp.headers["X-Redaction-Audit-Report-B64"]))
    assert report["signatures"]["count"] == 1
    assert report["signatures"]["fields"] == ["Signature1"]


@pytest.mark.integration
def test_an_unsigned_document_carries_no_such_mention() -> None:
    """Sinon l'avertissement se banalise et ne veut plus rien dire."""
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Jean Dupont", fontname="helv", fontsize=12)
    raw = doc.tobytes()
    doc.close()

    resp = _apply(raw, {"searches": [{"query": "Dupont"}]})
    assert resp.status_code == 200, resp.text
    assert resp.headers["X-Redaction-Signatures-Removed"] == "0"

    report = json.loads(base64.b64decode(resp.headers["X-Redaction-Audit-Report-B64"]))
    assert "signatures" not in report
