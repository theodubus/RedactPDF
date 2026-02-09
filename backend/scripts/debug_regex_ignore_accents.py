from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

from app.multiline_regex_engine import iter_regex_hits


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.debug_regex_ignore_accents <pdf_path>")
        return 2

    pdf_path = Path(sys.argv[1])
    pdf_bytes = pdf_path.read_bytes()

    # Mets ici exactement les patterns que tu testes dans l'UI
    patterns_to_try = [
        ["Theo"],   # ascii -> doit matcher accentué si ignore_accents
        ["Dûbus"],  # accentué -> doit matcher ascii si ignore_accents
        ["Dubus"],  # ascii -> doit matcher accentué si ignore_accents
    ]

    for pats in patterns_to_try:
        print("\n=== PATTERNS:", pats, "===")
        hits = list(
            iter_regex_hits(
                pdf_bytes,
                pats,
                case_sensitive=False,
                multiline=False,
                ignore_accents=True,
            )
        )
        print("hits:", len(hits))
        for h in hits[:10]:
            print(
                f"- page={h.page+1} kind={h.kind} match={h.match!r} "
                f"rects={[(r.x0, r.y0, r.x1, r.y1) for r in h.rects]}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
