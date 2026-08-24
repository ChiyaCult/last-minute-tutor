"""Textebene-vs-Scan-Erkennung, OCR-Fallback (Issue #30) und
Verklebt-Erkennung mit Zweitextraktion."""
from pathlib import Path
from typing import Dict, List

from lernpaket_pipeline.extraktion.pdf import (FOLIEN, PROSA, erkenne_dokumentart,
                                               ist_scan_pdf, ist_verklebt, lies_pdf)

from .conftest import FakeOcr
from .pdf_helfer import schreibe_pdf

VERKLEBTE_ZEILEN = [
    "InAbb.1.16werdenverschiedeneMöglichkeitenaufgezeigt,wieEinschränkungen",
    "fürBeziehungstypendefiniertwerdenkönnen.EinBeziehungstypwirdals",
    "RautedargestelltdiemitLinienzweiEntity-Typenverbindet.DieseNotation",
    "wirddurchzusätzlicheMarkierungennocherweitertunderklärt.",
    "DieseMarkierungenbezeichnendieArtderBeziehungnochetwasgenauer.",
]
REPARIERTE_ZEILEN = (
    "In Abb. 1.16 werden verschiedene Möglichkeiten aufgezeigt, wie "
    "Einschränkungen für Beziehungstypen definiert werden können. Ein "
    "Beziehungstyp wird als Raute dargestellt, die mit Linien zwei "
    "Entity-Typen verbindet.")


class FakeZweitextraktor:
    """Liefert für angefragte Seiten festen reparierten Text."""

    def __init__(self, text: str = REPARIERTE_ZEILEN):
        self.text = text
        self.aufrufe: List[List[int]] = []

    def lies_seiten(self, pfad: Path, nummern: List[int]) -> Dict[int, str]:
        self.aufrufe.append(list(nummern))
        return {n: self.text for n in nummern}


def test_textebene_wird_ausgelesen(tmp_path: Path):
    pdf = schreibe_pdf(tmp_path / "text.pdf", [["Erste Seite mit ausreichend Inhalt zum Lesen."],
                                               ["Zweite Seite mit weiterem Inhalt hier."]])
    seiten = lies_pdf(pdf)
    assert len(seiten) == 2
    assert "Erste Seite" in seiten[0].text
    assert not seiten[0].ist_scan and not seiten[1].ist_scan


def test_scan_seite_wird_erkannt(tmp_path: Path):
    pdf = schreibe_pdf(tmp_path / "gemischt.pdf",
                       [["Seite mit echter Textebene und genug Zeichen darauf."], [""]],
                       scan_seiten=[2])
    seiten = lies_pdf(pdf)
    assert seiten[0].ist_scan is False
    assert seiten[1].ist_scan is True
    assert seiten[1].text == ""  # ohne OCR bleibt sie leer, aber markiert


def test_scan_pdf_ohne_textebene_liefert_text_via_ocr(tmp_path: Path):
    """Akzeptanzkriterium #30: Scan-PDF ohne Textebene liefert verwertbaren Text."""
    pdf = schreibe_pdf(tmp_path / "scan.pdf", [[""], [""]], scan_seiten=[1, 2])
    assert ist_scan_pdf(pdf) is True
    ocr = FakeOcr("Erkannter Scantext ueber Sortierverfahren.")
    seiten = lies_pdf(pdf, ocr=ocr)
    assert ocr.aufrufe == [1, 2]  # Volltext-OCR lief fuer jede Scan-Seite
    assert all(s.ist_scan for s in seiten)
    assert all("Sortierverfahren" in s.text for s in seiten)


def test_text_pdf_ist_kein_scan(tmp_path: Path):
    pdf = schreibe_pdf(tmp_path / "text.pdf",
                       [["Ganz normale Seite mit ordentlich viel Textinhalt."]])
    assert ist_scan_pdf(pdf) is False


def test_ist_verklebt_erkennt_fehlende_leerzeichen():
    assert ist_verklebt("\n".join(VERKLEBTE_ZEILEN)) is True
    assert ist_verklebt(REPARIERTE_ZEILEN) is False


def test_ist_verklebt_toleriert_urls_und_einzelne_komposita():
    text = ("Siehe https://beispiel.example/sehr/langer/pfad/zur/quelle-dokument "
            "sowie die Donaudampfschifffahrtsgesellschaft als Beispiel für "
            "ein langes Kompositum im ansonsten normalen Text hier.")
    assert ist_verklebt(text) is False


