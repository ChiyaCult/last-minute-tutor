"""Diagnose: Kennzahlen über eine bereits gelaufene Aufbereitung (Issue #45).

Rechnet über den bereits geschriebenen Themenkatalog und die Chunks eines
Lernpakets die Kennzahlen nach, die den Umbau aus ADR 0009–0011 steuern sollen
(`docs/BEFUND-AUFBEREITUNG.md`, Abschnitt „Was zuerst gemessen gehört"). Läuft
ohne LLM — reine Nachrechnung der bereits vorhandenen Heuristiken
(`ordne_chunks_zu`, `waehle_prompt_chunks`) auf dem gespeicherten Ergebnis, nicht
Teil des eigentlichen Generierungslaufs.
"""
from __future__ import annotations

import statistics
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from .generierung import MAX_PROMPT_CHUNKS, klausur_vokabular, waehle_prompt_chunks
from .relevanz import _WORT_RE
from .themen import ZIEL_MAX, ZIEL_MIN, _PUNKTREIHE_RE, ordne_chunks_zu
from .vertrag import Chunk, Thema

# --- Dubletten (Befund 5): lexikalisch, ohne neue Abhängigkeit -------------

# Wortweise Shingles statt Zeichen-Shingles: robuster gegen Formatierungsreste
# (Zeilenumbrüche, doppelte Leerzeichen) aus Studienbrief/Folie/Transkript.
SHINGLE_LAENGE = 8
# Ab diesem Jaccard-Wert gelten zwei Chunks als dieselbe Aussage in anderer
# Formulierung. Nicht am Material geeicht — Issue #45 misst nur, verändert
# nichts an der Pipeline. Ein plausibler Startwert für Stufe #47, dort bei
# Bedarf nachzuschärfen.
AEHNLICHKEIT_SCHWELLE = 0.6
# Themen mit mehr Chunks als dieser Wert werden für die Dublettenprüfung auf
# eine gleichmäßige Stichprobe verkleinert: die paarweisen Vergleiche wachsen
# quadratisch, und die im Befund beobachteten ~200-Chunk-Themen würden die
# Laufzeit sonst unnötig sprengen.
MAX_CHUNKS_FUER_DUBLETTEN = 250

# --- Nicht-substanzielle Chunks: Heuristik ohne LLM -------------------------

_LOESUNGSKOPF_RE = re.compile(
    r"^\s*(?:l[öo]sung(?:en)?\s+zu|musterl[öo]sung)", re.IGNORECASE)
_BEGRUESSUNG_RE = re.compile(
    r"guten (?:morgen|tag|abend)|herzlich willkommen|meine damen und herren|"
    r"hallo (?:zusammen|liebe)|sch[öo]nen (?:guten )?tag|"
    r"bis (?:zum|dann) n[äa]chste[sn]? mal|wir sehen uns (?:dann |wieder )?",
    re.IGNORECASE)
# Eine Begrüßung steht am Chunk-Anfang, nicht irgendwo im Fließtext — dieses
# Fenster reicht, ohne spätere zufällige Treffer (z. B. in einem Zitat) mitzunehmen.
_BEGRUESSUNG_FENSTER = 300
# Stichprobengröße je Quelle für die Klassifikation nicht-substanzieller
# Chunks: groß genug für eine belastbare Quote, klein genug, dass das Skript
# auch bei mehreren tausend Vorlesungs-Chunks in Sekunden durchläuft.
STICHPROBENGROESSE_JE_QUELLE = 300


def _stichprobe(chunks: List[Chunk], groesse: int) -> List[Chunk]:
    """Gleichmäßig über die Liste verteilte Stichprobe (deterministisch)."""
    if len(chunks) <= groesse:
        return chunks
    schritt = len(chunks) / groesse
    return [chunks[int(i * schritt)] for i in range(groesse)]


def klassifiziere_nicht_substanziell(chunk: Chunk) -> Optional[str]:
    """Heuristische Klassifikation; None = vermutlich substanziell.

    Kein Ersatz für die Aussagen-Schicht aus ADR 0009 — nur eine grobe,
    stichprobenhafte Schätzung ohne LLM, wie in Issue #45 gefordert.
    """
    text = chunk.text.strip()
    if not text:
        return "leer"
    if _PUNKTREIHE_RE.search(text):
        return "inhaltsverzeichnis"
    if _LOESUNGSKOPF_RE.match(text):
        return "uebungsloesungskopf"
    if chunk.quelle == "vorlesung" and _BEGRUESSUNG_RE.search(text[:_BEGRUESSUNG_FENSTER]):
        return "begruessung"
    return None


