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

import re
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
            import pymupdf  # type: ignore
            from PIL import Image  # type: ignore
        except ImportError as exc:  # pragma: no cover - abhängig von Umgebung
            raise RuntimeError(
                "OCR-Fallback benötigt die Extras 'ocr' (pip install "
                "'lernpaket-pipeline[ocr]') sowie die System-Engine tesseract "
                "mit deutschen Sprachdaten."
            ) from exc
        with pymupdf.open(str(pdf)) as dokument:
            pix = dokument[seitennummer - 1].get_pixmap(dpi=self.dpi)  # 0-basiert
            bild = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return pytesseract.image_to_string(bild, lang=self.sprache)


def hat_textebene(seite_text: str) -> bool:
    return len(seite_text.strip()) >= MIN_TEXTEBENE_ZEICHEN


# Echtes Kleben zeigt sich an einem Kleinbuchstaben direkt gefolgt von einem
# Großbuchstaben ("werdenMöglichkeiten", "MiniweltTabelle") — im Deutschen ein
# verlässliches Wortgrenzen-Signal, weil Nomen großgeschrieben werden. Lange
# Komposita ("Patientenverwaltungssystem") und Bindestrich-Namen
# ("Friedrich-Alexander-Universität") haben diesen Übergang NICHT und lösen
# damit keinen Fehlalarm mehr aus.
_KLEBE_RE = re.compile(r"[a-zäöüß][A-ZÄÖÜ]")


def _verklebte_woerter(text: str) -> List[str]:
    """Überlange Tokens mit CamelCase-Übergang = tatsächlich zusammengeklebt."""
    return [w for w in text.split()
            if len(w) > MAX_WORTLAENGE and "://" not in w and "www." not in w
            and _KLEBE_RE.search(w)]


def ist_verklebt(text: str) -> bool:
    """True, wenn dem Text die Wortzwischenräume fehlen (echtes Kleben).

    Zählt nur Tokens mit CamelCase-Übergang (s. `_verklebte_woerter`); einzelne
    lange Komposita, Bindestrich-Namen, Formeln und URLs lösen nicht aus.
    """
    woerter = text.split()
    if len(woerter) < 5:
        return False
    geklebt = _verklebte_woerter(text)
    return len(geklebt) >= 2 or len(geklebt) / len(woerter) > 0.05


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
    Verklebte Seiten werden in zwei Stufen repariert: erst der Zweitextraktor
    (Default pdfminer.six), dann — für hartnäckige Fälle wie Diagramm-
    Beschriftungen — die OCR (rendert die Seite und liest sie mit visueller
    Wortgrenze). Übernommen wird jeweils nur ein *weniger* verklebtes Ergebnis;
    was danach verklebt bleibt, meldet die Pipeline als Materiallücke.
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

    def _ersetze_wenn_besser(nummer: int, text: str) -> None:
        alte = seiten[nummer - 1]
        if (hat_textebene(text)
                and len(_verklebte_woerter(text)) < len(_verklebte_woerter(alte.text))):
            seiten[nummer - 1] = Seite(nummer=nummer, text=text, ist_scan=False)

    # Stufe 1: Zweitextraktor (pdfminer) rekonstruiert die Wortgrenzen aus Glyphen.
    verklebte = [s.nummer for s in seiten if not s.ist_scan and ist_verklebt(s.text)]
    if verklebte:
        ersatz = (zweitextraktor or PdfMinerExtraktor()).lies_seiten(pfad, verklebte)
        for nummer, text in ersatz.items():
            _ersetze_wenn_besser(nummer, text)

    # Stufe 2: OCR für weiterhin verklebte Seiten (Diagramm-Beschriftungen o. Ä.) —
    # die visuelle Anordnung liefert Wortgrenzen, die der Textebene fehlen.
    if ocr is not None:
        for nummer in [s.nummer for s in seiten if not s.ist_scan and ist_verklebt(s.text)]:
            _ersetze_wenn_besser(nummer, ocr.lese_seite(pfad, nummer))
    return seiten


