"""Exécution des motifs fournis par l'utilisateur, sous budget de temps.

Pourquoi ce module existe
-------------------------
`re` peut partir en retour arrière catastrophique sur des motifs anodins en
apparence : `(a|a)+$` contre 28 caractères occupe 48 secondes, et la courbe est
exponentielle. Pire, `re` ne relâche pas le GIL pendant le parcours : un seul
motif fige le processus entier, boucle d'événements comprise. Un délai posé
dans un thread ne servirait donc à rien -- il n'y aurait personne pour
l'observer.

Le paquet `regex` répond aux deux problèmes : il encaisse nativement plusieurs
formes catastrophiques, et il accepte un `timeout` qu'il vérifie pendant le
parcours. Son mode V0 est compatible avec `re`, ce qui est la raison de ne pas
avoir changé la sémantique des règles existantes en chemin.

Budget partagé, pas délai par appel
-----------------------------------
Le moteur exécute chaque motif ligne par ligne, page par page. Un délai posé
sur chaque appel serait multiplié par le nombre de lignes : sur un document de
cent pages, « deux secondes » deviendraient une heure. Le budget est donc
consommé par une requête entière, et chaque parcours ne reçoit que ce qu'il
reste.
"""
from __future__ import annotations

import os
import time
from collections.abc import Iterator, Sequence

import regex

DEFAULT_TIMEOUT_SECONDS = 10.0


class RegexTimeout(ValueError):
    """Le budget de temps a été épuisé.

    Hérite de `ValueError` pour rejoindre le traitement d'erreur déjà en place :
    l'API répond 400 avec le message, au lieu de rester muette pendant que le
    processus tourne.
    """


def default_timeout_seconds() -> float:
    """Budget par requête, en secondes. Réglable par `REDACT_REGEX_TIMEOUT`."""
    raw = os.getenv("REDACT_REGEX_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


class RegexBudget:
    """Temps total accordé aux motifs d'une même requête.

    Le compte à rebours démarre au premier parcours, pas à la construction :
    le budget mesure le temps passé dans les motifs, pas celui passé à ouvrir
    le PDF ou à en extraire le texte.
    """

    def __init__(self, seconds: float | None = None) -> None:
        self.total = seconds if seconds is not None else default_timeout_seconds()
        self._deadline: float | None = None

    def remaining(self) -> float:
        if self._deadline is None:
            self._deadline = time.monotonic() + self.total
        left = self._deadline - time.monotonic()
        if left <= 0.0:
            raise RegexTimeout(
                f"Regex execution exceeded its {self.total:g}s budget. "
                "A pattern is backtracking catastrophically; simplify it "
                "(nested quantifiers such as (a+)+ are the usual cause)."
            )
        return left


def compile_pattern(pattern: str, *, ignore_case: bool) -> regex.Pattern[str]:
    flags = regex.V0 | (regex.IGNORECASE if ignore_case else 0)
    try:
        return regex.compile(pattern, flags=flags)
    except regex.error as e:
        raise ValueError(f"invalid regex pattern: {pattern}") from e


def compile_patterns(
    patterns: Sequence[str], *, ignore_case: bool
) -> list[tuple[str, regex.Pattern[str]]]:
    out: list[tuple[str, regex.Pattern[str]]] = []
    for raw in patterns:
        cleaned = (raw or "").strip()
        if not cleaned:
            continue
        out.append((cleaned, compile_pattern(cleaned, ignore_case=ignore_case)))
    return out


def finditer(
    pattern: regex.Pattern[str], text: str, budget: RegexBudget
) -> Iterator[regex.Match[str]]:
    """Parcourt `text` sous le budget restant.

    Le résultat est matérialisé : `regex` applique le délai à l'itération, et
    une itération paresseuse laisserait le budget courir bien après l'appel.
    """
    try:
        return iter(list(pattern.finditer(text, timeout=budget.remaining())))
    except TimeoutError as e:
        raise RegexTimeout(
            f"Regex execution exceeded its {budget.total:g}s budget while scanning "
            f"with {pattern.pattern!r}. Simplify the pattern; nested quantifiers "
            "such as (a+)+ are the usual cause."
        ) from e