def _shingles(text: str) -> "set":
    """Menge überlappender Wortfolgen fester Länge (leer bei leerem Text).

    Ist der Chunk kürzer als `SHINGLE_LAENGE`, dient das gesamte Wort-Tupel als
    einziges Shingle — kurze Chunks sind sonst nie zueinander ähnlich, obwohl
    sie wortgleich sein können.
    """
    woerter = [w.lower() for w in _WORT_RE.findall(text)]
    if not woerter:
        return set()
    if len(woerter) < SHINGLE_LAENGE:
        return {tuple(woerter)}
    return {tuple(woerter[i:i + SHINGLE_LAENGE])
            for i in range(len(woerter) - SHINGLE_LAENGE + 1)}


def _jaccard(a: "set", b: "set") -> float:
    vereinigung = a | b
    return len(a & b) / len(vereinigung) if vereinigung else 0.0


def _dubletten_in_thema(chunks: List[Chunk]) -> "tuple":
    """Chunk-IDs mit mindestens einer Dublette, quellübergreifende und
    gesamte Anzahl gefundener Dubletten-Paare innerhalb eines Themas."""
    shingles = {c.id: _shingles(c.text) for c in chunks}
    mit_dublette: set = set()
    quellgrenzen = 0
    gesamt_paare = 0
    for i in range(len(chunks)):
        for j in range(i + 1, len(chunks)):
            a, b = chunks[i], chunks[j]
            if _jaccard(shingles[a.id], shingles[b.id]) >= AEHNLICHKEIT_SCHWELLE:
                mit_dublette.add(a.id)
                mit_dublette.add(b.id)
                gesamt_paare += 1
                if a.quelle != b.quelle:
                    quellgrenzen += 1
    return mit_dublette, quellgrenzen, gesamt_paare


def _perzentil(werte: List[float], quantil: float) -> float:
    """Lineare Interpolation zwischen den Rängen (wie `numpy.percentile`, Default)."""
    if not werte:
        return 0.0
    sortiert = sorted(werte)
    if len(sortiert) == 1:
        return float(sortiert[0])
    position = quantil * (len(sortiert) - 1)
    unten = int(position)
    rest = position - unten
    if unten + 1 < len(sortiert):
        return sortiert[unten] + rest * (sortiert[unten + 1] - sortiert[unten])
    return float(sortiert[unten])


# --- Ergebnis-Datenmodell ----------------------------------------------------

@dataclass
class ThemenzahlKennzahlen:
    anzahl: int
    ziel_min: int
    ziel_max: int
    im_zielband: bool


@dataclass
class ChunksJeThemaKennzahlen:
    anzahl_themen: int
    median: float
    perzentil_90: float
    maximum: int
    minimum: int
    gesamt_zuordnungen: int  # Summe über alle Themen; Mehrfachzuordnung zählt mehrfach
    eindeutige_chunks: int  # verschiedene Chunk-IDs, die mind. einem Thema zugeordnet sind
    mehrfachzuordnungsfaktor: float  # gesamt_zuordnungen / eindeutige_chunks
    je_quelle: Dict[str, int] = field(default_factory=dict)
    je_thema: Dict[str, int] = field(default_factory=dict)


@dataclass
class PromptAbdeckung:
    max_prompt_chunks: int
    gesamt_zuordnungen: int
    zuordnungen_im_prompt: int
    anteil_zuordnungen_im_prompt: float
    eindeutige_chunks_zugeordnet: int
    eindeutige_chunks_im_prompt: int
    anteil_eindeutiger_chunks_im_prompt: float


@dataclass
class DublettenKennzahlen:
    schwelle: float
    gesamt_anteil_mit_dublette: float
    quellgrenzen_uebergreifend_anteil: float
    je_thema_anteil_mit_dublette: Dict[str, float] = field(default_factory=dict)
    themen_gekappt: List[str] = field(default_factory=list)


@dataclass
class NichtSubstanzielleKennzahlen:
    stichprobengroesse: int
    anteil_gesamt: float
    anteil_je_grund: Dict[str, float] = field(default_factory=dict)
    anteil_je_quelle: Dict[str, float] = field(default_factory=dict)


@dataclass
class DiagnoseErgebnis:
    themenzahl: ThemenzahlKennzahlen
    chunks_je_thema: ChunksJeThemaKennzahlen
    prompt_abdeckung: PromptAbdeckung
    dubletten: DublettenKennzahlen
    nicht_substanziell: NichtSubstanzielleKennzahlen


# --- Berechnung ---------------------------------------------------------------

