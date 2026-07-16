"""Optionalquellen + graceful degradation (Issue #31) und End-zu-Ende-Durchstich
mit Determinismus (Issue #21)."""
from datetime import datetime, timezone
from pathlib import Path

from lernpaket_pipeline.pipeline import erzeuge_lernpaket, erzeuge_und_schreibe
from lernpaket_pipeline.vertrag import lade_lernpaket, pruefe_vertrag

FIX_ZEIT = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)


def test_gleicher_input_mit_und_ohne_optionalquellen(modul_dir_mit_optionalquellen):
    """Akzeptanz #31: beide Läufe liefern ein valides Lernpaket."""
    ohne_dir = modul_dir_mit_optionalquellen  # erst mit, dann Quellen entfernen
    mit = erzeuge_lernpaket(ohne_dir, jetzt=FIX_ZEIT)
    for pdf in (ohne_dir / "altklausuren").glob("*.pdf"):
        pdf.unlink()
    (ohne_dir / "altklausuren").rmdir()
    ohne = erzeuge_lernpaket(ohne_dir, jetzt=FIX_ZEIT)

    for paket in (mit, ohne):
        assert pruefe_vertrag(paket) == []
        assert paket.themen and paket.fragen and paket.lehrbloecke

    assert mit.manifest.optionalquellen_vorhanden is True
    assert mit.manifest.relevanz_unsicherheit == "niedrig"
    assert ohne.manifest.optionalquellen_vorhanden is False
    assert ohne.manifest.relevanz_unsicherheit == "hoch"


def test_optionalquellen_staerken_relevanzsignal(modul_dir_mit_optionalquellen):
    mit = erzeuge_lernpaket(modul_dir_mit_optionalquellen, jetzt=FIX_ZEIT)
    quicksort = next(t for t in mit.themen if "Quicksort" in t.titel)
    komplex = next(t for t in mit.themen if "Komplexitaet" in t.titel)
    # Quicksort kommt in der Altklausur vor, Komplexitaet nicht.
    assert quicksort.relevanz > komplex.relevanz
    assert "altklausur" in quicksort.relevanzsignale


def test_ende_zu_ende_deterministisch(modul_dir, tmp_path: Path):
    """Akzeptanz #21: deterministisches Lernpaket aus einem Beispiel-PDF."""
    ziel1 = erzeuge_und_schreibe(modul_dir, tmp_path / "lauf1", jetzt=FIX_ZEIT)
    ziel2 = erzeuge_und_schreibe(modul_dir, tmp_path / "lauf2", jetzt=FIX_ZEIT)
    dateien = sorted(p.name for p in ziel1.iterdir())
    assert dateien == ["chunks.jsonl", "lehrbloecke.json", "manifest.json",
                       "quiz.json", "themen.json"]
    for name in dateien:
        assert (ziel1 / name).read_bytes() == (ziel2 / name).read_bytes(), name

    paket = lade_lernpaket(ziel1)
    assert pruefe_vertrag(paket) == []
    assert any(f.diagnose for f in paket.fragen)
    assert 1 <= len(paket.themen) <= 40
