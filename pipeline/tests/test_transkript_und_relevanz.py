"""Vorlesungs-Audio → Transkript → Themenkatalog (Issue #22) und
Relevanzsignal aus dem Transkript (Issue #23)."""
from pathlib import Path

from lernpaket_pipeline.chunks import chunks_aus_transkript
from lernpaket_pipeline.pipeline import erzeuge_lernpaket
from lernpaket_pipeline.relevanz import finde_relevanz_marker

from .conftest import FakeTranskribierer


def test_transkript_chunks_tragen_zeitstempel(fake_transkribierer):
    transkript = fake_transkribierer.transkribiere(Path("vorlesung-01.mp4"))
    assert all(s.ende > s.start for s in transkript.segmente)
    chunks = chunks_aus_transkript(transkript)
    assert chunks, "Transkript muss Chunks liefern"
    assert chunks[0].quelle == "vorlesung"
    assert chunks[0].position.startswith("Min. ")


def test_transkript_erzeugt_neue_themen(modul_dir_mit_vorlesung, fake_transkribierer):
    """Akzeptanz #22: Transkriptinhalt erzeugt/ergänzt Themen im Themenkatalog."""
    paket = erzeuge_lernpaket(modul_dir_mit_vorlesung, transkribierer=fake_transkribierer)
    titel = [t.titel.lower() for t in paket.themen]
    # 'Hashtabellen' kommt nur in der Vorlesung vor und muss als Thema auftauchen.
    assert any("hashtabellen" in t for t in titel)
    hash_thema = next(t for t in paket.themen if "hashtabellen" in t.titel.lower())
    assert any(b.quelle == "vorlesung" for b in hash_thema.belege)


def test_relevanz_marker_werden_gefunden(fake_transkribierer):
    transkript = fake_transkribierer.transkribiere(Path("v.mp4"))
    treffer = finde_relevanz_marker(chunks_aus_transkript(transkript))
    assert any("klausurrelevant" in t.satz.lower() for t in treffer)
    assert all(t.chunk_id and t.position for t in treffer)


def test_marker_priorisiert_markierte_themen(modul_dir_mit_vorlesung, fake_transkribierer):
    """Akzeptanz #23: Transkript mit Markern priorisiert die markierten Themen."""
    paket = erzeuge_lernpaket(modul_dir_mit_vorlesung, transkribierer=fake_transkribierer)
    landau = next(t for t in paket.themen if "landau" in t.titel.lower())
    mergesort = next(t for t in paket.themen if "mergesort" in t.titel.lower())
    assert landau.relevanz > mergesort.relevanz
    assert "transkript-marker" in landau.relevanzsignale
    assert any(b.quelle == "vorlesung" for b in landau.belege)


def test_ohne_transkribierer_laeuft_pipeline_trotzdem(modul_dir_mit_vorlesung):
    paket = erzeuge_lernpaket(modul_dir_mit_vorlesung)
    assert paket.themen, "Pipeline muss ohne ASR-Adapter durchlaufen"
