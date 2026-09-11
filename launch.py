#!/usr/bin/env python3
"""Amorce du lanceur RedactPDF pour un dépôt source.

Le lanceur lui-même vit dans le paquet (`redactpdf/launch.py`) : un point
d'entrée console doit pointer vers un module contenu dans la distribution.
Ce fichier ne fait que rendre `backend/` importable sans installation, puis
délègue. Il reste la cible analysée par `packaging/redactpdf.spec`.

    python launch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    # Dépôt source : rendre le paquet importable sans l'installer.
    # Dans un bundle PyInstaller il est déjà sur le chemin d'import gelé.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from redactpdf.launch import run  # noqa: E402  (doit suivre le réglage de sys.path)

if __name__ == "__main__":
    run()
