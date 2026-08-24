"""Dokumentarten der Pflichtquelle Studienbrief (ADR 0008): Prosa vs. Foliensatz."""
import pytest

from lernpaket_pipeline.extraktion.formeln import verwaiste_striche
from lernpaket_pipeline.pipeline import (FoliensatzOhneDokumentParser,
                                         extrahiere_material, finde_quellen,
                                         generiere_lernpaket)

from .pdf_helfer import schreibe_pdf

FOLIEN_MEDIABOX = "0 0 720 540"


class FakeSeitenParser:
    """Dokument-Parser, der ganze PDFs kann — wie Marker (SeitenParser)."""

    def pdf_nach_seiten(self, pfad):
        return {}

    def nach_markdown(self, seiten_text: str) -> str:
        return seiten_text


class NurZeilenParser:
    """Heuristik-Parser: kann nur Zeilen, keine gerenderten Seiten."""

    def nach_markdown(self, seiten_text: str) -> str:
        return seiten_text


def _foliensatz_modul(tmp_path):
    modul = tmp_path / "REST"
    (modul / "studienbrief").mkdir(parents=True)
    (modul / "vorlesungen").mkdir()
    (modul / "vorlesungen" / "v1.mp4").write_bytes(b"nicht wirklich video")
    seiten = [["Rechnerstrukturen", "Boolesche Algebra", "Kapitel 4.2"]]
    seiten += [["Schaltalgebraische Regeln", f"R{n}a a + 0 = a"] for n in range(2, 22)]
    schreibe_pdf(modul / "studienbrief" / "REST_4.2.pdf", seiten,
                 mediabox=FOLIEN_MEDIABOX)
    return modul


def test_foliensatz_ohne_dokument_parser_bricht_ab(tmp_path):
    """Ohne Parser wären die Formeln lautlos falsch — dann lieber kein Paket."""
    modul = _foliensatz_modul(tmp_path)
    with pytest.raises(FoliensatzOhneDokumentParser) as fehler:
        extrahiere_material(modul, parser=NurZeilenParser(), mit_diagrammen=False)
    assert "marker" in str(fehler.value).lower()
    assert "--dokumentart prosa" in str(fehler.value)


def test_dokumentart_landet_im_manifest(tmp_path):
    """Erkennen-dann-Bestätigen: die Annahme muss nachprüfbar im Paket stehen."""
    modul = _foliensatz_modul(tmp_path)
    extraktion = extrahiere_material(modul, parser=FakeSeitenParser(),
                                     mit_diagrammen=False)
    briefe = [q for q in extraktion.quellen if q.art == "studienbrief"]
    assert [q.dokumentart for q in briefe] == ["folien"]


def test_dokumentart_vorgabe_ueberschreibt_erkennung(tmp_path):
    """--dokumentart prosa rettet den Lauf, wenn die Erkennung danebenliegt."""
    modul = _foliensatz_modul(tmp_path)
    extraktion = extrahiere_material(modul, parser=NurZeilenParser(),
                                     mit_diagrammen=False, dokumentart="prosa")
    briefe = [q for q in extraktion.quellen if q.art == "studienbrief"]
    assert [q.dokumentart for q in briefe] == ["prosa"]


def test_folien_themen_ueberstehen_den_schrittwechsel(tmp_path):
    """Die Art muss aus extraktion.json in den Generierungsschritt tragen."""
    modul = _foliensatz_modul(tmp_path)
    extraktion = extrahiere_material(modul, parser=FakeSeitenParser(),
                                     mit_diagrammen=False)
    paket = generiere_lernpaket(extraktion, modul_id="rest", titel="REST")
    titel = [t.titel for t in paket.themen]
    assert any("Schaltalgebraische Regeln" in t for t in titel), titel


def test_prosa_modul_bleibt_prosa(modul_dir):
    """Regressionsschutz: das bestehende Fixture wird nicht plötzlich Folien."""
    extraktion = extrahiere_material(modul_dir, mit_diagrammen=False)
    briefe = [q for q in extraktion.quellen if q.art == "studienbrief"]
    assert all(q.dokumentart == "prosa" for q in briefe)
    assert finde_quellen(modul_dir).studienbriefe


def test_verwaiste_striche_werden_gezaehlt():
    """Gemessen an Markers Ausgabe für REST_4.2_Bool_Algebra, Folie 5."""
    assert verwaiste_striche(r"R8a a + a = 1 \_") == 1
    assert verwaiste_striche("R7a a + a = a\n____ _ _\n") == 3
    # Echtes LaTeX mit Indizes und gebundenem Überstrich schlägt nicht an.
    assert verwaiste_striche(r"$x_r = a_{r,1}\overline{y} + z\_index$") == 0
