from __future__ import annotations

import sys
from pathlib import Path

# Nom du répertoire de données où l'UI construite est embarquée dans la roue.
# `scripts/build_app.py` l'y recopie depuis `frontend/dist` avant la
# construction du paquet ; il est ignoré par git.
_PACKAGE_UI_DIR = "_frontend"

# Données de langue Tesseract embarquées. Contrairement à l'UI, ce ne sont pas
# des produits de construction mais des ressources versionnées : elles vivent
# dans le paquet, donc le dépôt source et la roue installée partagent le même
# chemin, et seul le gel PyInstaller en diffère.
_PACKAGE_TESSDATA_DIR = "_tessdata"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than a source checkout."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def is_source_checkout() -> bool:
    """True quand le paquet tourne depuis le dépôt, pas depuis une installation.

    On teste `frontend/package.json`, qui est versionné, et non `frontend/dist`,
    qui est un produit de construction : le marqueur doit rester vrai même quand
    l'UI n'a pas encore été construite.
    """
    return (Path(__file__).resolve().parents[2] / "frontend" / "package.json").is_file()


def frontend_dist() -> Path:
    """Directory holding the built UI.

    Trois dispositions possibles, et aucune ne se déduit de `__file__` seul :

    - **Bundle PyInstaller** : la copie embarquée à la construction, sous le même
      nom relatif dans le répertoire d'extraction (``sys._MEIPASS``). Résoudre
      depuis ``__file__`` échouerait, le code vivant alors dans un arbre
      temporaire et non dans le dépôt.
    - **Dépôt source** : ``<repo>/frontend/dist``, produit par ``npm run build``.
    - **Paquet installé** (roue depuis PyPI) : ``<paquet>/_frontend``, où
      ``frontend/dist`` a été recopié au moment de construire la distribution.

    Le dépôt source est testé avant le paquet : sur une machine de développement
    qui a déjà construit une roue, un ``_frontend`` périmé ne doit jamais
    masquer le ``frontend/dist`` fraîchement reconstruit.

    Quand aucune des dispositions n'aboutit, on renvoie le candidat le plus
    plausible pour le mode courant, afin que l'appelant puisse afficher un
    message d'erreur qui nomme le chemin attendu.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle is not None:
        return Path(bundle) / "frontend" / "dist"

    here = Path(__file__).resolve()

    repo = here.parents[2] / "frontend" / "dist"
    if (repo / "index.html").is_file():
        return repo

    packaged = here.parent / _PACKAGE_UI_DIR
    if (packaged / "index.html").is_file():
        return packaged

    return repo


def bundled_tessdata() -> Path | None:
    """Les données de langue embarquées, ou None si elles manquent.

    Le moteur d'OCR est déjà dans PyMuPDF (vérifié en cachant le binaire
    `tesseract` : la reconnaissance continue de marcher). Seules les données de
    langue manquaient, et elles pèsent 5 Mo pour `fra` et `eng`, pas les 22 Mo du
    paquet système que j'avais mesurés à tort. À ce prix-là, obliger un
    utilisateur non technique à lancer un `apt install` pour une application
    livrée en un fichier n'avait aucune justification.

    Rend None plutôt que de lever : l'absence est un cas normal (dépôt sans les
    fichiers), et `ocr.py` retombe alors sur un Tesseract système.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle is not None:
        frozen = Path(bundle) / "redactpdf" / _PACKAGE_TESSDATA_DIR
        return frozen if _has_language_data(frozen) else None

    packaged = Path(__file__).resolve().parent / _PACKAGE_TESSDATA_DIR
    return packaged if _has_language_data(packaged) else None


def _has_language_data(directory: Path) -> bool:
    """Un répertoire vide ne vaut pas mieux qu'un répertoire absent.

    Tesseract lit `<langue>.traineddata` dans le dossier qu'on lui donne ; lui en
    désigner un qui n'en contient aucun échouerait à l'export au lieu de laisser
    le repli système jouer.
    """
    try:
        return any(directory.glob("*.traineddata"))
    except OSError:
        return False