def _themenzahl_kennzahlen(themen: List[Thema]) -> ThemenzahlKennzahlen:
    anzahl = len(themen)
    return ThemenzahlKennzahlen(
        anzahl=anzahl, ziel_min=ZIEL_MIN, ziel_max=ZIEL_MAX,
        im_zielband=ZIEL_MIN <= anzahl <= ZIEL_MAX)


def _chunks_je_thema_kennzahlen(
        zuordnung: Dict[str, List[Chunk]]) -> ChunksJeThemaKennzahlen:
    groessen = [len(cs) for cs in zuordnung.values()]
    je_quelle: Dict[str, int] = {}
    alle_ids: List[str] = []
    for chunks in zuordnung.values():
        for c in chunks:
            je_quelle[c.quelle] = je_quelle.get(c.quelle, 0) + 1
            alle_ids.append(c.id)
    eindeutige = len(set(alle_ids))
    gesamt = sum(groessen)
    return ChunksJeThemaKennzahlen(
        anzahl_themen=len(zuordnung),
        median=statistics.median(groessen) if groessen else 0.0,
        perzentil_90=_perzentil(groessen, 0.9),
        maximum=max(groessen, default=0),
        minimum=min(groessen, default=0),
        gesamt_zuordnungen=gesamt,
        eindeutige_chunks=eindeutige,
        mehrfachzuordnungsfaktor=round(gesamt / eindeutige, 4) if eindeutige else 0.0,
        je_quelle=je_quelle,
        je_thema={tid: len(cs) for tid, cs in zuordnung.items()},
    )


def _prompt_abdeckung(themen: List[Thema],
                      zuordnung: Dict[str, List[Chunk]]) -> PromptAbdeckung:
    klausur = klausur_vokabular(zuordnung)
    gesamt = 0
    im_prompt = 0
    eindeutig_zugeordnet: set = set()
    eindeutig_im_prompt: set = set()
    for thema in themen:
        chunks = zuordnung.get(thema.id, [])
        gesamt += len(chunks)
        eindeutig_zugeordnet.update(c.id for c in chunks)
        gewaehlt = waehle_prompt_chunks(thema, chunks, klausur)
        im_prompt += len(gewaehlt)
        eindeutig_im_prompt.update(c.id for c in gewaehlt)
    return PromptAbdeckung(
        max_prompt_chunks=MAX_PROMPT_CHUNKS,
        gesamt_zuordnungen=gesamt,
        zuordnungen_im_prompt=im_prompt,
        anteil_zuordnungen_im_prompt=round(im_prompt / gesamt, 4) if gesamt else 1.0,
        eindeutige_chunks_zugeordnet=len(eindeutig_zugeordnet),
        eindeutige_chunks_im_prompt=len(eindeutig_im_prompt),
        anteil_eindeutiger_chunks_im_prompt=(
            round(len(eindeutig_im_prompt) / len(eindeutig_zugeordnet), 4)
            if eindeutig_zugeordnet else 1.0),
    )


def _dubletten_kennzahlen(zuordnung: Dict[str, List[Chunk]]) -> DublettenKennzahlen:
    je_thema_anteil: Dict[str, float] = {}
    gekappt: List[str] = []
    gesamt_chunks = 0
    gesamt_mit_dublette = 0
    gesamt_paare = 0
    gesamt_quellgrenzen = 0
    for tid, chunks in zuordnung.items():
        stichprobe = chunks
        if len(chunks) > MAX_CHUNKS_FUER_DUBLETTEN:
            stichprobe = _stichprobe(chunks, MAX_CHUNKS_FUER_DUBLETTEN)
            gekappt.append(tid)
        mit_dublette, quellgrenzen, paare = _dubletten_in_thema(stichprobe)
        je_thema_anteil[tid] = round(len(mit_dublette) / len(stichprobe), 4) if stichprobe else 0.0
        gesamt_chunks += len(stichprobe)
        gesamt_mit_dublette += len(mit_dublette)
        gesamt_paare += paare
        gesamt_quellgrenzen += quellgrenzen
    return DublettenKennzahlen(
        schwelle=AEHNLICHKEIT_SCHWELLE,
        gesamt_anteil_mit_dublette=(
            round(gesamt_mit_dublette / gesamt_chunks, 4) if gesamt_chunks else 0.0),
        quellgrenzen_uebergreifend_anteil=(
            round(gesamt_quellgrenzen / gesamt_paare, 4) if gesamt_paare else 0.0),
        je_thema_anteil_mit_dublette=je_thema_anteil,
        themen_gekappt=gekappt,
    )


