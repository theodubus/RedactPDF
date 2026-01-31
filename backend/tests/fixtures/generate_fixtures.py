from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import reportlab.rl_config  # type: ignore
from PIL import Image  # type: ignore
from reportlab.lib.pagesizes import A4  # type: ignore
from reportlab.lib.units import mm  # type: ignore
from reportlab.lib.utils import ImageReader  # type: ignore
from reportlab.pdfgen import canvas  # type: ignore

# ---------------------------------------------------------------------------
# Determinism
# ReportLab can embed timestamps/IDs; invariant mode makes outputs repeatable.
# ---------------------------------------------------------------------------
reportlab.rl_config.invariant = 1  # repeatable PDFs for regression testing

SECRET = "SECRET_ABC123"

ROOT_DIR = Path(__file__).resolve().parent
GENERATED_DIR = ROOT_DIR / "generated"


@dataclass(frozen=True)
class FixtureSpec:
    filename: str
    writer: Callable[[Path], None]
    description: str


def _new_canvas(path: Path) -> canvas.Canvas:
    c = canvas.Canvas(str(path), pagesize=A4)
    # Set stable metadata (still keep invariant mode enabled).
    c.setTitle("pdf-redaction-test-fixture")
    c.setAuthor("pdf-redaction-test-suite")
    c.setSubject("deterministic fixtures for regression testing")
    return c


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def write_001_secret_text(path: Path) -> None:
    c = _new_canvas(path)
    _, h = A4
    c.setFont("Helvetica", 14)
    c.drawString(25 * mm, h - 30 * mm, "Fixture 001 — secret text")
    c.setFont("Helvetica", 12)
    c.drawString(25 * mm, h - 45 * mm, f"Le secret à supprimer est : {SECRET}")
    c.drawString(25 * mm, h - 60 * mm, "Texte non sensible : Bonjour le monde.")
    c.showPage()
    c.save()


def write_002_email_phone_one_line(path: Path) -> None:
    c = _new_canvas(path)
    _, h = A4
    c.setFont("Helvetica", 14)
    c.drawString(25 * mm, h - 30 * mm, "Fixture 002 — email + phone (one line)")
    c.setFont("Helvetica", 12)
    c.drawString(25 * mm, h - 50 * mm, "Contact: john.doe@example.com — Tel: 06 12 34 56 78")
    c.drawString(25 * mm, h - 70 * mm, "Texte non sensible : référence ABC-999.")
    c.showPage()
    c.save()


def write_003_phone_two_lines(path: Path) -> None:
    c = _new_canvas(path)
    _, h = A4
    c.setFont("Helvetica", 14)
    c.drawString(25 * mm, h - 30 * mm, "Fixture 003 — phone split across lines")
    c.setFont("Helvetica", 12)
    c.drawString(25 * mm, h - 50 * mm, "Téléphone :")
    c.drawString(25 * mm, h - 60 * mm, "06 12 34")
    c.drawString(25 * mm, h - 70 * mm, "56 78")
    c.drawString(25 * mm, h - 90 * mm, "Texte non sensible : ticket 12345.")
    c.showPage()
    c.save()


def write_004_bitmap_image(path: Path) -> None:
    c = _new_canvas(path)
    _, h = A4
    c.setFont("Helvetica", 14)
    c.drawString(25 * mm, h - 30 * mm, "Fixture 004 — bitmap image + text")
    c.setFont("Helvetica", 12)
    label = "Texte : IMAGE_TEST — la zone image doit pouvoir être redigée."
    c.drawString(25 * mm, h - 50 * mm, label)

    # Create a deterministic bitmap in memory (no external file, no base64).
    im = Image.new("RGB", (64, 64), (255, 0, 0))  # solid red square
    buf = BytesIO()
    im.save(buf, format="PNG", optimize=False)
    buf.seek(0)

    img = ImageReader(buf)

    # Draw bitmap image at a known location
    x = 25 * mm
    y = h - 110 * mm
    c.drawImage(img, x, y, width=30 * mm, height=30 * mm, mask=None)

    # Add a label near image to help manual alignment in future UI tests
    c.setFont("Helvetica", 10)
    c.drawString(x, y - 5 * mm, "Bitmap: red square 30mm x 30mm")

    c.showPage()
    c.save()