def test_verklebte_seite_wird_nachextrahiert(tmp_path: Path):
    pdf = schreibe_pdf(tmp_path / "verklebt.pdf", [
        ["Ganz normale erste Seite mit ordentlich viel Textinhalt darauf."],
        VERKLEBTE_ZEILEN,
    ])
    fake = FakeZweitextraktor()
    seiten = lies_pdf(pdf, zweitextraktor=fake)
    assert fake.aufrufe == [[2]]  # nur die verklebte Seite wird nachextrahiert
    assert "werden verschiedene Möglichkeiten" in seiten[1].text
    assert "normale erste Seite" in seiten[0].text


def test_schlechteres_zweitergebnis_wird_verworfen(tmp_path: Path):
    pdf = schreibe_pdf(tmp_path / "verklebt.pdf", [VERKLEBTE_ZEILEN])
    fake = FakeZweitextraktor(text="\n".join(VERKLEBTE_ZEILEN) + "\nnochverklebtererText")
    seiten = lies_pdf(pdf, zweitextraktor=fake)
    assert seiten[0].text.splitlines()[0] == VERKLEBTE_ZEILEN[0]
    assert ist_verklebt(seiten[0].text) is True  # Pipeline meldet das als Lücke


def test_ocr_rettet_seite_die_pdfminer_nicht_entklebt(tmp_path: Path):
    """Stufe 2: bleibt eine Seite nach pdfminer verklebt, entklebt OCR sie."""
    pdf = schreibe_pdf(tmp_path / "verklebt.pdf", [VERKLEBTE_ZEILEN])
    pdfminer_scheitert = FakeZweitextraktor(text="\n".join(VERKLEBTE_ZEILEN))

    class SauberOcr:
        def __init__(self):
            self.aufrufe: List[int] = []

        def lese_seite(self, pdf, seitennummer):
            self.aufrufe.append(seitennummer)
            return REPARIERTE_ZEILEN

    ocr = SauberOcr()
    seiten = lies_pdf(pdf, ocr=ocr, zweitextraktor=pdfminer_scheitert)
    assert ocr.aufrufe == [1]  # OCR nur für die nach pdfminer noch verklebte Seite
    assert "werden verschiedene Möglichkeiten" in seiten[0].text
    assert ist_verklebt(seiten[0].text) is False


def test_falsch_positiv_lange_komposita_werden_nicht_als_verklebt_gewertet():
    """Echte deutsche Komposita/Bindestrich-Namen sind kein Kleben (kein Fehlalarm)."""
    text = ("Richard Lenz ist Professor an der Friedrich-Alexander-Universität "
            "Erlangen-Nürnberg und forscht zu IT-Sicherheitsinfrastrukturen und "
            "einem Patientenverwaltungssystem im Entity-Relationship-Modell.")
    assert ist_verklebt(text) is False


def test_dokumentart_erkennt_foliensatz(tmp_path):
    """Querformat + wenig Text je Seite = Foliensatz (ADR 0008)."""
    pfad = schreibe_pdf(tmp_path / "folien.pdf",
                        [["Schaltalgebraische Regeln", "R5a a + 0 = a"]] * 6,
                        mediabox="0 0 720 540")
    assert erkenne_dokumentart(pfad, lies_pdf(pfad)) == FOLIEN


def test_dokumentart_erkennt_prosa(tmp_path):
    """Hochformat mit dichtem Fließtext bleibt Prosa — der bisherige Pfad."""
    zeilen = ["Ein Satz mit reichlich Fliesstext fuer die Zeichenzahl." * 2] * 20
    pfad = schreibe_pdf(tmp_path / "brief.pdf", [zeilen] * 6)
    assert erkenne_dokumentart(pfad, lies_pdf(pfad)) == PROSA


def test_dokumentart_querformat_allein_reicht_nicht(tmp_path):
    """Ein quer gesetzter Prosa-Studienbrief ist kein Foliensatz."""
    zeilen = ["Ein Satz mit reichlich Fliesstext fuer die Zeichenzahl." * 2] * 20
    pfad = schreibe_pdf(tmp_path / "quer.pdf", [zeilen] * 6, mediabox="0 0 792 612")
    assert erkenne_dokumentart(pfad, lies_pdf(pfad)) == PROSA


def test_dokumentart_wenig_text_allein_reicht_nicht(tmp_path):
    """Hochformat mit wenig Text (Aufgabenblatt, Deckblatt) bleibt Prosa."""
    pfad = schreibe_pdf(tmp_path / "duenn.pdf", [["Aufgabe 1", "Berechnen Sie."]] * 6)
    assert erkenne_dokumentart(pfad, lies_pdf(pfad)) == PROSA
