"""Formel-/Tabellen-/Code-Erfassung nach Markdown (Issue #28)."""
from lernpaket_pipeline.extraktion.formeln import HeuristikParser, ist_formelzeile


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
