"""Generierungs-Vertrag (Belege, Formate, Materiallücke) und Verifikation
(Issues #21, #24, #25, #26)."""
import urllib.error

import pytest

from lernpaket_pipeline.generierung import HeuristischerGenerator, LLMGenerator
from lernpaket_pipeline.llm import GecachterLLM, LLMDienstNichtVerfuegbar
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


class AussetzendesLLM:
    """LLM, das bei bestimmten Themen einen Serverfehler wirft."""

    def __init__(self, fehlerhafte_themen, antwort=None, code=503):
        self.fehlerhafte = set(fehlerhafte_themen)
        self.code = code
        self.aufrufe = 0
        self.antwort = antwort or (
            '{"lehrbloecke": [{"tiefe": "auffrischung", '
            '"inhalt_markdown": "Sortieren ist das Ordnen von Werten.", "chunk_ids": ["c-0001"]}], '
            '"fragen": [{"format": "freitext", "frage_markdown": "Was ist Sortieren?", '
            '"antwort": "Sortieren ist das Ordnen von Werten nach Groesse.", "erklaerung_markdown": "Siehe Text.", '
            '"chunk_ids": ["c-0001"]}]}')

    def frage(self, system, prompt, max_tokens=4096):
        for kennung in self.fehlerhafte:
            if kennung in prompt:
                raise urllib.error.HTTPError(
                    "https://api.example", self.code, "Fehler", {}, None)
        self.aufrufe += 1   # nur beantwortete Anfragen — sie kosten Kontingent
        return self.antwort


def _themen_mit_chunks(anzahl):
    themen = [Thema(id=f"t-{i:02d}", titel=f"Thema {i}") for i in range(1, anzahl + 1)]
    zuordnung = {t.id: [Chunk(id="c-0001", quelle="studienbrief", position="S. 1",
                              text="Sortieren ist das Ordnen von Werten nach Groesse. " * 12)] for t in themen}
    return themen, zuordnung


def test_voruebergehender_ausfall_bricht_ab_statt_zu_degradieren():
    """Wer ein LLM angefordert hat, bekommt kein heuristisches Ersatzpaket.

    Ein stillschweigend heruntergestuftes Paket sähe später aus wie ein
    vollwertiges — beim Lernen fällt der Unterschied erst auf, wenn es zu spät
    ist. Also klarer Abbruch; der Antwort-Cache macht den zweiten Anlauf billig.
    """
    themen, zuordnung = _themen_mit_chunks(4)
    llm = AussetzendesLLM(fehlerhafte_themen=["Thema 2"])
    with pytest.raises(LLMDienstNichtVerfuegbar) as fehler:
        LLMGenerator(llm).erzeuge(themen, zuordnung, "freitext")
    assert "Thema 2" in str(fehler.value)
    assert "Cache" in str(fehler.value), "Meldung muss den Weg nach vorn nennen"


def test_dauerhafter_fehler_markiert_nur_das_thema():
    """400/404 gehen nicht vorüber — markieren und weiter, aber ohne Ersatzinhalt."""
    themen, zuordnung = _themen_mit_chunks(3)
    llm = AussetzendesLLM(fehlerhafte_themen=["Thema 2"], code=400)
    ergebnis = LLMGenerator(llm).erzeuge(themen, zuordnung, "freitext")
    erzeugte = {lb.thema_id for lb in ergebnis.lehrbloecke}
    assert erzeugte == {"t-01", "t-03"}, "kein heuristischer Ersatz für t-02"
    assert any(m.thema_id == "t-02" for m in ergebnis.materialluecken)


def test_cache_spart_den_zweiten_lauf(tmp_path):
    """Nach einem Abbruch darf der zweite Anlauf nur die fehlenden Themen kosten."""
    themen, zuordnung = _themen_mit_chunks(3)
    # Erster Lauf: Thema 3 fällt aus, Thema 1 und 2 sind bezahlt.
    llm = AussetzendesLLM(fehlerhafte_themen=["Thema 3"])
    gecacht = GecachterLLM(llm, tmp_path / "generierung")
    with pytest.raises(LLMDienstNichtVerfuegbar):
        LLMGenerator(gecacht).erzeuge(themen, zuordnung, "freitext")
    assert llm.aufrufe == 2, "zwei Themen wurden tatsächlich angefragt"

    # Zweiter Anlauf, Dienst wieder da: nur noch das fehlende Thema kostet.
    llm2 = AussetzendesLLM(fehlerhafte_themen=[])
    gecacht2 = GecachterLLM(llm2, tmp_path / "generierung")
    ergebnis = LLMGenerator(gecacht2).erzeuge(themen, zuordnung, "freitext")
    assert llm2.aufrufe == 1, f"nur das fehlende Thema, war {llm2.aufrufe}"
    assert gecacht2.treffer == 2, "die beiden anderen kamen aus dem Cache"
    assert {lb.thema_id for lb in ergebnis.lehrbloecke} == {"t-01", "t-02", "t-03"}


def test_cache_greift_nicht_bei_geaendertem_material(tmp_path):
    """Neues Material heißt neuer Prompt — sonst lieferte der Cache Veraltetes."""
    themen, zuordnung = _themen_mit_chunks(1)
    llm = AussetzendesLLM(fehlerhafte_themen=[])
    gecacht = GecachterLLM(llm, tmp_path / "generierung")
    LLMGenerator(gecacht).erzeuge(themen, zuordnung, "freitext")
    zuordnung["t-01"][0].text = "Ganz anderer Inhalt zum selben Thema, mit Sätzen. " * 6
    LLMGenerator(gecacht).erzeuge(themen, zuordnung, "freitext")
    assert llm.aufrufe == 2, "geänderter Prompt muss neu angefragt werden"
