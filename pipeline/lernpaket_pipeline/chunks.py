"""Chunking mit Quellpositionen — die Grundlage aller Belege (ADR 0003/0004).

Das Reasoning-LLM (und der Heuristik-Generator) sieht nie Rohmaterial, sondern
diese Chunks: normalisiertes Markdown/Transkript plus Position (Seite/Minute/
Folie). Dieselben Chunks landen 1:1 in chunks.jsonl fürs Tutormodus-Retrieval.
"""
from __future__ import annotations

from typing import List

from .vertrag import Chunk
from .extraktion.audio import Transkript, minuten_position
from .extraktion.folien import Folie
from .extraktion.pdf import Seite

MAX_CHUNK_ZEICHEN = 1400
TRANSKRIPT_FENSTER_SEKUNDEN = 60.0


def _neue_id(zaehler: int) -> str:
    return f"c-{zaehler:04d}"


def _teile_text(text: str, max_zeichen: int = MAX_CHUNK_ZEICHEN) -> List[str]:
    """Teilt an Absatz-, notfalls Satzgrenzen in Stücke <= max_zeichen."""
    text = text.strip()
    if len(text) <= max_zeichen:
        return [text] if text else []
    stuecke: List[str] = []
    aktuell = ""
    for absatz in text.split("\n\n"):
        kandidat = f"{aktuell}\n\n{absatz}".strip() if aktuell else absatz
        if len(kandidat) <= max_zeichen:
            aktuell = kandidat
            continue
        if aktuell:
            stuecke.append(aktuell)
            aktuell = ""
        while len(absatz) > max_zeichen:
            schnitt = absatz.rfind(". ", 0, max_zeichen)
            schnitt = schnitt + 1 if schnitt > max_zeichen // 2 else max_zeichen
            stuecke.append(absatz[:schnitt].strip())
            absatz = absatz[schnitt:].strip()
        aktuell = absatz
    if aktuell:
        stuecke.append(aktuell)
    return stuecke


def chunks_aus_seiten(seiten: List[Seite], quelle: str = "studienbrief",
                      start_zaehler: int = 0) -> List[Chunk]:
    ergebnis: List[Chunk] = []
    zaehler = start_zaehler
    for seite in seiten:
        for stueck in _teile_text(seite.text):
            ergebnis.append(Chunk(id=_neue_id(zaehler), quelle=quelle,
                                  position=f"S. {seite.nummer}", text=stueck))
            zaehler += 1
    return ergebnis


def chunks_aus_transkript(transkript: Transkript, start_zaehler: int = 0) -> List[Chunk]:
    """Fasst Transkript-Segmente zu ~60s-Fenstern zusammen; Position = Startminute."""
    ergebnis: List[Chunk] = []
    zaehler = start_zaehler
    fenster_start = None
    fenster_texte: List[str] = []
    for segment in transkript.segmente:
        if fenster_start is None:
            fenster_start = segment.start
        fenster_texte.append(segment.text.strip())
        if segment.ende - fenster_start >= TRANSKRIPT_FENSTER_SEKUNDEN:
            ergebnis.append(Chunk(id=_neue_id(zaehler), quelle="vorlesung",
                                  position=minuten_position(fenster_start),
                                  text=" ".join(fenster_texte)))
            zaehler += 1
            fenster_start, fenster_texte = None, []
    if fenster_texte:
        ergebnis.append(Chunk(id=_neue_id(zaehler), quelle="vorlesung",
                              position=minuten_position(fenster_start or 0.0),
                              text=" ".join(fenster_texte)))
    return ergebnis


def chunks_aus_folien(folien: List[Folie], start_zaehler: int = 0) -> List[Chunk]:
    ergebnis: List[Chunk] = []
    zaehler = start_zaehler
    for folie in folien:
        if not folie.text.strip():
            continue
        ergebnis.append(Chunk(id=_neue_id(zaehler), quelle="folie",
                              position=f"Folie {folie.nummer} ({minuten_position(folie.zeit_sekunden)})",
                              text=folie.text.strip()))
        zaehler += 1
    return ergebnis
