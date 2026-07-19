"""Generierungs-Vertrag (Belege, Formate, Materiallücke) und Verifikation
(Issues #21, #24, #25, #26)."""
from lernpaket_pipeline.generierung import HeuristischerGenerator
from lernpaket_pipeline.pipeline import erzeuge_lernpaket
from lernpaket_pipeline.verifikation import verifiziere
from lernpaket_pipeline.vertrag import Beleg, Chunk, Frage, Thema


def test_jedes_artefakt_traegt_beleg(modul_dir):
    paket = erzeuge_lernpaket(modul_dir)
    chunk_ids = {c.id for c in paket.chunks}
    assert paket.lehrbloecke and paket.fragen
    for artefakt in paket.lehrbloecke + paket.fragen:
        assert artefakt.belege, f"{artefakt.id} ohne Beleg"
        for beleg in artefakt.belege:
            assert beleg.chunk_id in chunk_ids


def test_fragen_sind_format_parametrisch(modul_dir):
    """Akzeptanz #24: Quizfragen parametrisch in mehreren Formaten (mc, rechnen, freitext, beweis)."""
    paket = erzeuge_lernpaket(modul_dir)
    formate = {f.format for f in paket.fragen}
    assert {"mc", "rechnen", "freitext", "beweis"} <= formate
    mc = next(f for f in paket.fragen if f.format == "mc")
    assert mc.optionen and len(mc.optionen) == 4 and mc.antwort in "ABCD"
    rechnen = next(f for f in paket.fragen if f.format == "rechnen")
    assert rechnen.antwort == "42"


def test_diagnosequiz_eine_frage_pro_thema(modul_dir):
    paket = erzeuge_lernpaket(modul_dir)
    diagnose = [f for f in paket.fragen if f.diagnose]
    themen_mit_fragen = {f.thema_id for f in paket.fragen}
    assert {f.thema_id for f in diagnose} == themen_mit_fragen
    for thema_id in themen_mit_fragen:
        assert sum(1 for f in diagnose if f.thema_id == thema_id) == 1


def test_materialluecke_statt_erfinden():
    """Akzeptanz #25: Schweigt das Material, entsteht eine Materiallücke."""
    thema = Thema(id="t-01", titel="Unbelegtes Thema")
    ergebnis = HeuristischerGenerator().erzeuge([thema], {"t-01": []}, "freitext")
    assert ergebnis.lehrbloecke == [] and ergebnis.fragen == []
    assert len(ergebnis.materialluecken) == 1
    assert ergebnis.materialluecken[0].art == "schweigen"
    assert ergebnis.materialluecken[0].thema_id == "t-01"


def _frage(antwort: str, chunk_id: str = "c-0000") -> Frage:
    return Frage(id="q-t-01-rechnen-1", thema_id="t-01", format="rechnen",
                 frage_markdown="Wie viele Elemente?", antwort=antwort,
                 belege=[Beleg(quelle="studienbrief", position="S. 1", chunk_id=chunk_id)])


def test_verifikation_bestaetigt_belegte_antwort():
    chunks = [Chunk(id="c-0000", quelle="studienbrief", position="S. 1",
                    text="Der Stapel enthaelt genau 42 Elemente.")]
    frage = _frage("42")
    luecken = verifiziere([frage], [], chunks)
    assert frage.verifikation.status == "bestaetigt"
    assert luecken == []


def test_verifikation_markiert_zahlen_abweichung():
    """Akzeptanz #25: Numerisches wird gegen die Quelle geprüft, Abweichung markiert."""
    chunks = [Chunk(id="c-0000", quelle="studienbrief", position="S. 1",
                    text="Der Stapel enthaelt genau 42 Elemente.")]
    frage = _frage("43")
    luecken = verifiziere([frage], [], chunks)
    assert frage.verifikation.status == "abweichung"
    assert "43" in frage.verifikation.hinweis
    assert luecken and luecken[0].art == "widerspruch"


def test_verifikation_ohne_beleg_ist_abweichung():
    frage = _frage("42", chunk_id="")
    frage.belege = []
    luecken = verifiziere([frage], [], [])
    assert frage.verifikation.status == "abweichung"
    assert luecken and luecken[0].art == "schweigen"


def test_pipeline_verifiziert_alle_fragen(modul_dir):
    paket = erzeuge_lernpaket(modul_dir)
    assert all(f.verifikation.status == "bestaetigt" for f in paket.fragen), [
        (f.id, f.verifikation.hinweis) for f in paket.fragen
        if f.verifikation.status != "bestaetigt"]
