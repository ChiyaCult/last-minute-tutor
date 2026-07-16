"""Zweiter Verifikationsdurchlauf gegen die Quelle (Issue #25, ADR 0003).

Geprüft wird gezielt das Fehleranfälligste: Quizantworten sowie Numerisches/
Formelhaftes. Der Durchlauf arbeitet gegen die belegten Chunks — eine Antwort,
deren Zahlen oder Kernbegriffe in ihren Belegstellen nicht vorkommen, wird als
`abweichung` markiert; der Player blendet solche Fragen aus und zeigt den
Hinweis als Materiallücke.
"""
from __future__ import annotations

import re
from typing import Dict, List

from .relevanz import _WORT_RE, STOPPWOERTER
from .vertrag import Chunk, Frage, Lehrblock, Materialluecke

_ZAHL_RE = re.compile(r"\d+(?:[.,]\d+)?")
_LATEX_RE = re.compile(r"\$\$?([^$]+)\$\$?")


def _normalisiere(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _kernwoerter(text: str, anzahl: int = 4) -> List[str]:
    woerter = [w.lower() for w in _WORT_RE.findall(text) if w.lower() not in STOPPWOERTER]
    return sorted(set(woerter), key=lambda w: (-len(w), w))[:anzahl]


def verifiziere(fragen: List[Frage], lehrbloecke: List[Lehrblock],
                chunks: List[Chunk]) -> List[Materialluecke]:
    """Setzt frage.verifikation und liefert Materiallücken für Widersprüche."""
    nach_id: Dict[str, Chunk] = {c.id: c for c in chunks}
    luecken: List[Materialluecke] = []

    for frage in fragen:
        quelltexte = [nach_id[b.chunk_id].text for b in frage.belege
                      if b.chunk_id and b.chunk_id in nach_id]
        if not quelltexte:
            frage.verifikation.status = "abweichung"
            frage.verifikation.hinweis = "Kein nachprüfbarer Beleg vorhanden."
            luecken.append(Materialluecke(
                thema_id=frage.thema_id, art="schweigen",
                beschreibung=f"Frage {frage.id}: Antwort ist nicht im Material belegt."))
            continue
        quelle = " ".join(quelltexte)
        quelle_norm = _normalisiere(quelle)

        antwort_text = frage.antwort
        if frage.format == "mc" and frage.optionen and frage.antwort in "ABCD":
            pos = "ABCD".index(frage.antwort)
            if pos < len(frage.optionen):
                antwort_text = frage.optionen[pos]

        zahlen = _ZAHL_RE.findall(antwort_text)
        fehlende_zahlen = [z for z in zahlen
                           if _normalisiere(z) not in quelle_norm
                           and _normalisiere(z.replace(",", ".")) not in quelle_norm]
        if fehlende_zahlen:
            frage.verifikation.status = "abweichung"
            frage.verifikation.hinweis = (
                f"Zahl(en) {', '.join(fehlende_zahlen)} der Antwort kommen in den "
                f"Belegstellen nicht vor.")
            luecken.append(Materialluecke(
                thema_id=frage.thema_id, art="widerspruch",
                beschreibung=f"Frage {frage.id}: {frage.verifikation.hinweis}"))
            continue

        kern = _kernwoerter(antwort_text)
        # Zahlen sind bereits geprüft; rein numerische Antworten gelten damit als belegt.
        if kern and not any(w in quelle_norm for w in kern):
            frage.verifikation.status = "abweichung"
            frage.verifikation.hinweis = (
                "Kernbegriffe der Antwort kommen in den Belegstellen nicht vor.")
            luecken.append(Materialluecke(
                thema_id=frage.thema_id, art="widerspruch",
                beschreibung=f"Frage {frage.id}: {frage.verifikation.hinweis}"))
            continue

        frage.verifikation.status = "bestaetigt"
        frage.verifikation.hinweis = ""

    # Formelhaftes in Lehrblöcken: jede $…$-Formel muss in ihren Belegen vorkommen.
    for block in lehrbloecke:
        quelltexte = [nach_id[b.chunk_id].text for b in block.belege
                      if b.chunk_id and b.chunk_id in nach_id]
        if not quelltexte:
            continue
        quelle_norm = _normalisiere(" ".join(quelltexte))
        for formel in _LATEX_RE.findall(block.inhalt_markdown):
            kern = _normalisiere(re.sub(r"\\[a-z]+", "", formel))
            if len(kern) >= 4 and kern not in quelle_norm:
                luecken.append(Materialluecke(
                    thema_id=block.thema_id, art="widerspruch",
                    beschreibung=f"Lehrblock {block.id}: Formel '{formel.strip()}' ist "
                                 f"in den Belegstellen nicht nachweisbar."))
    return luecken
