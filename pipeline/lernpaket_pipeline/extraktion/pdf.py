"""PDF-Extraktion: Textebene auslesen, Scan erkennen, OCR-Fallback (Issue #30, ADR 0004).

Der Erkennungsschritt läuft pro Seite: Hat die Seite eine brauchbare Textebene,
wird sie direkt ausgelesen; sonst gilt sie als Scan und läuft durch die OCR.
Liefert die Textebene verklebten Text (Wortzwischenräume nur als Kerning
kodiert, pypdf verliert die Leerzeichen), rekonstruiert ein Zweitextraktor
(pdfminer.six) die Wortgrenzen aus den Glyphen-Positionen.
Beide Werkzeuge sind austauschbare Adapter — in Tests Fakes (PRD: Extraktion
deterministisch testbar).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from pypdf import PdfReader

# Unterhalb dieser Zeichenzahl gilt die Textebene einer Seite als unbrauchbar
# (reine Scans liefern oft 0–20 Zeichen Artefakte).
MIN_TEXTEBENE_ZEICHEN = 25
# Wörter oberhalb dieser Länge sind im Deutschen fast immer zusammengeklebte
# Wortfolgen; URLs und Formeln werden gesondert behandelt.
MAX_WORTLAENGE = 25


@dataclass
class Seite:
    nummer: int  # 1-basiert
    text: str
    ist_scan: bool = False


class Ocr(Protocol):
    """Volltext-OCR für eine einzelne PDF-Seite ohne Textebene."""

    def lese_seite(self, pdf: Path, seitennummer: int) -> str: ...


class TesseractOcr:
    """Reale OCR: PyMuPDF rendert die Seite (pip-only), tesseract erkennt den Text.

    Optional installierbar über das Extra 'ocr'. Einzige System-Abhängigkeit ist
    die OCR-Engine tesseract (mit deutschen Sprachdaten); das PDF-Rendering
    braucht dank PyMuPDF kein poppler mehr.
    """

    def __init__(self, sprache: str = "deu", dpi: int = 300):
        self.sprache = sprache
        self.dpi = dpi

    def lese_seite(self, pdf: Path, seitennummer: int) -> str:
        try:
            import pytesseract  # type: ignore
            import fitz  # type: ignore  # PyMuPDF
            from PIL import Image  # type: ignore
        except ImportError as exc:  # pragma: no cover - abhängig von Umgebung
            raise RuntimeError(
                "OCR-Fallback benötigt die Extras 'ocr' (pip install "
                "'lernpaket-pipeline[ocr]') sowie die System-Engine tesseract "
                "mit deutschen Sprachdaten."
            ) from exc
        with fitz.open(str(pdf)) as dokument:
            pix = dokument[seitennummer - 1].get_pixmap(dpi=self.dpi)  # 0-basiert
            bild = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return pytesseract.image_to_string(bild, lang=self.sprache)


def hat_textebene(seite_text: str) -> bool:
    return len(seite_text.strip()) >= MIN_TEXTEBENE_ZEICHEN


def _ueberlange_woerter(text: str) -> List[str]:
    return [w for w in text.split()
            if len(w) > MAX_WORTLAENGE and "://" not in w and "www." not in w]


def ist_verklebt(text: str) -> bool:
    """True, wenn der Textebene die Wortzwischenräume fehlen.

    Erkennungsmerkmal sind gehäufte überlange "Wörter" ("InAbb.1.16werden…").
    Einzelne lange Tokens (Komposita, Formeln) lösen nicht aus.
    """
    woerter = text.split()
    if len(woerter) < 5:
        return False
    ueberlang = _ueberlange_woerter(text)
    return len(ueberlang) >= 3 or len(ueberlang) / len(woerter) > 0.1


class Zweitextraktor(Protocol):
    """Positions-basierte Nachextraktion einzelner Seiten (1-basierte Nummern)."""

    def lies_seiten(self, pfad: Path, nummern: List[int]) -> Dict[int, str]: ...


class PdfMinerExtraktor:
    """Zweitextraktion via pdfminer.six — rekonstruiert Leerzeichen aus
    Glyphen-Abständen, wo pypdf nur verklebten Text liefert."""

    def lies_seiten(self, pfad: Path, nummern: List[int]) -> Dict[int, str]:
        try:
            from pdfminer.high_level import extract_text  # type: ignore
        except ImportError:  # pragma: no cover - Abhängigkeit fehlt
            return {}
        # pdfminer warnt lautstark über Grafik-Details, die es nicht versteht
        # (z. B. Musterfarben: "Cannot set gray non-stroke color … /'p5'").
        # Für die Textextraktion ist das irrelevant — nur echte Fehler zeigen.
        import logging
        logging.getLogger("pdfminer").setLevel(logging.ERROR)
        nummern = sorted(set(nummern))
        text = extract_text(str(pfad), page_numbers=[n - 1 for n in nummern])
        teile = text.split("\f")
        if teile and not teile[-1].strip():
            teile = teile[:-1]
        if len(teile) != len(nummern):  # pragma: no cover - defensiver Einzelabruf
            return {n: extract_text(str(pfad), page_numbers=[n - 1]) for n in nummern}
        return dict(zip(nummern, teile))


def lies_pdf(pfad: Path, ocr: Optional[Ocr] = None,
             zweitextraktor: Optional[Zweitextraktor] = None) -> List[Seite]:
    """Liest alle Seiten; Scan-Seiten laufen durch die OCR, falls eine da ist.

    Ohne OCR bleibt eine Scan-Seite leer, aber markiert (`ist_scan=True`) —
    die Pipeline meldet das später als Materiallücke statt still zu schlucken.
    Seiten mit verklebtem Text werden mit dem Zweitextraktor (Default:
    pdfminer.six) nachextrahiert; übernommen wird nur ein besseres Ergebnis.
    Was danach verklebt bleibt, meldet die Pipeline als Materiallücke.
    """
    from ..fortschritt import balken

    pfad = Path(pfad)
    reader = PdfReader(str(pfad))
    seiten: List[Seite] = []
    # Balken über die Seiten — bei Scan-Seiten (OCR) verweilt er sichtbar länger.
    bar = balken(total=len(reader.pages), desc=f"PDF {pfad.name}", unit="Seite")
    for i, pdf_seite in enumerate(reader.pages, start=1):
        text = pdf_seite.extract_text() or ""
        if hat_textebene(text):
            seiten.append(Seite(nummer=i, text=text, ist_scan=False))
        else:
            ocr_text = ocr.lese_seite(pfad, i) if ocr is not None else ""
            seiten.append(Seite(nummer=i, text=ocr_text, ist_scan=True))
        bar.update(1)
    bar.close()

    verklebte = [s.nummer for s in seiten if not s.ist_scan and ist_verklebt(s.text)]
    if verklebte:
        ersatz = (zweitextraktor or PdfMinerExtraktor()).lies_seiten(pfad, verklebte)
        for nummer, text in ersatz.items():
            alte = seiten[nummer - 1]
            if (hat_textebene(text)
                    and len(_ueberlange_woerter(text)) < len(_ueberlange_woerter(alte.text))):
                seiten[nummer - 1] = Seite(nummer=nummer, text=text, ist_scan=False)
    return seiten


def seiten_mit_bildern(pfad: Path) -> List[int]:
    """1-basierte Nummern der Seiten mit eingebetteten Bildern (Image-XObjects).

    Zählt ohne Dekodierung (kein Pillow nötig). Grundlage für die Meldung, dass
    Abbildungen/Diagramme von der Text-Extraktion nicht erfasst werden.
    """
    reader = PdfReader(str(pfad))
    nummern: List[int] = []
    for i, seite in enumerate(reader.pages, start=1):
        try:
            ressourcen = seite.get("/Resources")
            if ressourcen is None:
                continue
            xobjekte = ressourcen.get_object().get("/XObject")
            if xobjekte is None:
                continue
            if any(x.get_object().get("/Subtype") == "/Image"
                   for x in xobjekte.get_object().values()):
                nummern.append(i)
        except Exception:  # defektes Objekt: lieber keine Meldung als Abbruch
            continue
    return nummern


def ist_scan_pdf(pfad: Path) -> bool:
    """True, wenn das PDF überwiegend keine brauchbare Textebene hat."""
    reader = PdfReader(str(pfad))
    if not reader.pages:
        return False
    ohne_text = sum(
        1 for s in reader.pages if not hat_textebene(s.extract_text() or "")
    )
    return ohne_text > len(reader.pages) / 2
