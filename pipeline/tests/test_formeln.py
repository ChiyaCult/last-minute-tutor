import json

from lernpaket_pipeline.extraktion import formeln
"""Formel-/Tabellen-/Code-Erfassung nach Markdown (Issue #28)."""
from lernpaket_pipeline.extraktion.formeln import (HeuristikParser, ist_formelzeile,
                                                   raeume_marker_text_auf,
                                                   spalte_marker_seiten)


def test_formelzeile_wird_latex():
    md = HeuristikParser().nach_markdown("Die Rekursionsgleichung lautet:\nT(n) = 2T(n/2) + n\nSo weit der Text.")
    assert "$$T(n) = 2T(n/2) + n$$" in md


def test_unicode_mathe_wird_normalisiert():
    md = HeuristikParser().nach_markdown("f(n) ≤ c·g(n)")
    assert "\\le" in md and "\\cdot" in md and md.startswith("$$")


def test_prosa_bleibt_prosa():
    satz = "Die Komplexitaet ist ein Mass fuer den Aufwand eines Algorithmus."
    assert ist_formelzeile(satz) is False
    assert HeuristikParser().nach_markdown(satz) == satz


def test_code_wird_eingezaeunt():
    md = HeuristikParser().nach_markdown("def quicksort(liste):\n    return liste")
    assert md.startswith("```")
    assert "def quicksort(liste):" in md


def test_tabelle_wird_markdown():
    md = HeuristikParser().nach_markdown(
        "Verfahren   Laufzeit   Stabil\nQuicksort   n log n    nein\nMergesort   n log n    ja")
    zeilen = md.splitlines()
    assert zeilen[0] == "| Verfahren | Laufzeit | Stabil |"
    assert zeilen[1] == "| --- | --- | --- |"
    assert "| Mergesort | n log n | ja |" in zeilen


def test_marker_seiten_werden_nach_seitennummer_aufgeteilt():
    """Markers Paginierungsmarke trägt den 0-basierten Seitenindex.

    Wortlaut aus einem echten Marker-Lauf (page_range 30,45): der Index ist
    absolut, nicht relativ zum ausgewählten Bereich.
    """
    markdown = (
        "\n\n{30}" + "-" * 48 + "\n\n"
        "Erweiterte Koeffizientenmatrix\n"
        "\n\n{45}" + "-" * 48 + "\n\n"
        "## Abb. 2.8: Surjektivität\n")
    seiten = spalte_marker_seiten(markdown)
    assert sorted(seiten) == [31, 46]
    assert seiten[31] == "Erweiterte Koeffizientenmatrix"
    assert seiten[46] == "## Abb. 2.8: Surjektivität"


def test_ohne_paginierungsmarken_keine_seiten():
    assert spalte_marker_seiten("Nur Fließtext ohne Marken") == {}


def test_buchstabige_hochstellung_wird_ausgepackt():
    """Marker stellt im Studienbrief gewöhnliche Variablen hoch — Wortlaut echt."""
    roh = "Es sei *<sup>f</sup>* ∶ *<sup>D</sup>* → *<sup>M</sup>* eine Funktion."
    assert raeume_marker_text_auf(roh) == "Es sei *f* ∶ *D* → *M* eine Funktion."


def test_numerische_hochstellung_bleibt_erhalten():
    """Echte Exponenten dürfen nicht verloren gehen."""
    assert raeume_marker_text_auf("*x*<sup>2</sup>") == "*x*<sup>2</sup>"


def test_leere_sprunganker_verschwinden():
    roh = '<span id="page-45-0"></span>Abb. 2.9: Die Funktion'
    assert raeume_marker_text_auf(roh) == "Abb. 2.9: Die Funktion"


def _sentinel(verzeichnis, name, pid):
    datei = verzeichnis / f"{name}_server.json"
    datei.write_text(json.dumps({"pid": pid, "backend": name, "port": 1}),
                     encoding="utf-8")
    return datei


def test_schliesse_beendet_eigene_dienste(tmp_path, monkeypatch):
    """Nach der PDF-Phase müssen die Inferenzserver weg — sie halten GB."""
    monkeypatch.setattr(formeln, "_DIENST_VERZEICHNIS", tmp_path)
    beendet = []
    monkeypatch.setattr(formeln.os, "kill", lambda pid, sig: beendet.append(pid))

    parser = formeln.MarkerParser()
    parser._fremde_dienste = set()  # nichts lief vorher
    datei = _sentinel(tmp_path, "llamacpp", 4242)
    parser.schliesse()

    assert beendet == [4242]
    assert not datei.exists(), "Sentinel muss mit aufgeräumt werden"


def test_schliesse_laesst_fremde_dienste_laufen(tmp_path, monkeypatch):
    """Ein parallel laufender Prozess darf seinen Server nicht verlieren."""
    monkeypatch.setattr(formeln, "_DIENST_VERZEICHNIS", tmp_path)
    beendet = []
    monkeypatch.setattr(formeln.os, "kill", lambda pid, sig: beendet.append(pid))

    fremd = _sentinel(tmp_path, "fast_layout", 111)
    parser = formeln.MarkerParser()
    parser._fremde_dienste = {fremd.name}  # lief schon vor unserem Lauf
    _sentinel(tmp_path, "llamacpp", 222)   # den haben wir gestartet
    parser.schliesse()

    assert beendet == [222]
    assert fremd.exists()


def test_schliesse_uebersteht_bereits_toten_prozess(tmp_path, monkeypatch):
    monkeypatch.setattr(formeln, "_DIENST_VERZEICHNIS", tmp_path)

    def _weg(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(formeln.os, "kill", _weg)
    datei = _sentinel(tmp_path, "llamacpp", 9)
    parser = formeln.MarkerParser()
    parser._fremde_dienste = set()
    parser.schliesse()  # darf nicht werfen
    assert not datei.exists()
