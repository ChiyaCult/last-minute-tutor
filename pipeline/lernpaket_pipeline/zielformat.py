"""Zielformat: erkennen-dann-bestätigen (Issue #24).

Die Pipeline schlägt aus dem STÄRKSTEN vorhandenen Relevanzsignal ein Format
vor (Altklausur > Übung > Transkript); bestätigt/korrigiert wird im Player.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .vertrag import Chunk, Zielformat

_INDIKATOREN: Dict[str, List[str]] = {
    "mc": [
        r"kreuzen sie", r"multiple.?choice", r"welche der folgenden",
        r"richtig oder falsch", r"\ba\)\s.*\bb\)\s", r"genau eine antwort",
        r"single.?choice",
    ],
    "rechnen": [
        r"berechnen sie", r"bestimmen sie den wert", r"wie viele?\b",
        r"geben sie das ergebnis", r"rechnen sie", r"lösen sie die gleichung",
    ],
    "beweis": [
        r"beweisen sie", r"zeigen sie,? dass", r"führen sie den beweis",
        r"widerlegen sie", r"per induktion",
    ],
    "freitext": [
        r"definieren sie", r"erläutern sie", r"beschreiben sie",
        r"erklären sie", r"nennen sie", r"vergleichen sie", r"grenzen sie .* ab",
    ],
}

_QUELLEN_RANG = {"altklausur": 3, "uebung": 2, "vorlesung": 1}


def _zaehle(text: str) -> Dict[str, int]:
    text = text.lower()
    return {fmt: sum(len(re.findall(muster, text)) for muster in muster_liste)
            for fmt, muster_liste in _INDIKATOREN.items()}


def erkenne_zielformat(chunks: List[Chunk]) -> Zielformat:
    """Erkennt das wahrscheinliche Zielformat aus dem stärksten Relevanzsignal."""
    nach_quelle: Dict[str, List[Chunk]] = {}
    for chunk in chunks:
        if chunk.quelle in _QUELLEN_RANG:
            nach_quelle.setdefault(chunk.quelle, []).append(chunk)

    for quelle, _ in sorted(_QUELLEN_RANG.items(), key=lambda p: -p[1]):
        if quelle not in nach_quelle:
            continue
        text = "\n".join(c.text for c in nach_quelle[quelle])
        treffer = _zaehle(text)
        bestes: Tuple[str, int] = max(sorted(treffer.items()), key=lambda p: p[1])
        if bestes[1] > 0:
            return Zielformat(
                vorschlag=bestes[0],
                begruendung=(f"{bestes[1]} Indikator(en) für '{bestes[0]}' in Quelle "
                             f"'{quelle}' (stärkstes vorhandenes Relevanzsignal)."),
            )
    return Zielformat(
        vorschlag="freitext",
        begruendung="Kein Formatindikator in den Relevanzsignalen gefunden — "
                    "Freitext als vorsichtiger Default; bitte im Player korrigieren.",
    )
