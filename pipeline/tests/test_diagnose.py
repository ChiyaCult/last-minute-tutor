"""Kennzahlen auf einem synthetischen Mini-Modul mit bekannten Sollwerten (Issue #45)."""
from __future__ import annotations

from lernpaket_pipeline.diagnose import (
    _jaccard, _perzentil, _shingles, _themenzahl_kennzahlen,
    diagnostiziere, klassifiziere_nicht_substanziell,
)
from lernpaket_pipeline.generierung import MAX_PROMPT_CHUNKS
from lernpaket_pipeline.themen import ZIEL_MAX, ZIEL_MIN
from lernpaket_pipeline.vertrag import Beleg, Chunk, Thema

NORMALFORM_TEXT = (
    "Die erste Normalform verlangt, dass jedes Attribut einer Relation einen "
    "atomaren Wertebereich besitzt und keine Wiederholungsgruppen innerhalb "
    "eines Tupels auftreten. Ein Attribut darf also nicht selbst wieder "
    "mehrere Werte enthalten, sondern muss auf einen einzigen unteilbaren "
    "Wert festgelegt sein."
)
REKURSION_TEXT = (
    "Rekursion liegt vor, wenn eine Funktion im eigenen Rumpf erneut sich "
    "selbst aufruft, um ein Problem auf eine kleinere Variante desselben "
    "Problems zurückzuführen. Damit die Berechnung terminiert, braucht jede "
    "rekursive Funktion mindestens einen Basisfall ohne weiteren Aufruf."
)


def _mini_modul():
    """Zwei Themen, acht Chunks — von Hand nachgerechnete Sollwerte, s. u."""
    themen = [
        Thema(id="t-01", titel="Normalform",
              belege=[Beleg(quelle="studienbrief", position="S. 1", chunk_id="c-01")]),
        Thema(id="t-02", titel="Rekursion",
              belege=[Beleg(quelle="studienbrief", position="S. 3", chunk_id="c-03")]),
    ]
    chunks = [
        Chunk(id="c-01", quelle="studienbrief", position="S. 1", text=NORMALFORM_TEXT),
        Chunk(id="c-02", quelle="studienbrief", position="S. 2",
              text="Inhaltsverzeichnis .......... 3\n2 Normalform .......... 5"),
        Chunk(id="c-03", quelle="studienbrief", position="S. 3", text=REKURSION_TEXT),
        Chunk(id="c-04", quelle="studienbrief", position="S. 4", text=REKURSION_TEXT),
        Chunk(id="c-05", quelle="studienbrief", position="S. 5",
              text="Lösung zu Aufgabe 3.2: Der Algorithmus terminiert nach drei Schritten."),
        Chunk(id="c-06", quelle="vorlesung", position="VL01, Min. 00:10",
              text="Guten Morgen zusammen, herzlich willkommen zur heutigen Vorlesung."),
        Chunk(id="c-07", quelle="folie", position="Folie, F. 2", text=NORMALFORM_TEXT),
        Chunk(id="c-08", quelle="vorlesung", position="VL02, Min. 05:00",
              text="Diese Rekursion kommt in der Klausurvorbereitung häufig vor, "
                   "denken Sie an den Abbruch der Berechnung."),
    ]
    return themen, chunks


def test_themenzahl_ausserhalb_des_zielbands():
    themen, chunks = _mini_modul()
    ergebnis = diagnostiziere(themen, chunks)
    assert ergebnis.themenzahl.anzahl == 2
    assert ergebnis.themenzahl.ziel_min == ZIEL_MIN
    assert ergebnis.themenzahl.ziel_max == ZIEL_MAX
    assert ergebnis.themenzahl.im_zielband is False


def test_chunks_je_thema_kennzahlen():
    themen, chunks = _mini_modul()
    ergebnis = diagnostiziere(themen, chunks)
    cjt = ergebnis.chunks_je_thema
    # t-01: c-01, c-02 (Studienbrief-Bereich) + c-07 (Folie, Wortüberlappung "Normalform")
    # t-02: c-03, c-04, c-05 (Studienbrief-Bereich) + c-08 (Vorlesung, Wortüberlappung "Rekursion")
    assert cjt.je_thema["t-01"] == 3
    assert cjt.je_thema["t-02"] == 4
    assert cjt.gesamt_zuordnungen == 7
    assert cjt.eindeutige_chunks == 7
    assert cjt.mehrfachzuordnungsfaktor == 1.0
    assert cjt.maximum == 4
    assert cjt.minimum == 3
    assert cjt.median == 3.5
    assert cjt.je_quelle == {"studienbrief": 5, "folie": 1, "vorlesung": 1}


def test_prompt_abdeckung_bei_kleinem_modul_ist_vollstaendig():
    """Beide Themen liegen unter MAX_PROMPT_CHUNKS — nichts fällt aus dem Prompt."""
    themen, chunks = _mini_modul()
    ergebnis = diagnostiziere(themen, chunks)
    pa = ergebnis.prompt_abdeckung
    assert pa.gesamt_zuordnungen == 7
    assert pa.zuordnungen_im_prompt == 7
    assert pa.anteil_zuordnungen_im_prompt == 1.0
    assert pa.anteil_eindeutiger_chunks_im_prompt == 1.0


