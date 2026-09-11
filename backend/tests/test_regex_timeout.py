from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from redactpdf.main import app
from redactpdf.regex_guard import RegexBudget, RegexTimeout, compile_pattern
from redactpdf.regex_guard import finditer as guarded_finditer

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "generated"

# Quantificateurs imbriqués sur une alternance redondante : chaque découpage de
# la suite de « a » doit être essayé avant de conclure à l'échec.
CATASTROPHIC = r"(a|a)+$"


@pytest.mark.unit
def test_budget_interrupts_a_catastrophic_pattern() -> None:
    """Le parcours doit rendre la main, au lieu de figer le processus.

    `re` ne relâche pas le GIL pendant le parcours : sans interruption au niveau
    du moteur, rien ne pourrait observer un délai, pas même un thread de garde.
    """
    budget = RegexBudget(seconds=1.0)
    pattern = compile_pattern(CATASTROPHIC, ignore_case=False)

    started = time.monotonic()
    with pytest.raises(RegexTimeout):
        guarded_finditer(pattern, "a" * 40 + "b", budget)
    elapsed = time.monotonic() - started

    # `re` met une cinquantaine de secondes sur une entrée de cette taille.
    assert elapsed < 5.0, f"interruption trop lente : {elapsed:.1f}s"


@pytest.mark.unit
def test_budget_is_shared_across_scans() -> None:
    """Le budget couvre la requête entière, pas chaque parcours.

    Le moteur exécute les motifs ligne par ligne : un délai par appel serait
    multiplié par le nombre de lignes, et « dix secondes » deviendraient une
    heure sur un document de cent pages.
    """
    budget = RegexBudget(seconds=1.0)
    pattern = compile_pattern(CATASTROPHIC, ignore_case=False)
    text = "a" * 40 + "b"

    started = time.monotonic()
    for _ in range(3):
        with pytest.raises(RegexTimeout):
            guarded_finditer(pattern, text, budget)
    elapsed = time.monotonic() - started

    # Trois parcours sous un budget d'une seconde restent sous deux secondes ;
    # un délai par appel en aurait pris trois.
    assert elapsed < 2.0, f"le budget n'est pas partagé : {elapsed:.1f}s"


@pytest.mark.integration
def test_api_answers_instead_of_hanging_on_a_catastrophic_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L'API doit répondre en erreur, pas rester muette pendant que ça tourne.

    C'est le point où `docs/SECURITY.md` divergeait du fonctionnement réel : il
    renvoyait la parade au reverse proxy du déployeur, alors que le mode d'usage
    principal est un binaire local, où il n'y a pas de déployeur.
    """
    monkeypatch.setenv("REDACT_REGEX_TIMEOUT", "1")
    pdf_bytes = (FIXTURES_DIR / "014_redos_bait.pdf").read_bytes()

    payload = {
        "rects": [],
        "regexes": [
            {
                "patterns": [CATASTROPHIC],
                "case_sensitive": True,
                "multiline": False,
                "scope": {"pages": None},
            }
        ],
    }

    started = time.monotonic()
    resp = TestClient(app).post(
        "/redact/apply",
        files={
            "file": ("in.pdf", pdf_bytes, "application/pdf"),
            "payload": (None, json.dumps(payload), "application/json"),
        },
    )
    elapsed = time.monotonic() - started

    assert resp.status_code == 400, resp.text
    assert "budget" in resp.text.lower()
    assert elapsed < 10.0, f"réponse trop lente : {elapsed:.1f}s"
