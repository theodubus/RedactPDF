"""Le corpus de parité téléphone, vu du backend.

`frontend/src/utils/phonePreview.ts` doit rendre exactement ce que
`_phone_post_filter` rend. Un aperçu qui surligne un numéro se lit comme une
promesse de caviardage : s'il surligne ce que le backend ne touchera pas,
l'utilisateur reçoit un export réussi avec la donnée en clair, et l'audit ne le
rattrape pas puisqu'il rejoue le même détecteur.

Deux langages ne se testent pas dans le même processus. Le contrat passe donc par
un fichier commis que **les deux suites vérifient** : ce test-ci le confronte au
backend, `phonePreview.test.ts` le confronte au frontend. Une dérive d'un côté ou
de l'autre fait échouer l'une des deux.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import redactpdf.presets as presets_module
from redactpdf.presets import _phone_post_filter

FIXTURE = Path(__file__).parents[2] / "frontend" / "src" / "utils" / "phoneParity.fixture.json"


def _cases() -> list[dict[str, object]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return list(data["cases"])


@pytest.mark.unit
def test_fixture_exists_and_is_not_trivial() -> None:
    """Un corpus vide ou tout à False passerait les deux suites sans rien prouver."""
    cases = _cases()
    assert len(cases) >= 40
    redacted = sum(1 for c in cases if c["redacted"])
    assert 0 < redacted < len(cases), "le corpus doit contenir les deux réponses"
    assert {c["region"] for c in cases} >= {"FR", "US"}


@pytest.mark.unit
def test_backend_still_agrees_with_the_committed_corpus() -> None:
    """Si le filtre change, ce test tombe et oblige à régénérer, donc à revoir le frontend."""
    original = presets_module.DEFAULT_REGION
    mismatches: list[str] = []
    try:
        for case in _cases():
            presets_module.DEFAULT_REGION = str(case["region"])
            got = bool(_phone_post_filter(str(case["candidate"])))
            if got is not bool(case["redacted"]):
                mismatches.append(
                    f"{case['candidate']!r} en {case['region']} : "
                    f"corpus={case['redacted']} backend={got}"
                )
    finally:
        presets_module.DEFAULT_REGION = original

    assert not mismatches, "\n".join(mismatches)


@pytest.mark.unit
def test_the_region_actually_changes_the_answer() -> None:
    """Sinon le corpus ne testerait qu'une moitié de la logique.

    Un numéro américain écrit sans indicatif est caviardé en région US et pas en
    région FR : c'est exactement l'asymétrie qui rend la région porteuse.
    """
    by_candidate: dict[str, dict[str, bool]] = {}
    for case in _cases():
        by_candidate.setdefault(str(case["candidate"]), {})[str(case["region"])] = bool(
            case["redacted"]
        )

    differing = [c for c, r in by_candidate.items() if r.get("FR") != r.get("US")]
    assert differing, "aucun candidat ne distingue les deux régions"
