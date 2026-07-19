"""Relevanzsignale: mündliche Marker aus dem Transkript, Optionalquellen (Issues #23, #31).

Der Studienbrief selbst ist KEIN Relevanzsignal (er ist die unsortierte
Obermenge, siehe CONTEXT.md) — Signale kommen aus Vorlesungs-Transkripten,
Altklausuren und Übungs-PDFs. Ohne Optionalquellen degradiert die Pipeline
kontrolliert: gleiche Ausgabeform, höhere Unsicherheit im Manifest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from .vertrag import Beleg, Chunk

# Mündliche Betonungen der Professoren — das präziseste Relevanzsignal.
RELEVANZ_MARKER = [
    r"klausurrelevant",
    r"kommt (?:in|zur) der? ?klausur",
    r"prüfungsrelevant",
    r"wird (?:gerne|oft|häufig) (?:gefragt|geprüft|abgefragt)",
    r"müssen sie (?:können|beherrschen|wissen)",
    r"sollten sie (?:sich )?(?:gut )?(?:merken|anschauen|einprägen)",
    r"das ist (?:sehr )?wichtig",
    r"typische (?:klausur|prüfungs)aufgabe",
    r"merken sie sich",
]
_MARKER_RE = re.compile("|".join(RELEVANZ_MARKER), re.IGNORECASE)

_WORT_RE = re.compile(r"[a-zA-ZäöüÄÖÜß]{4,}")

STOPPWOERTER = {
    "aber", "alle", "allem", "allen", "aller", "alles", "also", "auch", "beim",
    "dann", "dass", "dem", "den", "denn", "der", "des", "dessen", "die", "dies",
    "diese", "diesem", "diesen", "dieser", "dieses", "doch", "dort", "durch",
    "eine", "einem", "einen", "einer", "eines", "einige", "etwa", "etwas",
    "für", "gegen", "haben", "hier", "ihre", "immer", "kann", "können", "man",
    "mehr", "mit", "nach", "nicht", "noch", "nur", "oder", "ohne", "schon",
    "sehr", "sich", "sie", "sind", "sowie", "über", "und", "unter", "vom",
    "von", "vor", "was", "wenn", "werden", "wie", "wieder", "wird", "wir",
    "zum", "zur", "zwischen", "sein", "seine", "einer", "damit", "dabei",
    "diesem", "welche", "beziehungsweise", "sowie", "kapitel", "abschnitt",
    "beispiel", "seite", "somit", "dazu", "jedoch", "bereits",
}


@dataclass
class RelevanzTreffer:
    """Ein im Transkript gefundener mündlicher Relevanzmarker samt Kontext."""

    chunk_id: str
    position: str
    satz: str
    schluesselwoerter: List[str] = field(default_factory=list)


def _schluesselwoerter(text: str) -> List[str]:
    woerter = [w.lower() for w in _WORT_RE.findall(text)]
    return [w for w in woerter if w not in STOPPWOERTER]


def finde_relevanz_marker(transkript_chunks: Iterable[Chunk]) -> List[RelevanzTreffer]:
    """Findet Sätze mit mündlichen Relevanzmarkern in Vorlesungs-Chunks."""
    treffer: List[RelevanzTreffer] = []
    for chunk in transkript_chunks:
        if chunk.quelle != "vorlesung":
            continue
        for satz in re.split(r"(?<=[.!?])\s+", chunk.text):
            if _MARKER_RE.search(satz):
                treffer.append(RelevanzTreffer(
                    chunk_id=chunk.id, position=chunk.position, satz=satz.strip(),
                    schluesselwoerter=_schluesselwoerter(satz),
                ))
    return treffer


def _ueberlappung(thema_woerter: "set[str]", signal_woerter: "set[str]") -> float:
    if not thema_woerter or not signal_woerter:
        return 0.0
    return len(thema_woerter & signal_woerter) / len(thema_woerter | signal_woerter)


def gewichte_themen(themen, treffer: List[RelevanzTreffer],
                    optional_chunks: List[Chunk]) -> None:
    """Gewichtet/filtert den Themenkatalog anhand der Relevanzsignale (in place).

    - Transkript-Marker: stärkstes Signal (+0.5 skaliert nach Wortüberlappung).
    - Optionalquellen (Altklausur/Übung): Termüberlappung (+0.4 skaliert).
    - Basis bleibt 0.3 (`abdeckung`): Abdeckung ist immer vollständig, die
      Signale steuern nur Gewichtung und Reihenfolge, nie das Weglassen.
    """
    optional_woerter: Dict[str, "set[str]"] = {}
    for chunk in optional_chunks:
        optional_woerter.setdefault(chunk.quelle, set()).update(_schluesselwoerter(chunk.text))

    for thema in themen:
        woerter = set(_schluesselwoerter(f"{thema.titel} {thema.beschreibung}"))
        titel_woerter = set(_schluesselwoerter(thema.titel))

        bester_marker = 0.0
        for t in treffer:
            marker_woerter = set(t.schluesselwoerter)
            score = _ueberlappung(woerter, marker_woerter)
            if titel_woerter & marker_woerter:
                score = max(score, 0.6)
            if score > bester_marker:
                bester_marker = score
                if score >= 0.2 and "transkript-marker" not in thema.relevanzsignale:
                    thema.relevanzsignale.append("transkript-marker")
                    thema.belege.append(Beleg(quelle="vorlesung", position=t.position,
                                              chunk_id=t.chunk_id))
        zuschlag = 0.5 * min(1.0, bester_marker / 0.6) if bester_marker >= 0.2 else 0.0

        for quelle, signal_woerter in optional_woerter.items():
            treffer_quote = (len(titel_woerter & signal_woerter) / len(titel_woerter)
                             if titel_woerter else 0.0)
            if treffer_quote >= 0.5:
                zuschlag += 0.4 * treffer_quote
                if quelle not in thema.relevanzsignale:
                    thema.relevanzsignale.append(quelle)

        thema.relevanz = round(min(1.0, 0.3 + zuschlag), 3)
