"""Themenkatalog-Aufbau und Zielformat-Erkennung (Issues #21, #24)."""
from lernpaket_pipeline.pipeline import erzeuge_lernpaket
from lernpaket_pipeline.vertrag import Chunk
from lernpaket_pipeline.zielformat import erkenne_zielformat


def test_themen_aus_ueberschriften(modul_dir):
    paket = erzeuge_lernpaket(modul_dir)
    titel = [t.titel for t in paket.themen]
    assert any("Komplexitaet" in t for t in titel)
    assert any("Quicksort" in t for t in titel)
    for thema in paket.themen:
        assert thema.belege, "Jedes Thema traegt Belege"


def test_zielformat_aus_altklausur(modul_dir_mit_optionalquellen):
    """Altklausur ist das stärkste Relevanzsignal; MC-Indikatoren → Vorschlag mc."""
    paket = erzeuge_lernpaket(modul_dir_mit_optionalquellen)
    assert paket.manifest.zielformat.vorschlag == "mc"
    assert "altklausur" in paket.manifest.zielformat.begruendung


def test_zielformat_default_ohne_signale(modul_dir):
    paket = erzeuge_lernpaket(modul_dir)
    assert paket.manifest.zielformat.vorschlag == "freitext"


def test_zielformat_rangfolge_der_quellen():
    """Altklausur schlägt Übung schlägt Vorlesung."""
    chunks = [
        Chunk(id="c-0001", quelle="vorlesung", position="Min. 1:00",
              text="Berechnen Sie die Laufzeit. Berechnen Sie den Speicher."),
        Chunk(id="c-0002", quelle="altklausur", position="S. 1",
              text="Beweisen Sie das Master-Theorem. Zeigen Sie, dass die Schranke gilt."),
    ]
    assert erkenne_zielformat(chunks).vorschlag == "beweis"
    assert erkenne_zielformat([chunks[0]]).vorschlag == "rechnen"
