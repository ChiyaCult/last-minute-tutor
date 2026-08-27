"""Relevanzsignale: mündliche Marker aus dem Transkript, Optionalquellen (Issues #23, #31).

Der Studienbrief selbst ist KEIN Relevanzsignal (er ist die unsortierte
Obermenge, siehe CONTEXT.md) — Signale kommen aus Vorlesungs-Transkripten,
Altklausuren und Übungs-PDFs. Ohne Optionalquellen degradiert die Pipeline
kontrolliert: gleiche Ausgabeform, höhere Unsicherheit im Manifest.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from .vertrag import Beleg, Chunk

log = logging.getLogger("lernpaket")

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


@dataclass
class Klausuraufgabe:
    """Eine Aufgabe aus einer Altklausur samt ihrem Punktgewicht.

    Das präziseste schriftliche Relevanzsignal überhaupt: keine geratene
    Wortüberlappung, sondern die Gewichtung des Prüfers selbst.
    """

    nummer: str
    titel: str
    punkte: int
    chunk_id: str
    position: str


# Altklausuren führen ihre Aufgaben als Block:
#     Aufgabe 1.1: (min, max)-Notation
#     1.1:
#     max. 11
# Die Rückwärtsreferenz auf die Nummer bindet die Punktzahl an genau ihre
# Aufgabe — sonst erben Unteraufgaben die Punkte der Oberaufgabe. Die im Text
# verstreuten „/ 4“ sind Korrekturkästchen je Teilfrage, keine Aufgabenpunkte.
KLAUSURAUFGABE_RE = re.compile(
    r"Aufgabe\s+(\d+(?:\.\d+)*)\s*:\s*(.+?)\s*\n\1\s*:\s*\n\s*max\.\s*(\d+)")


def _schluesselwoerter(text: str) -> List[str]:
    woerter = [w.lower() for w in _WORT_RE.findall(text)]
    return [w for w in woerter if w not in STOPPWOERTER]


def finde_klausuraufgaben(optional_chunks: Iterable[Chunk]) -> List[Klausuraufgabe]:
    """Liest Aufgabentitel samt Punktzahl aus Altklausuren und Übungs-PDFs.

    Nicht jedes Modul liefert das: gemessen 89% der Altklausur-Chunks in
    „Konzeptionelle Modellierung“, aber 0% in „Mathe 2a“. Ein leeres Ergebnis
    ist der Normalfall, kein Fehler — die Gewichtung fällt dann auf die
    Termüberlappung zurück.
    """
    aufgaben: List[Klausuraufgabe] = []
    for chunk in optional_chunks:
        if chunk.quelle not in ("altklausur", "uebung"):
            continue
        for nummer, titel, punkte in KLAUSURAUFGABE_RE.findall(chunk.text):
            titel = " ".join(titel.split())
            if titel:
                aufgaben.append(Klausuraufgabe(
                    nummer=nummer, titel=titel, punkte=int(punkte),
                    chunk_id=chunk.id, position=chunk.position))
    return aufgaben


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


def _wortnah(a: str, b: str) -> bool:
    """Gleiches Wort, Flexionsform oder Kompositum-Bestandteil.

    Bewusst NUR für Titel-gegen-Titel: über ganze Chunk-Texte erzeugt dieselbe
    Regel überwiegend Rauschen (gemessen — „lassen“ steckt in „Oberklassen“,
    und „Relation“ in „Relationship“, obwohl das hier zwei Konzepte sind).
    Bei zwei kurzen Titeln ist der Suchraum klein genug, dass sie trägt:
    „Modellierung“/„Modell“, „Relationenschemas“/„Relationenschema“.
    """
    if a == b:
        return True
    kurz, lang = (a, b) if len(a) <= len(b) else (b, a)
    # Nur echte Wortstämme, und der gemeinsame Teil muss den Großteil des
    # kürzeren Wortes ausmachen — sonst matcht jedes Wort auf jedes lange.
    return len(kurz) >= 5 and lang.startswith(kurz[:max(5, len(kurz) - 2)])


def _titel_naehe(thema_woerter: "set[str]", aufgabe_woerter: "set[str]") -> float:
    """Beste Abdeckung in beide Richtungen.

    Beide Richtungen, weil Aufgaben- und Thementitel unterschiedlich lang sind:
    „Funktionale Abhängigkeiten und Normalisierung“ deckt das Thema
    „Normalisierung“ vollständig ab, obwohl nur ein Drittel der Aufgabenwörter
    trifft. Nur eine Richtung zu messen verliert genau solche Fälle.
    """
    if not thema_woerter or not aufgabe_woerter:
        return 0.0
    aus_aufgabe = sum(1 for a in aufgabe_woerter if any(_wortnah(a, t) for t in thema_woerter))
    aus_thema = sum(1 for t in thema_woerter if any(_wortnah(t, a) for a in aufgabe_woerter))
    return max(aus_aufgabe / len(aufgabe_woerter), aus_thema / len(thema_woerter))


def _punkte_je_thema(themen, aufgaben: List[Klausuraufgabe]
                     ) -> Dict[str, List[Klausuraufgabe]]:
    """Ordnet jede Klausuraufgabe dem Thema zu, das ihr Titel am besten trifft.

    Jede Aufgabe geht an höchstens ein Thema — sonst zöge eine 52-Punkte-Aufgabe
    das halbe Modul nach oben. Taucht dieselbe Aufgabe in mehreren Altklausuren
    auf, summieren sich ihre Punkte bewusst: zweimal geprüft ist wichtiger.

    Rein lexikalisch, also blind für Synonyme („Structured Query Language“ vs.
    „Die Datenbanksprache SQL“). `ordne_aufgaben_per_llm` deckt die zusätzlich ab.
    """
    zuordnung: Dict[str, List[Klausuraufgabe]] = {}
    for aufgabe in aufgaben:
        aufgabe_woerter = set(_schluesselwoerter(aufgabe.titel))
        if not aufgabe_woerter:
            continue
        bestes, bester_wert = None, 0.0
        for thema in themen:
            wert = _titel_naehe(set(_schluesselwoerter(thema.titel)), aufgabe_woerter)
            if wert > bester_wert:
                bestes, bester_wert = thema, wert
        if bestes is not None and bester_wert >= 0.5:
            zuordnung.setdefault(bestes.id, []).append(aufgabe)
    return zuordnung


AUFGABEN_SYSTEM = (
    "Du ordnest Aufgaben einer Altklausur den Themen eines Lernpakets zu. "
    "Gib zu jeder Aufgabennummer die ID des inhaltlich passenden Themas an. "
    "Passt keines, gib null. Erfinde keine IDs. Antworte ausschließlich mit JSON."
)


def ordne_aufgaben_per_llm(themen, aufgaben: List[Klausuraufgabe], llm
                           ) -> Dict[str, List[Klausuraufgabe]]:
    """Wie `_punkte_je_thema`, aber semantisch statt lexikalisch.

    Ein Aufruf je Modul (gut zwei Dutzend Titel gegen ein Dutzend Titel), der
    genau die Fälle löst, an denen Wortvergleich prinzipiell scheitert:
    „Structured Query Language“ vs. „Die Datenbanksprache SQL“, „EE/R“ vs.
    „Entity-Relationship“. Scheitert der Aufruf, bleibt es beim lexikalischen
    Ergebnis — das Punktesignal ist ein Bonus, kein Muss.
    """
    from .llm import extrahiere_json  # lokal: relevanz.py ist sonst LLM-frei

    if not aufgaben or not themen:
        return {}
    # Titel entdoppeln: dieselbe Aufgabe steht in jeder Altklausur erneut.
    titel = sorted({a.titel for a in aufgaben})
    prompt = (
        "Themen:\n"
        + "\n".join(f"  {t.id}: {t.titel}" for t in themen)
        + "\n\nKlausuraufgaben:\n"
        + "\n".join(f"  {i}: {t}" for i, t in enumerate(titel))
        + "\n\nAntworte als JSON-Objekt {\"<aufgaben-index>\": \"<thema-id>\"|null} "
          "mit genau einem Eintrag je Aufgabe."
    )
    try:
        paare = extrahiere_json(llm.frage(AUFGABEN_SYSTEM, prompt, max_tokens=2048))
    except Exception as fehler:
        log.warning("Klausuraufgaben konnten nicht per LLM zugeordnet werden (%s) — "
                    "lexikalischer Rückfall.", fehler)
        return _punkte_je_thema(themen, aufgaben)

    gueltig = {t.id for t in themen}
    thema_je_titel: Dict[str, str] = {}
    for index, thema_id in (paare or {}).items():
        try:
            name = titel[int(index)]
        except (ValueError, TypeError, IndexError):
            continue
        if thema_id in gueltig:
            thema_je_titel[name] = thema_id

    zuordnung: Dict[str, List[Klausuraufgabe]] = {}
    for aufgabe in aufgaben:
        thema_id = thema_je_titel.get(aufgabe.titel)
        if thema_id:
            zuordnung.setdefault(thema_id, []).append(aufgabe)
    # Nichts Verwertbares zurückbekommen? Dann lieber die lexikalische Zuordnung
    # als gar keine Gewichtung.
    return zuordnung or _punkte_je_thema(themen, aufgaben)


def gewichte_themen(themen, treffer: List[RelevanzTreffer],
                    optional_chunks: List[Chunk], llm=None) -> None:
    """Gewichtet/filtert den Themenkatalog anhand der Relevanzsignale (in place).

    - Transkript-Marker: stärkstes Signal (+0.5 skaliert nach Wortüberlappung).
    - Klausurpunkte: die Gewichtung des Prüfers (+0.4 skaliert am punktstärksten
      Thema des Moduls). Nur wo die Altklausur Punkte ausweist.
    - Optionalquellen (Altklausur/Übung): Termüberlappung (+0.4 skaliert).
    - Basis bleibt 0.3 (`abdeckung`): Abdeckung ist immer vollständig, die
      Signale steuern nur Gewichtung und Reihenfolge, nie das Weglassen.
    """
    optional_woerter: Dict[str, "set[str]"] = {}
    for chunk in optional_chunks:
        optional_woerter.setdefault(chunk.quelle, set()).update(_schluesselwoerter(chunk.text))

    aufgaben = finde_klausuraufgaben(optional_chunks)
    aufgaben_je_thema = (ordne_aufgaben_per_llm(themen, aufgaben, llm) if llm
                         else _punkte_je_thema(themen, aufgaben))
    punkte_je_thema = {tid: sum(a.punkte for a in aufg)
                       for tid, aufg in aufgaben_je_thema.items()}
    hoechstpunktzahl = max(punkte_je_thema.values(), default=0)

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

        punkte = punkte_je_thema.get(thema.id, 0)
        if punkte and hoechstpunktzahl:
            zuschlag += 0.4 * (punkte / hoechstpunktzahl)
            if "klausur-punkte" not in thema.relevanzsignale:
                thema.relevanzsignale.append("klausur-punkte")
                erste = aufgaben_je_thema[thema.id][0]
                thema.belege.append(Beleg(quelle="altklausur", position=erste.position,
                                          chunk_id=erste.chunk_id))

        for quelle, signal_woerter in optional_woerter.items():
            treffer_quote = (len(titel_woerter & signal_woerter) / len(titel_woerter)
                             if titel_woerter else 0.0)
            if treffer_quote >= 0.5:
                zuschlag += 0.4 * treffer_quote
                if quelle not in thema.relevanzsignale:
                    thema.relevanzsignale.append(quelle)

        thema.relevanz = round(min(1.0, 0.3 + zuschlag), 3)