def _nicht_substanziell_kennzahlen(chunks: List[Chunk]) -> NichtSubstanzielleKennzahlen:
    je_quelle: Dict[str, List[Chunk]] = {}
    for c in chunks:
        je_quelle.setdefault(c.quelle, []).append(c)
    stichprobe: List[Chunk] = []
    for cs in je_quelle.values():
        stichprobe.extend(_stichprobe(cs, STICHPROBENGROESSE_JE_QUELLE))

    gruende: Dict[str, int] = {}
    treffer_je_quelle: Dict[str, int] = {}
    gesamt_je_quelle: Dict[str, int] = {}
    for c in stichprobe:
        gesamt_je_quelle[c.quelle] = gesamt_je_quelle.get(c.quelle, 0) + 1
        grund = klassifiziere_nicht_substanziell(c)
        if grund:
            gruende[grund] = gruende.get(grund, 0) + 1
            treffer_je_quelle[c.quelle] = treffer_je_quelle.get(c.quelle, 0) + 1

    n = len(stichprobe)
    return NichtSubstanzielleKennzahlen(
        stichprobengroesse=n,
        anteil_gesamt=round(sum(gruende.values()) / n, 4) if n else 0.0,
        anteil_je_grund={g: round(x / n, 4) for g, x in gruende.items()} if n else {},
        anteil_je_quelle={
            q: round(treffer_je_quelle.get(q, 0) / x, 4) for q, x in gesamt_je_quelle.items()},
    )


def diagnostiziere(themen: List[Thema], chunks: List[Chunk]) -> DiagnoseErgebnis:
    """Berechnet alle Kennzahlen aus Issue #45 über Themenkatalog und Chunks.

    Rechnet `ordne_chunks_zu` frisch nach statt eine gespeicherte Zuordnung zu
    lesen — die Pipeline persistiert die Chunk-Thema-Zuordnung nirgends, sie
    ist reine Laufzeitgröße der Generierung (`generiere_lernpaket`).
    """
    zuordnung = ordne_chunks_zu(themen, chunks)
    return DiagnoseErgebnis(
        themenzahl=_themenzahl_kennzahlen(themen),
        chunks_je_thema=_chunks_je_thema_kennzahlen(zuordnung),
        prompt_abdeckung=_prompt_abdeckung(themen, zuordnung),
        dubletten=_dubletten_kennzahlen(zuordnung),
        nicht_substanziell=_nicht_substanziell_kennzahlen(chunks),
    )


def formatiere_zusammenfassung(ergebnis: DiagnoseErgebnis) -> str:
    """Kurze Textzusammenfassung fürs Terminal (die vollen Zahlen stehen im JSON)."""
    tz, cjt, pa, du, ns = (ergebnis.themenzahl, ergebnis.chunks_je_thema,
                          ergebnis.prompt_abdeckung, ergebnis.dubletten,
                          ergebnis.nicht_substanziell)
    zielband = "im Zielband" if tz.im_zielband else "AUSSERHALB des Zielbands"
    zeilen = [
        f"Themen: {tz.anzahl} ({zielband} {tz.ziel_min}–{tz.ziel_max})",
        f"Chunks je Thema: Median {cjt.median:g} · 90. Perzentil {cjt.perzentil_90:g} · "
        f"Maximum {cjt.maximum} (Minimum {cjt.minimum})",
        f"Mehrfachzuordnungsfaktor: {cjt.mehrfachzuordnungsfaktor:g} "
        f"({cjt.gesamt_zuordnungen} Zuordnungen / {cjt.eindeutige_chunks} Chunks)",
        f"Quellverteilung der Zuordnungen: "
        + ", ".join(f"{q} {n}" for q, n in sorted(cjt.je_quelle.items())),
        f"Prompt-Abdeckung (max. {pa.max_prompt_chunks}/Thema): "
        f"{pa.anteil_zuordnungen_im_prompt:.1%} der Zuordnungen, "
        f"{pa.anteil_eindeutiger_chunks_im_prompt:.1%} der eindeutigen Chunks",
        f"Dublettenrate (Schwelle {du.schwelle:g}): "
        f"{du.gesamt_anteil_mit_dublette:.1%} der Chunks mit Dublette, "
        f"davon {du.quellgrenzen_uebergreifend_anteil:.1%} quellübergreifend",
        f"Nicht-substanziell (Stichprobe n={ns.stichprobengroesse}): "
        f"{ns.anteil_gesamt:.1%} "
        + (f"({', '.join(f'{g} {a:.1%}' for g, a in sorted(ns.anteil_je_grund.items()))})"
           if ns.anteil_je_grund else ""),
    ]
    return "\n".join(zeilen)
