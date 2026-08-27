"""Generierungs-Vertrag (Belege, Formate, Materiallücke) und Verifikation
(Issues #21, #24, #25, #26)."""
import urllib.error

import pytest

from lernpaket_pipeline.generierung import (MAX_PROMPT_CHUNKS,
                                           HeuristischerGenerator,
                                           LLMGenerator,
                                           waehle_prompt_chunks)
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


# --- Chunk-Auswahl für den Prompt ----------------------------------------

def _chunks(quelle, anzahl, text="Ein Satz über das Thema Beispiel.", start=0):
    return [Chunk(id=f"c-{quelle}-{i}", quelle=quelle, position=f"S. {i}",
                  text=text) for i in range(start, start + anzahl)]


def test_wenig_material_kommt_vollstaendig_in_den_prompt():
    chunks = _chunks("studienbrief", 5)
    assert waehle_prompt_chunks(Thema(id="t-01", titel="Beispiel"), chunks, {}) == chunks


def test_studienbrief_verdraengt_die_anderen_quellen_nicht():
    """Der eigentliche Fehler: Nicht-Studienbrief wird hinten angehängt und
    fiel dem simplen Abschneiden immer zum Opfer."""
    chunks = _chunks("studienbrief", 100) + _chunks("folie", 40) + _chunks("vorlesung", 40)
    gewaehlt = waehle_prompt_chunks(Thema(id="t-01", titel="Beispiel"), chunks, {})
    quellen = {c.quelle for c in gewaehlt}
    assert len(gewaehlt) == MAX_PROMPT_CHUNKS
    assert quellen == {"studienbrief", "folie", "vorlesung"}


def test_auswahl_behaelt_dokumentreihenfolge():
    chunks = _chunks("studienbrief", 50)
    gewaehlt = waehle_prompt_chunks(Thema(id="t-01", titel="Beispiel"), chunks, {})
    reihenfolge = {c.id: i for i, c in enumerate(chunks)}
    assert [reihenfolge[c.id] for c in gewaehlt] == sorted(reihenfolge[c.id] for c in gewaehlt)


def test_muendlicher_marker_schlaegt_irrelevantes_material():
    füller = _chunks("vorlesung", 60, text="Nebensächliches Geplauder ohne Bezug.")
    markiert = Chunk(id="c-wichtig", quelle="vorlesung", position="Min. 12",
                     text="Das ist klausurrelevant und kommt in der Klausur.")
    gewaehlt = waehle_prompt_chunks(Thema(id="t-01", titel="Beispiel"),
                                    füller + [markiert], {})
    assert any(c.id == "c-wichtig" for c in gewaehlt)


def test_belege_nur_auf_gezeigte_chunks(monkeypatch):
    """Das Modell darf keine chunk_id belegen, die nie im Prompt stand."""
    viele = _chunks("studienbrief", 60)
    unsichtbar = viele[-1].id

    class ErfindetBeleg:
        def frage(self, system, prompt, max_tokens=4096):
            assert unsichtbar not in prompt
            sichtbar = viele[0].id
            return ('{"lehrbloecke": [{"tiefe": "auffrischung", "inhalt_markdown": "X", '
                    f'"chunk_ids": ["{unsichtbar}"]}}], '
                    '"fragen": [{"format": "freitext", "frage_markdown": "F", '
                    f'"antwort": "A", "erklaerung_markdown": "E", "chunk_ids": ["{sichtbar}"]}}], '
                    '"materialluecken": []}')

    thema = Thema(id="t-01", titel="Beispiel")
    ergebnis = LLMGenerator(ErfindetBeleg()).erzeuge([thema], {"t-01": viele}, "mc")
    assert ergebnis.lehrbloecke == [], "Beleg auf nie gezeigten Chunk muss fallen"
    assert len(ergebnis.fragen) == 1, "der gültige Beleg daneben bleibt erhalten"
    assert ergebnis.materialluecken


def test_dauerfehlerserie_bricht_ab_statt_leeres_paket_zu_schreiben():
    """Falscher Modellname ließ alle 19 Themen mit 404 scheitern — und die
    Pipeline schrieb ein leeres Paket mit Exit-Code 0."""
    class ImmerVierNullVier:
        def frage(self, system, prompt, max_tokens=4096):
            raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    themen = [Thema(id=f"t-{i:02d}", titel=f"Thema {i}") for i in range(1, 8)]
    zuordnung = {t.id: _chunks("studienbrief", 2) for t in themen}
    with pytest.raises(LLMDienstNichtVerfuegbar, match="Konfiguration"):
        LLMGenerator(ImmerVierNullVier()).erzeuge(themen, zuordnung, "mc")


def test_vereinzelter_dauerfehler_laeuft_weiter():
    """Ein einzelnes kaputtes Thema darf den Lauf nicht kippen."""
    class NurEinsKaputt:
        def frage(self, system, prompt, max_tokens=4096):
            if "Thema 2" in prompt:
                raise urllib.error.HTTPError("u", 400, "Bad Request", {}, None)
            chunk_id = prompt.split("[", 1)[1].split(" |", 1)[0]
            return ('{"lehrbloecke": [{"tiefe": "auffrischung", "inhalt_markdown": "X", '
                    f'"chunk_ids": ["{chunk_id}"]}}], "fragen": [], "materialluecken": []}}')

    themen = [Thema(id=f"t-{i:02d}", titel=f"Thema {i}") for i in range(1, 5)]
    zuordnung = {t.id: _chunks("studienbrief", 2) for t in themen}
    ergebnis = LLMGenerator(NurEinsKaputt()).erzeuge(themen, zuordnung, "mc")
    assert len(ergebnis.lehrbloecke) == 3
    assert any("fehlgeschlagen" in m.beschreibung for m in ergebnis.materialluecken)


def test_durchgehend_leere_antworten_gelten_nicht_als_paket():
    """Erfolgreiche Aufrufe ohne verwertbares Ergebnis sind auch kein Lernpaket."""
    class LiefertNichts:
        def frage(self, system, prompt, max_tokens=4096):
            return '{"lehrbloecke": [], "fragen": [], "materialluecken": []}'

    themen = [Thema(id="t-01", titel="Thema 1")]
    with pytest.raises(LLMDienstNichtVerfuegbar, match="keines"):
        LLMGenerator(LiefertNichts()).erzeuge(
            themen, {"t-01": _chunks("studienbrief", 2)}, "mc")
