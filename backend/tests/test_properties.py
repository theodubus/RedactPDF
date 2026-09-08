"""Invariants vérifiés sur des entrées engendrées, pas sur des exemples choisis.

Deux fonctions du paquet portent une propriété dont tout le reste dépend, et que
des cas écrits à la main ne peuvent pas couvrir : leur espace d'entrée est
Unicode entier, et les contre-exemples intéressants sont précisément ceux
auxquels personne ne pense.
"""
from __future__ import annotations

import regex
from hypothesis import given, settings
from hypothesis import strategies as st

from redactpdf.audit import _fold_keep_len, build_whole_word_pattern

# Lettres et chiffres de toutes les écritures : c'est là que vivent les pièges
# du repliage (marques combinantes, ligatures, formes précomposées).
_UNICODE_TEXT = st.text(
    alphabet=st.characters(
        categories=["Lu", "Ll", "Lt", "Lm", "Lo", "Nd", "Nl", "No", "Mn", "Mc", "Pd", "Po", "Zs"]
    ),
    max_size=40,
)

# Pour les frontières de mot : un jeton fait uniquement de caractères que le
# moteur considère comme des caractères de mot. La propriété n'a de sens que sur
# cette classe : sur un jeton qui commence par un point, « collé à un mot » et
# « isolé » ne se distinguent plus.
_WORD_CHAR = st.characters(categories=["Lu", "Ll", "Lt", "Lm", "Lo", "Nd"]).filter(
    lambda c: regex.fullmatch(r"\w", c) is not None
)
_WORD_TOKEN = st.text(alphabet=_WORD_CHAR, min_size=1, max_size=20)


@settings(max_examples=500)
@given(_UNICODE_TEXT)
def test_accent_folding_preserves_length(s: str) -> None:
    """Le repliage doit rendre exactement autant de caractères qu'il en reçoit.

    C'est l'invariant dont dépend toute la cartographie span -> rectangle : le
    texte est apparié caractère par caractère à une liste de boîtes de glyphes
    extraites de la page. Un décalage d'un seul cran ne caviarde pas *plus*, il
    caviarde *ailleurs* : la donnée visée reste visible et une donnée voisine
    est détruite, sans le moindre message.

    La version naïve (NFKD puis retrait des marques combinantes) échoue dès la
    première ligature : « ﬁ » est un caractère et en rend deux.
    """
    assert len(_fold_keep_len(s)) == len(s)


@settings(max_examples=500)
@given(_UNICODE_TEXT)
def test_accent_folding_is_idempotent(s: str) -> None:
    """Replier deux fois ne doit pas différer de replier une fois.

    L'audit et le moteur replient chacun de leur côté. S'ils ne convergeaient
    pas au même point fixe, une correspondance trouvée par l'un serait invisible
    à l'autre.
    """
    once = _fold_keep_len(s)
    assert _fold_keep_len(once) == once


@given(_WORD_TOKEN)
def test_whole_word_pattern_matches_the_token_standing_alone(token: str) -> None:
    """Le motif mot-entier doit trouver son jeton isolé, et entouré d'espaces."""
    pat = regex.compile(build_whole_word_pattern(token))

    assert pat.search(token) is not None
    assert pat.search(f" {token} ") is not None


@given(_WORD_TOKEN)
def test_whole_word_pattern_refuses_the_token_glued_inside_a_word(token: str) -> None:
    """Et il ne doit pas le trouver collé à un caractère de mot.

    C'est la propriété qui justifie le défaut `whole_word=True` : sans elle, une
    règle « Dupont » emporte « Dupontel », le nom de quelqu'un d'autre.
    """
    pat = regex.compile(build_whole_word_pattern(token))

    assert pat.search(f"x{token}") is None
    assert pat.search(f"{token}x") is None
    assert pat.search(f"x{token}x") is None


@given(_WORD_TOKEN)
def test_whole_word_pattern_still_crosses_punctuation(token: str) -> None:
    """La ponctuation doit rester une frontière, pas un obstacle.

    C'est ce qui rend le défaut mot-entier tenable plutôt que fuyant : sans
    cela, une recherche « Dupont » ne trouverait plus rien dans
    « jean.dupont@example.com » ni dans « Dupont-Martin ».
    """
    pat = regex.compile(build_whole_word_pattern(token))

    for glued in (f".{token}@", f"-{token}-", f"'{token}'", f"({token})"):
        assert pat.search(glued) is not None, glued
