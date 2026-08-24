"""Chunking mit Quellpositionen — die Grundlage aller Belege (ADR 0003/0004).

Das Reasoning-LLM (und der Heuristik-Generator) sieht nie Rohmaterial, sondern
diese Chunks: normalisiertes Markdown/Transkript plus Position (Seite/Minute/
Folie). Dieselben Chunks landen 1:1 in chunks.jsonl fürs Tutormodus-Retrieval.
"""
from __future__ import annotations

from pathlib import Path
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
                      start_zaehler: int = 0, dokument: str = "") -> List[Chunk]:
    """Seiten → Chunks; `dokument` stellt der Position den Dateinamen voran.

    Nötig, sobald eine Kategorie aus mehreren PDFs besteht: sonst zeigen die
    Belege mehrerer Dateien alle auf ein mehrdeutiges "S. 1".
    """
    ergebnis: List[Chunk] = []
    zaehler = start_zaehler
    for seite in seiten:
        position = f"{dokument}, S. {seite.nummer}" if dokument else f"S. {seite.nummer}"
        for stueck in _teile_text(seite.text):
            ergebnis.append(Chunk(id=_neue_id(zaehler), quelle=quelle,
                                  position=position, text=stueck))
            zaehler += 1
    return ergebnis


def _vorlesungsname(datei: str) -> str:
    """Dateiname ohne Endung — die Kennung einer Vorlesung im Beleg."""
    return Path(datei).stem


def chunks_aus_transkript(transkript: Transkript, start_zaehler: int = 0) -> List[Chunk]:
    """Fasst Transkript-Segmente zu ~60s-Fenstern zusammen.

    Position ist Vorlesung + Startminute. Der Name muss mit hinein: ein Modul
    hat in der Regel ein Dutzend Vorlesungen, und ein Beleg "Min. 19:07" ohne
    Angabe, welche davon gemeint ist, lässt sich nicht nachschlagen (ADR 0003).
    """
    ergebnis: List[Chunk] = []
    zaehler = start_zaehler
    dokument = _vorlesungsname(transkript.datei)
    fenster_start = None
    fenster_texte: List[str] = []

    def _position(start: float) -> str:
        minute = minuten_position(start)
        return f"{dokument}, {minute}" if dokument else minute

    for segment in transkript.segmente:
        if fenster_start is None:
            fenster_start = segment.start
        fenster_texte.append(segment.text.strip())
        if segment.ende - fenster_start >= TRANSKRIPT_FENSTER_SEKUNDEN:
            ergebnis.append(Chunk(id=_neue_id(zaehler), quelle="vorlesung",
                                  position=_position(fenster_start),
                                  text=" ".join(fenster_texte)))
            zaehler += 1
            fenster_start, fenster_texte = None, []
    if fenster_texte:
        ergebnis.append(Chunk(id=_neue_id(zaehler), quelle="vorlesung",
                              position=_position(fenster_start or 0.0),
                              text=" ".join(fenster_texte)))
    return ergebnis


def chunks_aus_folien(folien: List[Folie], start_zaehler: int = 0,
                      dokument: str = "") -> List[Chunk]:
    """Folien → Chunks; `dokument` benennt die Vorlesung, aus der sie stammen.

    Ohne sie gilt dasselbe wie für Transkripte: "Folie 3 (Min. 5:00)" ist über
    mehrere Vorlesungen hinweg mehrdeutig.
    """
    ergebnis: List[Chunk] = []
    zaehler = start_zaehler
    kennung = _vorlesungsname(dokument) if dokument else ""
    for folie in folien:
        if not folie.text.strip():
            continue
        stelle = f"Folie {folie.nummer} ({minuten_position(folie.zeit_sekunden)})"
        ergebnis.append(Chunk(id=_neue_id(zaehler), quelle="folie",
                              position=f"{kennung}, {stelle}" if kennung else stelle,
                              text=folie.text.strip()))
        zaehler += 1
    return ergebnis