def seiten_mit_bildern(pfad: Path) -> List[int]:
    """1-basierte Nummern der Seiten mit eingebetteten Bildern (Image-XObjects).

    Zählt ohne Dekodierung (kein Pillow nötig). Erfasst nur Rasterbilder —
    Vektor-Diagramme (die häufigere Form in Studienbriefen) siehe
    `seiten_mit_diagrammen`.
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


# Bildunterschrift am Zeilenanfang ("Abb. 1.1: Titel" / "Abbildung 3.4: …") —
# ein verlässliches Diagramm-Signal in Studienbriefen. Grenzt sich von Inline-
# Verweisen ab ("siehe Abb. 1.1", "in Abb. 1.5"), die nicht am Zeilenanfang mit
# folgendem Doppelpunkt stehen. Die Vektor-Zählung taugt nicht (Dekor-Elemente
# auf fast jeder Seite), Rasterbilder sind hier selten — die Unterschrift ist
# das präzise Signal und liefert zugleich einen Titel.
#
# Der Dokument-Parser (Marker) setzt vor die Unterschrift Markdown- und HTML-
# Dekor — mal eine Überschrift ("## Abb. 2.8: …"), mal einen Sprunganker
# ("<span id=…></span>Abb. 2.9: …"), mal Fettung. Ohne dieses tolerierte Vorspann
# fände die Erkennung auf normalisierten Seiten gar keine Abbildung mehr.
_ABB_VORSPANN = r"^[ \t>]*(?:#{1,6}[ \t]*)?(?:<[^>\n]+>[ \t]*)*[*_]{0,2}[ \t]*"
# Der Lookahead erzwingt die vollständige Nummer: ohne ihn zerfällt der Verweis
# "Abbildung 2.5 veranschaulicht …" in die Nummer "2", den Trenner "." und den
# halben Satz als Titel — der Fließtext landete dann als Bildunterschrift.
_ABB_UNTERSCHRIFT_RE = re.compile(
    _ABB_VORSPANN
    + r"((?:Abb\.|Abbildung)\s*\d+(?:[.,]\d+)*(?![.,]?\d))\s*[:.]\s*(\S[^\n]*)?",
    re.MULTILINE)
# Dekor am Titelende bzw. Inline-Auszeichnung im Titel wieder abräumen.
_ABB_TITEL_DEKOR_RE = re.compile(r"<[^>\n]+>|[*_]{1,2}")


def finde_abbildungen(seiten: List["Seite"]) -> List["tuple[int, str]"]:
    """(Seitennummer, Beschriftung) je Seite mit mindestens einer Bildunterschrift.

    Eine Seite erscheint einmal; mehrere Unterschriften werden im Titel
    zusammengefasst. Die Titel sind durch Zeilenumbruch oft abgeschnitten
    ("Abb. 1.1: Daten und") — als Label dennoch brauchbar.
    """
    ergebnis: List["tuple[int, str]"] = []
    for seite in seiten:
        marken = []
        for m in _ABB_UNTERSCHRIFT_RE.finditer(seite.text):
            nummer = _ABB_TITEL_DEKOR_RE.sub("", m.group(1)).strip()
            titel = _ABB_TITEL_DEKOR_RE.sub("", m.group(2) or "").strip()
            marken.append(f"{nummer}: {titel}".strip().rstrip(":").strip()
                          if titel else nummer)
        if marken:
            ergebnis.append((seite.nummer, " · ".join(dict.fromkeys(marken))))
    return ergebnis


class DiagrammRenderer(Protocol):
    """Rendert eine PDF-Seite als PNG-Bytes."""

    def rendere(self, pdf: Path, seitennummer: int) -> bytes: ...


class PyMuPdfRenderer:
    """Rendert die volle Seite als PNG (PyMuPDF) — zeigt das Diagramm im Kontext.

    Ganzseiten-Rendering statt Zuschnitt: die Studienbriefe haben einen
    Vollseiten-Rahmen, an dem sich eine Diagramm-Bounding-Box nicht zuverlässig
    festmachen lässt; die ganze Seite ist der ehrlichste, robusteste Ausschnitt.
    """

    def __init__(self, dpi: int = 150):
        self.dpi = dpi

    def rendere(self, pdf: Path, seitennummer: int) -> bytes:
        import pymupdf  # type: ignore

        with pymupdf.open(str(pdf)) as dokument:
            pix = dokument[seitennummer - 1].get_pixmap(dpi=self.dpi)  # 0-basiert
            return pix.tobytes("png")


def ist_scan_pdf(pfad: Path) -> bool:
    """True, wenn das PDF überwiegend keine brauchbare Textebene hat."""
    reader = PdfReader(str(pfad))
    if not reader.pages:
        return False
    ohne_text = sum(
        1 for s in reader.pages if not hat_textebene(s.extract_text() or "")
    )
    return ohne_text > len(reader.pages) / 2
