"""Textebene-vs-Scan-Erkennung und OCR-Fallback (Issue #30)."""
from pathlib import Path

from lernpaket_pipeline.extraktion.pdf import ist_scan_pdf, lies_pdf

from .conftest import FakeOcr
from .pdf_helfer import schreibe_pdf


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