def write_005_vector_graphics_and_text(path: Path) -> None:
    c = _new_canvas(path)
    _, h = A4
    c.setFont("Helvetica", 14)
    c.drawString(25 * mm, h - 30 * mm, "Fixture 005 — vector graphics + text")

    # Vector shapes
    c.setLineWidth(2)
    c.rect(25 * mm, h - 90 * mm, 60 * mm, 30 * mm, stroke=1, fill=0)
    c.circle(120 * mm, h - 75 * mm, 15 * mm, stroke=1, fill=0)
    c.line(25 * mm, h - 100 * mm, 160 * mm, h - 120 * mm)

    c.setFont("Helvetica", 12)
    label = "Texte proche des formes : VECTOR_TEST — à rediger si besoin."
    c.drawString(25 * mm, h - 140 * mm, label)

    c.showPage()
    c.save()


def write_006_two_columns_text(path: Path) -> None:
    c = _new_canvas(path)
    _, h = A4
    c.setFont("Helvetica", 14)
    c.drawString(25 * mm, h - 30 * mm, "Fixture 006 — two columns layout")

    c.setFont("Helvetica", 11)
    left_x = 25 * mm
    right_x = 110 * mm
    top_y = h - 50 * mm

    # Left column
    c.drawString(left_x, top_y, "Colonne gauche :")
    c.drawString(left_x, top_y - 10 * mm, "Alpha 111")
    c.drawString(left_x, top_y - 20 * mm, "Bravo 222")
    c.drawString(left_x, top_y - 30 * mm, "Charlie 333")

    # Right column
    c.drawString(right_x, top_y, "Colonne droite :")
    c.drawString(right_x, top_y - 10 * mm, "Delta 444")
    c.drawString(right_x, top_y - 20 * mm, "Echo 555")
    c.drawString(right_x, top_y - 30 * mm, "Foxtrot 666")

    c.setFont("Helvetica", 10)
    c.drawString(25 * mm, 20 * mm, "Note: fixture used to test line/column heuristics later.")

    c.showPage()
    c.save()


def write_007_whole_word_cat_catch(path: Path) -> None:
    """
    Fixture used to test whole_word behavior:
    - query "CAT" with whole_word=True must not redact the "CAT" substring inside "CATCH".
    """
    c = _new_canvas(path)
    _, h = A4
    c.setFont("Helvetica", 14)
    c.drawString(25 * mm, h - 30 * mm, "Fixture 007 — whole word CAT vs CATCH")

    c.setFont("Helvetica", 12)
    c.drawString(25 * mm, h - 55 * mm, "Standalone token: CAT")
    c.drawString(25 * mm, h - 75 * mm, "Substring token: CATCH")
    c.drawString(25 * mm, h - 95 * mm, "Texte non sensible : OK.")

    c.showPage()
    c.save()


SPECS: list[FixtureSpec] = [
    FixtureSpec(
        filename="001_secret_text.pdf",
        writer=write_001_secret_text,
        description="Simple text containing SECRET_ABC123",
    ),
    FixtureSpec(
        filename="002_email_phone_one_line.pdf",
        writer=write_002_email_phone_one_line,
        description="Email + phone on one line",
    ),
    FixtureSpec(
        filename="003_phone_two_lines.pdf",
        writer=write_003_phone_two_lines,
        description="Phone split across two lines",
    ),
    FixtureSpec(
        filename="004_bitmap_image.pdf",
        writer=write_004_bitmap_image,
        description="Bitmap image embedded + text",
    ),
    FixtureSpec(
        filename="005_vector_graphics_and_text.pdf",
        writer=write_005_vector_graphics_and_text,
        description="Vector shapes + text",
    ),
    FixtureSpec(
        filename="006_two_columns_text.pdf",
        writer=write_006_two_columns_text,
        description="Two columns layout",
    ),
    FixtureSpec(
        filename="007_whole_word_cat_catch.pdf",
        writer=write_007_whole_word_cat_catch,
        description='Whole word test fixture ("CAT" vs "CATCH")',
    ),
]


def generate_all(output_dir: Path = GENERATED_DIR) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []
    for spec in SPECS:
        out_path = output_dir / spec.filename
        spec.writer(out_path)
        out_paths.append(out_path)
    return out_paths


def print_manifest(paths: list[Path]) -> None:
    print("Generated fixtures:")
    for p in paths:
        print(f"- {p.name}  sha256={_sha256(p)}  bytes={p.stat().st_size}")


if __name__ == "__main__":
    paths = generate_all()
    print_manifest(paths)
