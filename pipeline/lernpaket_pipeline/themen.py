"""Themenkatalog: vollständige Abdeckung, mittlere Granularität (~15–40 Themen).

Themen entstehen aus der Überschriften-Struktur des Studienbriefs (Obermenge,
Abdeckungspflicht) und werden durch Transkript-Inhalte ergänzt (Issue #22:
Themen, die nur in der Vorlesung vorkommen, fehlen sonst). Die Granularität
skaliert automatisch: Liefert eine Überschriften-Ebene zu viele Themen, wird
zur gröberen Ebene zusammengefasst.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .vertrag import Beleg, Chunk, Thema
from .relevanz import STOPPWOERTER, _WORT_RE

ZIEL_MIN, ZIEL_MAX = 15, 40

# Nummerierte Überschriften wie "3 Sortieren", "3.2 Quicksort", "3.2.1 Pivot-Wahl"
_UEBERSCHRIFT_RE = re.compile(
    r"^\s*#{0,4}\s*(\d+(?:\.\d+){0,3})\.?\s+([A-ZÄÖÜ][^\n]{2,80})\s*$", re.MULTILINE
)
_KAPITEL_RE = re.compile(
    r"^\s*(?:Kapitel|Lerneinheit|Teil)\s+(\d+)[:.]?\s+([^\n]{3,80})\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Strukturelle Abschnitte ohne eigenständig lernbaren Inhalt — sie würden den
# Themenkatalog verwässern und im Player als leere "Lücken" auftauchen.
BOILERPLATE_TITEL = frozenset({
    "lernergebnisse", "lernziele", "advance organizer", "zusammenfassung",
    "übungen", "uebungen", "übung", "uebung", "übungsaufgaben",
    "uebungsaufgaben", "kontrollaufgaben", "impressum", "vorwort",
    "inhaltsverzeichnis", "inhalt", "literatur", "literaturverzeichnis",
    "abbildungsverzeichnis", "tabellenverzeichnis", "stichwortverzeichnis",
    "index", "glossar", "anhang",
})
# Lösungsabschnitte sind Aufgaben-Anhänge, keine lernbaren Themen.
_BOILERPLATE_PREFIXE = ("lösung zu ", "loesung zu ", "lösungen zu ", "loesungen zu ")
# Endet ein Titel auf einem Funktionswort, ist er ein im Umbruch abgerissenes
# Satzfragment (z. B. "Lösung zu Kontrollaufgabe 1.2 auf").
_ABRISS_ENDWOERTER = frozenset({
    "auf", "der", "die", "das", "und", "oder", "mit", "von", "für", "fuer",
    "zu", "zur", "zum", "im", "in", "am", "an", "bei", "dann", "gilt", "ist",
    "sind", "wird", "werden", "als", "des", "dem", "den", "eine", "ein",
})
# Beginnt ein "Titel" mit einer Konjunktion, ist es ein Satzanfang aus dem
# Fließtext, den die Überschriften-Erkennung fälschlich erwischt hat.
_ABRISS_STARTWOERTER = frozenset({
    "wenn", "dann", "daher", "deshalb", "somit", "also", "dabei", "hierbei",
    "ferner", "zudem", "außerdem", "ausserdem", "beispielsweise", "zwar",
})
# Punktführer wie "Thema ..... 33" bzw. "Thema . . . . ." (Inhaltsverzeichnis).
_PUNKTREIHE_RE = re.compile(r"\.{4,}|(?:\.\s+){3,}\.")
_SEITEN_SUFFIX_RE = re.compile(r"\s+Seite\s+\d+\s*$", re.IGNORECASE)
# Kapitel-/Abschnittsnummern oberhalb dieser Grenze sind fast immer Artefakte
# (Postleitzahlen, Jahreszahlen, Seitenzahlen aus dem Inhaltsverzeichnis).
MAX_KAPITELNUMMER = 50


def _bereinige_titel(titel: str) -> str:
    """Entfernt Seitenangaben und Punktführer-Reste am Titelende."""
    titel = _SEITEN_SUFFIX_RE.sub("", titel.strip())
    return titel.rstrip(" .").strip()


def ist_boilerplate_titel(titel: str) -> bool:
    """True für Überschriften, die kein lernbares Thema tragen.

    Neben den bekannten Struktur-Abschnitten (`BOILERPLATE_TITEL`) fallen auch
    Extraktions-Artefakte darunter: Inhaltsverzeichnis-Zeilen mit Punktführern
    und im Umbruch abgerissene Satzfragmente (Titel endet auf "-", ":" oder ",").
    """
    if _PUNKTREIHE_RE.search(titel):
        return True
    kern = _bereinige_titel(titel)
    if not kern or kern.endswith(("-", ":", ",")) or "=" in kern:
        return True
    kern_klein = kern.lower()
    if kern_klein.startswith(_BOILERPLATE_PREFIXE):
        return True
    woerter = kern_klein.split()
    if woerter[0] in _ABRISS_STARTWOERTER or woerter[-1] in _ABRISS_ENDWOERTER:
        return True
    return kern_klein in BOILERPLATE_TITEL


@dataclass
class _Kandidat:
    nummer: str
    titel: str
    ebene: int
    chunk_id: str
    position: str


def _finde_kandidaten(chunks: List[Chunk]) -> List[_Kandidat]:
    kandidaten: List[_Kandidat] = []
    for chunk in chunks:
        for m in _UEBERSCHRIFT_RE.finditer(chunk.text):
            nummer, titel = m.group(1), m.group(2).strip().rstrip(".")
            if _WORT_RE.search(titel) is None or ist_boilerplate_titel(titel):
                continue
            if int(nummer.split(".", 1)[0]) > MAX_KAPITELNUMMER:
                continue
            kandidaten.append(_Kandidat(nummer=nummer, titel=_bereinige_titel(titel),
                                        ebene=nummer.count(".") + 1,
                                        chunk_id=chunk.id, position=chunk.position))
        for m in _KAPITEL_RE.finditer(chunk.text):
            titel = m.group(2).strip()
            if ist_boilerplate_titel(titel):
                continue
            kandidaten.append(_Kandidat(nummer=m.group(1), titel=_bereinige_titel(titel),
                                        ebene=1, chunk_id=chunk.id, position=chunk.position))
    # Duplikate (gleiche Nummer) verwerfen, Reihenfolge des Auftretens behalten.
    gesehen = set()
    eindeutig = []
    for k in kandidaten:
        if k.nummer not in gesehen:
            gesehen.add(k.nummer)
            eindeutig.append(k)
    return eindeutig


def _waehle_ebene(kandidaten: List[_Kandidat]) -> Optional[int]:
    """Wählt die Überschriften-Ebene, deren Themenzahl dem Zielband am nächsten kommt."""
    beste, bester_abstand = None, None
    for ebene in (2, 3, 1):
        anzahl = sum(1 for k in kandidaten if k.ebene == ebene)
        if anzahl == 0:
            continue
        if ZIEL_MIN <= anzahl <= ZIEL_MAX:
            return ebene
        abstand = min(abs(anzahl - ZIEL_MIN), abs(anzahl - ZIEL_MAX))
        if bester_abstand is None or abstand < bester_abstand:
            beste, bester_abstand = ebene, abstand
    return beste


def _themen_aus_seitenbloecken(chunks: List[Chunk], block_groesse: int = 8) -> List[Thema]:
    """Fallback ohne erkennbare Struktur: Seitenblöcke als Themen."""
    themen: List[Thema] = []
    for i in range(0, len(chunks), block_groesse):
        block = chunks[i:i + block_groesse]
        woerter: Dict[str, int] = {}
        for c in block:
            for w in _WORT_RE.findall(c.text):
                w = w.lower()
                if w not in STOPPWOERTER:
                    woerter[w] = woerter.get(w, 0) + 1
        top = sorted(woerter, key=lambda w: (-woerter[w], w))[:3]
        titel = ", ".join(w.capitalize() for w in top) or f"Abschnitt {len(themen) + 1}"
        themen.append(Thema(
            id=f"t-{len(themen) + 1:02d}", titel=titel,
            beschreibung=f"Abschnitt {block[0].position}–{block[-1].position}",
            belege=[Beleg(quelle=block[0].quelle, position=block[0].position,
                          chunk_id=block[0].id)],
        ))
    return themen


def baue_themenkatalog(studienbrief_chunks: List[Chunk]) -> List[Thema]:
    kandidaten = _finde_kandidaten(studienbrief_chunks)
    ebene = _waehle_ebene(kandidaten)
    if ebene is None:
        return _themen_aus_seitenbloecken(studienbrief_chunks)
    gewaehlt = [k for k in kandidaten if k.ebene <= ebene]
    # Nur die tiefste erlaubte Ebene wird zum Thema; flachere sind Kontext.
    themen: List[Thema] = []
    for k in gewaehlt:
        if k.ebene != ebene:
            continue
        themen.append(Thema(
            id=f"t-{len(themen) + 1:02d}", titel=k.titel,
            beschreibung=f"Abschnitt {k.nummer} des Studienbriefs",
            belege=[Beleg(quelle="studienbrief", position=k.position, chunk_id=k.chunk_id)],
        ))
    if not themen:
        return _themen_aus_seitenbloecken(studienbrief_chunks)
    return themen


def ergaenze_aus_transkript(themen: List[Thema], transkript_chunks: List[Chunk],
                            min_nennungen: int = 3) -> List[Thema]:
    """Ergänzt Themen um Vorlesungsinhalte (Issue #22).

    Bestehende Themen, die im Transkript vorkommen, erhalten einen
    Vorlesungs-Beleg. Häufige Transkript-Begriffe ohne passendes Thema werden
    als neue Themen aufgenommen (Inhalt, der nur in der Vorlesung vorkommt).
    """
    if not transkript_chunks:
        return themen
    haeufigkeit: Dict[str, int] = {}
    fundort: Dict[str, Chunk] = {}
    for chunk in transkript_chunks:
        for w in _WORT_RE.findall(chunk.text):
            wl = w.lower()
            if wl in STOPPWOERTER or len(wl) < 6:
                continue
            haeufigkeit[wl] = haeufigkeit.get(wl, 0) + 1
            fundort.setdefault(wl, chunk)

    themen_woerter = set()
    for thema in themen:
        themen_woerter.update(w.lower() for w in _WORT_RE.findall(thema.titel))

    for thema in themen:
        titel_woerter = {w.lower() for w in _WORT_RE.findall(thema.titel)}
        for w in titel_woerter:
            if w in haeufigkeit and not any(b.quelle == "vorlesung" for b in thema.belege):
                chunk = fundort[w]
                thema.belege.append(Beleg(quelle="vorlesung", position=chunk.position,
                                          chunk_id=chunk.id))
                break

    neue = [(w, n) for w, n in haeufigkeit.items()
            if n >= min_nennungen and w not in themen_woerter]
    neue.sort(key=lambda p: (-p[1], p[0]))
    platz = max(0, ZIEL_MAX - len(themen))
    for w, _ in neue[:min(5, platz)]:
        chunk = fundort[w]
        themen.append(Thema(
            id=f"t-{len(themen) + 1:02d}", titel=w.capitalize(),
            beschreibung="Aus der Vorlesung ergänztes Thema (nicht im Studienbrief verortet)",
            relevanzsignale=["abdeckung", "transkript"],
            belege=[Beleg(quelle="vorlesung", position=chunk.position, chunk_id=chunk.id)],
        ))
    return themen


def ordne_chunks_zu(themen: List[Thema], chunks: List[Chunk]) -> Dict[str, List[Chunk]]:
    """Ordnet jedem Thema die inhaltlich zugehörigen Chunks zu (für die Generierung).

    Studienbrief-Chunks werden sequenziell zugeordnet: Ein Thema `besitzt`
    alles ab seinem Beleg-Chunk bis zum Beleg-Chunk des nächsten Themas.
    Vorlesungs-/Folien-Chunks per Wortüberlappung mit dem Titel.
    """
    reihenfolge = {c.id: i for i, c in enumerate(chunks)}
    sb_chunks = [c for c in chunks if c.quelle == "studienbrief"]
    marken = []
    for thema in themen:
        start = None
        for beleg in thema.belege:
            if beleg.quelle == "studienbrief" and beleg.chunk_id in reihenfolge:
                start = reihenfolge[beleg.chunk_id]
                break
        marken.append((thema.id, start))

    zuordnung: Dict[str, List[Chunk]] = {t.id: [] for t in themen}
    mit_start = [(tid, s) for tid, s in marken if s is not None]
    mit_start.sort(key=lambda p: p[1])
    for idx, (tid, start) in enumerate(mit_start):
        ende = mit_start[idx + 1][1] if idx + 1 < len(mit_start) else len(chunks)
        zuordnung[tid] = [c for c in sb_chunks if start <= reihenfolge[c.id] < ende]

    andere = [c for c in chunks if c.quelle != "studienbrief"]
    for chunk in andere:
        chunk_woerter = {w.lower() for w in _WORT_RE.findall(chunk.text)}
        for thema in themen:
            titel_woerter = {w.lower() for w in _WORT_RE.findall(thema.titel)}
            if titel_woerter and titel_woerter & chunk_woerter:
                zuordnung[thema.id].append(chunk)
    return zuordnung
