"""Datei-Vertrag: Schreiben/Lesen-Roundtrip und Invarianten (Issue #21)."""
from pathlib import Path

import pytest

from lernpaket_pipeline.vertrag import (Beleg, Chunk, Frage, Lehrblock, Lernpaket,
                                        Manifest, Thema, Zielformat, lade_lernpaket,
                                        pruefe_vertrag, schreibe_lernpaket)


def _mini_paket() -> Lernpaket:
    chunk = Chunk(id="c-0000", quelle="studienbrief", position="S. 1", text="Ein Satz.")
    beleg = Beleg(quelle="studienbrief", position="S. 1", chunk_id="c-0000")
    thema = Thema(id="t-01", titel="Testthema", belege=[beleg])
    return Lernpaket(
        manifest=Manifest(modul_id="test", titel="Test", erzeugt_am="2026-07-16T00:00:00Z",
                          zielformat=Zielformat(vorschlag="mc")),
        themen=[thema],
        lehrbloecke=[Lehrblock(id="lb-t-01-1", thema_id="t-01", tiefe="auffrischung",
                               inhalt_markdown="## Testthema", belege=[beleg])],
        fragen=[Frage(id="q-t-01-mc-1", thema_id="t-01", format="mc",
                      frage_markdown="Frage?", antwort="A",
                      optionen=["richtig", "falsch", "egal", "keine"],
                      diagnose=True, belege=[beleg])],
        chunks=[chunk],
    )


def test_roundtrip(tmp_path: Path):
    paket = _mini_paket()
    ziel = schreibe_lernpaket(paket, tmp_path / "lp" / "test")
    for datei in ("manifest.json", "themen.json", "lehrbloecke.json", "quiz.json",
                  "chunks.jsonl"):
        assert (ziel / datei).exists(), datei
    geladen = lade_lernpaket(ziel)
    assert geladen.manifest.modul_id == "test"
    assert geladen.themen[0].titel == "Testthema"
    assert geladen.fragen[0].optionen == ["richtig", "falsch", "egal", "keine"]
    assert geladen.fragen[0].belege[0].chunk_id == "c-0000"
    assert geladen.chunks[0].text == "Ein Satz."
    assert pruefe_vertrag(geladen) == []


def test_jede_frage_traegt_beleg_feld():
    paket = _mini_paket()
    for frage in paket.fragen:
        assert isinstance(frage.belege, list)  # Feld verpflichtend, Inhalt darf leer sein


def test_vertrag_meldet_kaputte_referenzen():
    paket = _mini_paket()
    paket.fragen[0].belege[0].chunk_id = "c-9999"
    paket.lehrbloecke[0].thema_id = "t-99"
    fehler = pruefe_vertrag(paket)
    assert any("unbekannten Chunk" in f for f in fehler)
    assert any("unbekanntes Thema" in f for f in fehler)


def test_unbekannte_schema_version_wird_abgelehnt(tmp_path: Path):
    paket = _mini_paket()
    paket.manifest.schema_version = 99
    ziel = schreibe_lernpaket(paket, tmp_path / "lp")
    with pytest.raises(ValueError, match="schema_version"):
        lade_lernpaket(ziel)
