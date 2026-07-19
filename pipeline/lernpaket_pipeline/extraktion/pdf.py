"""PDF-Extraktion: Textebene auslesen, Scan erkennen, OCR-Fallback (Issue #30, ADR 0004).

Der Erkennungsschritt läuft pro Seite: Hat die Seite eine brauchbare Textebene,
wird sie direkt ausgelesen; sonst gilt sie als Scan und läuft durch die OCR.
Die OCR selbst ist ein austauschbarer Adapter — Tesseract als reale
Implementierung, in Tests eine Fake-OCR (PRD: Extraktion deterministisch testbar).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol

from pypdf import PdfReader

# Unterhalb dieser Zeichenzahl gilt die Textebene einer Seite als unbrauchbar
# (reine Scans liefern oft 0–20 Zeichen Artefakte).
MIN_TEXTEBENE_ZEICHEN = 25


@dataclass
class Seite:
    nummer: int  # 1-basiert
    text: str
    ist_scan: bool = False


class Ocr(Protocol):
    """Volltext-OCR für eine einzelne PDF-Seite ohne Textebene."""

    def lese_seite(self, pdf: Path, seitennummer: int) -> str: ...


class TesseractOcr:
    """Reale OCR via pdf2image + pytesseract (optional installierbar: extra 'ocr')."""

    def __init__(self, sprache: str = "deu"):
        self.sprache = sprache

    def lese_seite(self, pdf: Path, seitennummer: int) -> str:
        try:
            import pytesseract  # type: ignore
            from pdf2image import convert_from_path  # type: ignore
        except ImportError as exc:  # pragma: no cover - abhängig von Umgebung
            raise RuntimeError(
                "OCR-Fallback benötigt die Extras 'ocr' (pip install "
                "'lernpaket-pipeline[ocr]') sowie tesseract und poppler."
            ) from exc
        bilder = convert_from_path(str(pdf), first_page=seitennummer, last_page=seitennummer)
        return pytesseract.image_to_string(bilder[0], lang=self.sprache)


def hat_textebene(seite_text: str) -> bool:
    return len(seite_text.strip()) >= MIN_TEXTEBENE_ZEICHEN


def lies_pdf(pfad: Path, ocr: Optional[Ocr] = None) -> List[Seite]:
    """Liest alle Seiten; Scan-Seiten laufen durch die OCR, falls eine da ist.

    Ohne OCR bleibt eine Scan-Seite leer, aber markiert (`ist_scan=True`) —
    die Pipeline meldet das später als Materiallücke statt still zu schlucken.
    """
    pfad = Path(pfad)
    reader = PdfReader(str(pfad))
    seiten: List[Seite] = []
    for i, pdf_seite in enumerate(reader.pages, start=1):
        text = pdf_seite.extract_text() or ""
        if hat_textebene(text):
            seiten.append(Seite(nummer=i, text=text, ist_scan=False))
        else:
            ocr_text = ocr.lese_seite(pfad, i) if ocr is not None else ""
            seiten.append(Seite(nummer=i, text=ocr_text, ist_scan=True))
    return seiten


def ist_scan_pdf(pfad: Path) -> bool:
    """True, wenn das PDF überwiegend keine brauchbare Textebene hat."""
    reader = PdfReader(str(pfad))
    if not reader.pages:
        return False
    ohne_text = sum(
        1 for s in reader.pages if not hat_textebene(s.extract_text() or "")
    )
    return ohne_text > len(reader.pages) / 2
