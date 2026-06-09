#!/usr/bin/env python3
"""Generate a synthetic demo PDF for the README showcase.

A fake invoice with obviously-fake PII (``@example.com``, test card ``4111...``),
a vector logo (graphics-removal demo) and an embedded bitmap "scan" whose text
is NOT selectable (manual-rectangle + 'pixels'/'Precise' mode demo). No real data.

Run:  python scripts/make_demo_pdf.py
Out:  docs/demo-invoice.pdf
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

OUT = Path(__file__).resolve().parent.parent / "docs" / "demo-invoice.pdf"

BLACK = (0, 0, 0)
GREY = (0.35, 0.35, 0.35)
BLUE = (0.16, 0.32, 0.62)


def build_scan_bitmap() -> bytes:
    """A small raster image with baked-in text (simulates a scanned ID card)."""
    scan = pymupdf.open()
    p = scan.new_page(width=320, height=120)
    p.draw_rect(p.rect, color=BLACK, fill=(0.96, 0.95, 0.90))
    p.insert_text((14, 30), "SCANNED ID  (bitmap)", fontsize=12, color=BLACK)
    p.insert_text((14, 58), "Name: Jean Dupont", fontsize=12, color=BLACK)
    p.insert_text((14, 84), "ID No: FR-9988-7766", fontsize=12, color=BLACK)
    png = p.get_pixmap(dpi=150).tobytes("png")
    scan.close()
    return png


def main() -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4 portrait

    # Vector logo dot -> demonstrates graphics removal when a rect touches it.
    page.draw_circle((520, 60), 16, color=BLUE, fill=BLUE)

    # Header (non-sensitive).
    page.insert_text((50, 66), "ACME Analytics SARL", fontsize=22, color=BLUE)
    page.insert_text((50, 92), "INVOICE  #2026-0042      Date: 2026-06-09", fontsize=11, color=GREY)

    # Bill-to block (sensitive -> text selection / email & phone presets).
    y = 150
    for line in [
        "Bill to:  Jean Dupont",
        "Email:    jean.dupont@example.com",
        "Phone:    +33 6 12 34 56 78",
        "Address:  12 Rue de la Paix, 75002 Paris",
    ]:
        page.insert_text((50, y), line, fontsize=12, color=BLACK)
        y += 24

    # Payment (sensitive -> credit-card preset, Luhn-valid test number).
    y += 12
    for line in [
        "Card on file:  4111 1111 1111 1111",
        "Client ref:    CUST-4521",
    ]:
        page.insert_text((50, y), line, fontsize=12, color=BLACK)
        y += 24

    # Line items (non-sensitive -> must REMAIN after redaction).
    y += 24
    page.insert_text((50, y), "Items", fontsize=13, color=BLUE)
    y += 22
    for line in [
        "Consulting services ............ 1 200,00 EUR",
        "Data audit ..................... 800,00 EUR",
        "Total .......................... 2 000,00 EUR",
    ]:
        page.insert_text((60, y), line, fontsize=11, color=BLACK)
        y += 20

    # Embedded bitmap "scan" -> the 'pixels' / 'Precise' mode showcase.
    page.insert_image(pymupdf.Rect(50, 600, 370, 720), stream=build_scan_bitmap())
    page.insert_text(
        (50, 736),
        "Fig. 1 - scanned ID. The text above is a BITMAP (not selectable): use a",
        fontsize=8,
        color=GREY,
    )
    page.insert_text(
        (50, 748),
        "manual rectangle + 'Precise' image mode to actually erase those pixels.",
        fontsize=8,
        color=GREY,
    )

    # Footer (non-sensitive).
    page.insert_text(
        (50, 800),
        "Thank you for your business.  ACME Analytics SARL - demo document, fake data.",
        fontsize=9,
        color=GREY,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT), garbage=4, deflate=True)
    doc.close()
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
