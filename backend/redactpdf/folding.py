"""Le repliage des caractères, et la seule définition de cette règle.

Pourquoi ce module existe
-------------------------
Elle existait en **quatre** copies : deux dans `audit.py`, deux dans
`multiline_regex_engine.py`. Toutes portaient la même faute sur les ligatures, et
n'en corriger qu'une a produit exactement ce qu'une règle dupliquée produit
toujours : la recherche disait « rien trouvé » pendant que l'audit disait
« la cible a survécu », sur un document qui ne contenait ni l'une ni l'autre.
Export refusé pour un mot qui n'était pas le mot cherché.

C'est la leçon déjà écrite pour l'aperçu téléphone, appliquée au moteur : deux
implémentations de la même sémantique dérivent, la seule question est quand.

Ce que la règle dit
-------------------
Un caractère replié rend **un** caractère. C'est la propriété dont dépendent les
index qui retrouvent les boîtes de glyphes : un décalage caviarderait les mauvais
glyphes plutôt que davantage de glyphes. `tests/test_properties.py` la vérifie
sur tout Unicode avec hypothesis.

Un caractère dont la décomposition contient **plusieurs** lettres est donc rendu
tel quel, faute de pouvoir le développer sans casser la longueur. C'est le cas
des ligatures typographiques (« ﬃ » se décompose en « ffi ») et des lettres
soudées. Garder la première lettre, comme le faisaient les quatre copies,
transformait « Griﬃth » en « Grifth » : la requête « Griffith » ne correspondait
plus, ni pour la règle ni pour l'audit, et l'export partait en 200 avec le nom
lisible à l'écran. Mesuré le 9 septembre 2026.

L'élargissement se fait donc côté **motif**, dans `audit.escape_literal`, où une
alternance peut faire correspondre plusieurs lettres tapées à un seul glyphe.
"""
from __future__ import annotations

import unicodedata


def fold_char(ch: str) -> str:
    """Replie un caractère en un caractère, accents retirés, ligatures gardées."""
    decomp = unicodedata.normalize("NFKD", ch)
    bases = [c for c in decomp if not unicodedata.combining(c)]
    if len(bases) > 1:
        return ch
    return bases[0] if bases else ch


def fold_keep_len(s: str) -> str:
    """Replie une chaîne en conservant sa longueur, caractère pour caractère."""
    return "".join(fold_char(ch) for ch in s or "")
