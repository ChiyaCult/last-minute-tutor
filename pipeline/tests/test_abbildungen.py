"""Diagramm-Erfassung: Bildunterschrift-Erkennung, Rendering (Fake), Zuordnung
zum Thema und Roundtrip durch den Datei-Vertrag (bilder/ + abbildungen.json)."""
from pathlib import Path

from lernpaket_pipeline.extraktion.pdf import Seite, finde_abbildungen
from lernpaket_pipeline.pipeline import (extrahiere_material, generiere_lernpaket,
                                         lade_extraktion, schreibe_extraktion)
from lernpaket_pipeline.vertrag import (lade_lernpaket, pruefe_vertrag,
                                        schreibe_lernpaket)

from .conftest import STUDIENBRIEF_SEITEN
from .pdf_helfer import schreibe_pdf

# Gültige PNG-Signatur + Nutzlast (der Fake-Renderer muss kein echtes PNG liefern).
PNG = bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"fake-bild"


class FakeRenderer:
    def __init__(self):
        self.aufrufe = []

    def rendere(self, pdf: Path, seitennummer: int) -> bytes:
        self.aufrufe.append(seitennummer)
        return PNG


def test_finde_abbildungen_erkennt_unterschrift_nicht_verweis():
    seiten = [
        Seite(nummer=1, text="Wie in Abb. 1.1 gezeigt, folgt daraus einiges an Text."),
        Seite(nummer=2, text="Abb. 1.1: Mein Diagramm\nErläuternder Text darunter."),
    ]
    assert finde_abbildungen(seiten) == [(2, "Abb. 1.1: Mein Diagramm")]


def test_mehrere_unterschriften_auf_einer_seite_zusammengefasst():
    seiten = [Seite(nummer=5, text="Abb. 2.3: Erstes\nText\nAbb. 2.4: Zweites")]
    assert finde_abbildungen(seiten) == [(5, "Abb. 2.3: Erstes · Abb. 2.4: Zweites")]


def test_unterschrift_trotz_markdown_dekor_des_dokument_parsers():
    """Marker gibt Unterschriften als Überschrift, Anker oder fett aus.

    Wortlaut aus einem echten Marker-Lauf über den Studienbrief Mathe 2a
    (Seite 46) — ohne Toleranz dafür fände die Erkennung dort nichts mehr.
    """
    seiten = [Seite(nummer=46, text=(
        "## Abb. 2.8: Surjektivität\n"
        "Text dazwischen.\n"
        '<span id="page-45-0"></span>Abb. 2.9: Die Funktion f ist surjektiv\n'
        "**Abb. 2.10: Bijektivität**\n"))]
    assert finde_abbildungen(seiten) == [
        (46, "Abb. 2.8: Surjektivität · Abb. 2.9: Die Funktion f ist surjektiv "
             "· Abb. 2.10: Bijektivität")]


def test_inline_verweis_bleibt_trotz_dekor_toleranz_unerkannt():
    """Die Vorspann-Toleranz darf Fließtext-Verweise nicht mitreißen."""
    seiten = [Seite(nummer=3, text="Wie in Abb. 1.1: gezeigt wird, gilt das immer.")]
    assert finde_abbildungen(seiten) == []


def _modul_mit_abbildung(tmp_path: Path) -> Path:
    modul = tmp_path / "modul"
    modul.mkdir()
    seiten = [list(s) for s in STUDIENBRIEF_SEITEN]
    seiten[1] = seiten[1] + ["Abb. 1.1: Landau-Diagramm"]  # S.2 = Landau-Notation
    schreibe_pdf(modul / "studienbrief.pdf", seiten)
    return modul


def test_extraktion_rendert_und_belegt_abbildung(tmp_path: Path):
    modul = _modul_mit_abbildung(tmp_path)
    fake = FakeRenderer()
    ext = extrahiere_material(modul, diagramm_renderer=fake)
    assert fake.aufrufe == [2]
    assert len(ext.abbildungen) == 1
    a = ext.abbildungen[0]
    assert a.titel.startswith("Abb. 1.1") and a.bild == PNG
    assert a.belege and a.belege[0].quelle == "studienbrief" and a.belege[0].position == "S. 2"


def test_ohne_diagramme_flag_ueberspringt_rendering(tmp_path: Path):
    fake = FakeRenderer()
    ext = extrahiere_material(_modul_mit_abbildung(tmp_path),
                              diagramm_renderer=fake, mit_diagrammen=False)
    assert fake.aufrufe == [] and ext.abbildungen == []


def test_abbildung_roundtrip_und_themenzuordnung(tmp_path: Path):
    modul = _modul_mit_abbildung(tmp_path)
    ext = extrahiere_material(modul, diagramm_renderer=FakeRenderer())
    schreibe_extraktion(ext, modul)

    geladen = lade_extraktion(modul)  # PNG-Bytes kommen aus extraktion/bilder/
    assert geladen.abbildungen[0].bild == PNG

    paket = generiere_lernpaket(geladen, modul_id="m", titel="M")
    assert paket.abbildungen[0].thema_id  # einem Thema zugeordnet
    assert pruefe_vertrag(paket) == []

    ziel = schreibe_lernpaket(paket, tmp_path / "out")
    assert (ziel / "bilder" / "abb-0002.png").read_bytes() == PNG
    assert (ziel / "abbildungen.json").exists()
    wieder = lade_lernpaket(ziel)
    assert wieder.abbildungen[0].bild == PNG
    assert wieder.abbildungen[0].titel.startswith("Abb. 1.1")


def test_fliesstext_verweis_mit_gliederungsnummer_ist_keine_unterschrift():
    """"Abbildung 2.5 veranschaulicht …" darf nicht als Unterschrift zählen.

    Wortlaut aus dem Studienbrief Mathe 2a: ohne vollständig erzwungene Nummer
    zerfiel der Verweis in Nummer "2", Trenner "." und den Satz als Titel.
    """
    seiten = [Seite(nummer=1, text=(
        "Abbildung 2.5 veranschaulicht die Injektivität, welche bedeutet, dass "
        "jedes Element höchstens einmal angenommen wird."))]
    assert finde_abbildungen(seiten) == []


def test_unterschrift_mit_punkt_als_trenner_bleibt_erkannt():
    seiten = [Seite(nummer=2, text="Abb. 2.5. Injektivität")]
    assert finde_abbildungen(seiten) == [(2, "Abb. 2.5: Injektivität")]