def test_prompt_abdeckung_kappt_bei_ueberschuss():
    """Ein Thema mit mehr als MAX_PROMPT_CHUNKS Chunks verliert den Rest im Prompt."""
    ueberschuss = 5
    anzahl = MAX_PROMPT_CHUNKS + ueberschuss
    thema = Thema(id="t-01", titel="Datenbank",
                  belege=[Beleg(quelle="studienbrief", position="S. 1", chunk_id="c-000")])
    chunks = [
        Chunk(id=f"c-{i:03d}", quelle="vorlesung", position=f"VL01, Min. {i:02d}:00",
              text=f"Die Datenbank speichert im Beispiel {i} eine eigene Tabelle ab "
                   f"und zeigt damit einen weiteren Aspekt der Normalisierung.")
        for i in range(anzahl)
    ]
    ergebnis = diagnostiziere([thema], chunks)
    pa = ergebnis.prompt_abdeckung
    assert pa.gesamt_zuordnungen == anzahl
    assert pa.zuordnungen_im_prompt == MAX_PROMPT_CHUNKS
    assert pa.anteil_zuordnungen_im_prompt == round(MAX_PROMPT_CHUNKS / anzahl, 4)


def test_dubletten_ueber_quellgrenzen_und_innerhalb_eines_themas():
    themen, chunks = _mini_modul()
    ergebnis = diagnostiziere(themen, chunks)
    du = ergebnis.dubletten
    # t-01: c-01 (Studienbrief) und c-07 (Folie) sind wortgleich -> Dublette, quellübergreifend.
    assert du.je_thema_anteil_mit_dublette["t-01"] == round(2 / 3, 4)
    # t-02: c-03 und c-04 sind wortgleich, beide Studienbrief -> Dublette, nicht quellübergreifend.
    assert du.je_thema_anteil_mit_dublette["t-02"] == round(2 / 4, 4)
    assert du.gesamt_anteil_mit_dublette == round(4 / 7, 4)
    # Von den zwei gefundenen Dubletten-Paaren liegt genau eines quellübergreifend.
    assert du.quellgrenzen_uebergreifend_anteil == 0.5
    assert du.themen_gekappt == []


def test_nicht_substanzielle_chunks_stichprobe():
    themen, chunks = _mini_modul()
    ergebnis = diagnostiziere(themen, chunks)
    ns = ergebnis.nicht_substanziell
    assert ns.stichprobengroesse == len(chunks)
    assert ns.anteil_je_grund == {
        "inhaltsverzeichnis": round(1 / 8, 4),
        "uebungsloesungskopf": round(1 / 8, 4),
        "begruessung": round(1 / 8, 4),
    }
    assert ns.anteil_gesamt == round(3 / 8, 4)
    assert ns.anteil_je_quelle["studienbrief"] == round(2 / 5, 4)
    assert ns.anteil_je_quelle["vorlesung"] == round(1 / 2, 4)
    assert ns.anteil_je_quelle["folie"] == 0.0


def test_klassifiziere_nicht_substanziell_einzelfaelle():
    assert klassifiziere_nicht_substanziell(
        Chunk(id="x", quelle="studienbrief", position="", text="Inhalt .......... 3")
    ) == "inhaltsverzeichnis"
    assert klassifiziere_nicht_substanziell(
        Chunk(id="x", quelle="uebung", position="", text="Lösung zu Aufgabe 1: fertig.")
    ) == "uebungsloesungskopf"
    assert klassifiziere_nicht_substanziell(
        Chunk(id="x", quelle="vorlesung", position="",
              text="Herzlich willkommen zur Vorlesung heute.")
    ) == "begruessung"
    assert klassifiziere_nicht_substanziell(
        Chunk(id="x", quelle="studienbrief", position="", text=NORMALFORM_TEXT)
    ) is None
    assert klassifiziere_nicht_substanziell(
        Chunk(id="x", quelle="studienbrief", position="", text="")
    ) == "leer"


def test_themenzahl_kennzahlen_zielband_grenzen():
    def _themen(n):
        return [Thema(id=f"t-{i:02d}", titel=f"Thema {i}") for i in range(n)]

    assert _themenzahl_kennzahlen(_themen(14)).im_zielband is False
    assert _themenzahl_kennzahlen(_themen(15)).im_zielband is True
    assert _themenzahl_kennzahlen(_themen(40)).im_zielband is True
    assert _themenzahl_kennzahlen(_themen(41)).im_zielband is False


def test_perzentil_lineare_interpolation():
    werte = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert _perzentil(werte, 0.0) == 1.0
    assert _perzentil(werte, 1.0) == 10.0
    assert _perzentil(werte, 0.5) == 5.5
    assert _perzentil([], 0.9) == 0.0
    assert _perzentil([7], 0.9) == 7.0


def test_shingles_und_jaccard_identischer_text():
    a = _shingles(NORMALFORM_TEXT)
    b = _shingles(NORMALFORM_TEXT)
    assert _jaccard(a, b) == 1.0


def test_shingles_und_jaccard_unterschiedlicher_text():
    a = _shingles(NORMALFORM_TEXT)
    b = _shingles(REKURSION_TEXT)
    assert _jaccard(a, b) == 0.0


def test_jaccard_leerer_mengen():
    assert _jaccard(set(), set()) == 0.0
