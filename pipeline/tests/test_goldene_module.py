"""Regressionsschutz an echtem Material (ADR 0008).

Diese Tests laufen nur, wenn die Modulverzeichnisse unter `input/` liegen —
sie sind bewusst nicht Teil des Repos (Urheberrecht, Größe). Sie halten fest,
dass die Foliensatz-Unterstützung den Prosa-Pfad nicht verschiebt: Die
Themenzahlen der bestehenden Module dürfen sich nicht ändern.
"""
import json
from pathlib import Path

import pytest

from lernpaket_pipeline.themen import ZIEL_MAX, ZIEL_MIN, baue_themenkatalog
from lernpaket_pipeline.vertrag import Chunk

INPUT = Path(__file__).resolve().parents[2] / "input"

# Gemessen am 2026-08-24 auf dem Extraktionsstand der jeweiligen Module.
GOLDENE_THEMENZAHL = {
    "mathe_2a": 26,
    "mathe_2b": 25,
    "Konzeptionelle_modellierung": 14,
}


def _studienbrief_chunks(modul: str):
    datei = INPUT / modul / "extraktion" / "chunks.jsonl"
    if not datei.exists():
        pytest.skip(f"kein Extraktionsergebnis für {modul} unter input/")
    chunks = [Chunk(**json.loads(z)) for z in
              datei.read_text(encoding="utf-8").splitlines() if z.strip()]
    return [c for c in chunks if c.quelle == "studienbrief"]


@pytest.mark.parametrize("modul,erwartet", sorted(GOLDENE_THEMENZAHL.items()))
def test_prosa_module_behalten_ihre_themenzahl(modul, erwartet):
    """Kippt die Dokumentart-Erkennung, fällt dieser Test statt der Klausur."""
    themen = baue_themenkatalog(_studienbrief_chunks(modul))
    assert len(themen) == erwartet


@pytest.mark.parametrize("modul", sorted(GOLDENE_THEMENZAHL))
def test_prosa_module_bleiben_im_zielband(modul):
    """Konzeptionelle Modellierung liegt mit 14 Themen knapp unter ZIEL_MIN.

    Das ist der Ist-Zustand seines Lernpakets und hier bewusst toleriert — der
    Test wacht über Abstürze der Granularität, nicht über diese eine Themenzahl.
    """
    themen = baue_themenkatalog(_studienbrief_chunks(modul))
    assert ZIEL_MIN - 1 <= len(themen) <= ZIEL_MAX
