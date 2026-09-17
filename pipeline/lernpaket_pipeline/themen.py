"""Themenkatalog: vollständige Abdeckung, mittlere Granularität (~15–40 Themen).

Themen entstehen aus der Überschriften-Struktur des Studienbriefs (Obermenge,
Abdeckungspflicht) und werden durch Transkript-Inhalte ergänzt (Issue #22:
Themen, die nur in der Vorlesung vorkommen, fehlen sonst). Die Granularität
skaliert automatisch: Liefert eine Überschriften-Ebene zu viele Themen, wird
zur gröberen Ebene zusammengefasst.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .llm import extrahiere_json
from .vertrag import Beleg, Chunk, Thema
from .relevanz import STOPPWOERTER, _WORT_RE

log = logging.getLogger("lernpaket")

ZIEL_MIN, ZIEL_MAX = 15, 40

# Beansprucht ein einzelnes Thema mehr als diesen Anteil der Studienbrief-Chunks,
# war die erkannte Gliederung keine: Die Überschriften-Erkennung hat vereinzelte
# Textfragmente erwischt, und alles dahinter fällt mangels weiterer Marke einem
# einzigen Thema zu. Gemessene Werte gesunder Module: Mathe 2a 38,9 %, Mathe 2b
# 29,5 %, Konzeptionelle Modellierung 56,7 % — REST-Foliensätze dagegen 98 %
# (8 Schein-Themen aus einer Assembler-Beispielfolie). Die Schwelle liegt
# bewusst über dem schlechtesten gesunden Modul; sonst verlöre es seine echten
# Kapiteltitel an die Seitenblöcke.
MAX_THEMEN_ANTEIL = 0.75
# Unterhalb dieser Chunk-Zahl sagt der Anteil nichts aus: Trägt ein Dokument
# kaum mehr Chunks als der Katalog Themen hat, besitzt das größte Thema
# zwangsläufig einen großen Teil davon — das ist normal und kein Scheitern.
MIN_CHUNKS_FUER_WAECHTER = 20
# Zielgröße des Seitenblock-Fallbacks: Mitte des Zielbands. Die Blockgröße
# richtet sich danach, statt fix zu sein — sonst liefert derselbe Fallback bei
# 60 Chunks 8 Themen und bei 431 Chunks 54, beides außerhalb des Bands.
ZIEL_THEMEN_FALLBACK = 30

# Nummerierte Überschriften wie "3 Sortieren", "3.2 Quicksort", "3.2.1 Pivot-Wahl".
# Der Dokument-Parser (Marker) setzt sie zusätzlich in Markdown-Auszeichnung:
# "## **2.5.1 Polynome**". Ohne die tolerierte Fettung vor der Nummer bliebe die
# gesamte Kapitelstruktur unsichtbar und der Themenkatalog fiele auf zufällige
# Fließtext-Fragmente zurück.
_UEBERSCHRIFT_RE = re.compile(
    r"^[ \t]*#{0,4}[ \t]*[*_]{0,2}[ \t]*"
    r"(\d+(?:\.\d+){0,3})\.?[ \t]+([A-ZÄÖÜ][^\n]{2,80})[ \t]*$", re.MULTILINE
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
# Lösungsabschnitte sind Aufgaben-Anhänge, Bild-/Tabellenunterschriften keine
# Überschriften — beides keine lernbaren Themen.
_BOILERPLATE_PREFIXE = ("lösung zu ", "loesung zu ", "lösungen zu ", "loesungen zu ",
                        "tabelle ", "abb. ", "abbildung ", "listing ")
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
# Markdown-Auszeichnung im Titel (Fettung/Kursiv des Dokument-Parsers).
_MARKDOWN_DEKOR_RE = re.compile(r"[*_]{1,2}")
# Kapitel-/Abschnittsnummern oberhalb dieser Grenze sind fast immer Artefakte
# (Postleitzahlen, Jahreszahlen, Seitenzahlen aus dem Inhaltsverzeichnis).
MAX_KAPITELNUMMER = 50


def _bereinige_titel(titel: str) -> str:
    """Entfernt Seitenangaben, Punktführer-Reste und Markdown-Auszeichnung."""
    titel = _SEITEN_SUFFIX_RE.sub("", titel.strip())
    # Die schließende Fettung des Dokument-Parsers ("… Polynome**") gehört nicht
    # in den Themen-Titel; Auszeichnung innerhalb des Titels ebenso wenig.
    titel = _MARKDOWN_DEKOR_RE.sub("", titel)
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
    # "=" und "%" gehören in Formeln bzw. Tabellenzeilen, nicht in Überschriften.
    if not kern or kern.endswith(("-", ":", ",")) or "=" in kern or "%" in kern:
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


def _themen_aus_seitenbloecken(chunks: List[Chunk],
                               block_groesse: Optional[int] = None) -> List[Thema]:
    """Fallback ohne erkennbare Struktur: Seitenblöcke als Themen.

    Ohne ausdrückliche Blockgröße skaliert sie mit der Stoffmenge, damit die
    Themenzahl im Zielband landet (Modul-Docstring: Granularität skaliert
    automatisch).
    """
    if block_groesse is None:
        block_groesse = max(1, -(-len(chunks) // ZIEL_THEMEN_FALLBACK))
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


# --- Foliensätze (ADR 0008) -------------------------------------------------
# Folien tragen keine nummerierten Überschriften. Ihre Gliederung steckt in der
# Titelfolie (Kapitelnummer) und im Wechsel der Folien-Kopfzeile.

# Zielgröße einer Themengruppe in Folien. Für REST (435 Folien) ergeben sich
# damit 33 Themen; die naiven Ebenen liefern 16 (Kapitel, zu grob) bzw. 240
# (jeder Kopfzeilenwechsel, zu fein).
ZIEL_FOLIEN_JE_THEMA = 15

# Schwellen der Transkript-Ergänzung (s. `_ist_fachbegriff`), an den REST-
# Transkripten geeicht: 989 Chunks aus 17,3 h Vorlesung.
MIN_NOMEN_ANTEIL = 0.8
MAX_STREUUNG = 0.05
# Unterhalb dieser Chunk-Zahl ist die Streuung nicht aussagekräftig: In einem
# kurzen Transkript steht jedes Wort zwangsläufig in einem großen Anteil der
# Chunks (gleiche Überlegung wie MIN_CHUNKS_FUER_WAECHTER).
MIN_CHUNKS_FUER_STREUUNG = 20


def _am_satzanfang(text: str, pos: int) -> bool:
    """Steht das Wort an `pos` am Satzanfang? Dort ist auch ein Verb groß."""
    davor = text[:pos].rstrip()
    return not davor or davor[-1] in ".!?:"
# Anteil der Folien, ab dem eine wiederkehrende Zeile als Rauschen gilt
# (Modulname, Logo, Fußzeile) — sie steht auf fast jeder Folie und ist nie ein
# Thementitel.
FOLIEN_RAUSCH_ANTEIL = 0.7

_FOLIEN_KAPITEL_RE = re.compile(r"^\s*Kapitel\s+(\d+(?:\.\d+)?)\s*$", re.MULTILINE)
# Überschrift, wie der Dokument-Parser sie aus dem Layout der Folie ableitet.
_FOLIEN_UEBERSCHRIFT_RE = re.compile(r"^#{1,6} +(\S.*?)\s*$", re.MULTILINE)

# Zeilen, die keine Folien-Kopfzeile sein können. Der Dokument-Parser ordnet die
# Folie nach Layout, nicht nach Lesefluss — vor der Überschrift stehen darum oft
# eine Wahrheitstabelle, eine abgesetzte Formel oder ein Aufzählungspunkt. Ohne
# diese Filterung landet so etwas als Thementitel im Player (gemessen am
# REST-Lauf: 10 von 37 Titeln, z. B. "| $k$ | $PI$ | $j$ |" oder "6 = 3$ |").
# Das Leerzeichen hinter dem Aufzählungszeichen ist wesentlich: Ohne es fällt
# auch jede fett gesetzte Überschrift ("**Digitale Schaltfunktionen**") unter
# die Regel, und der Titel rutscht auf das erstbeste Diagramm-Label der Folie
# ("Steuerwerk", "Festplatte") durch.
_KEINE_KOPFZEILE_RE = re.compile(
    r"^\s*(?:[-*+•>]\s|\||\d+[.)]\s|\$\$|\\\[|\\begin\{)"  # Aufzählung, Tabelle, Formelblock
    r"|\|\s*$"                                             # Tabellenzeile (Ende)
    r"|^[^A-Za-zÄÖÜäöü]*$"                                 # kein einziger Buchstabe
)
# Auszeichnung, die nicht in den Titel gehört: HTML-Reste des Parsers und
# Inline-Mathematik ("Wandlung aus dem Dezimalsystem: N<sup>10</sup> …").
_TITEL_RAUSCH_RE = re.compile(r"<[^>]+>|\$[^$]*\$|\\[a-zA-Z]+\{[^}]*\}|\\[a-zA-Z]+")


def _taugt_als_kopfzeile(zeile: str) -> bool:
    """Trägt die Zeile einen lesbaren Titel — oder ist sie Layout-Beiwerk?"""
    if _KEINE_KOPFZEILE_RE.search(zeile):
        return False
    kern = _TITEL_RAUSCH_RE.sub("", zeile).strip(" :–-—")
    # Nach Abzug von Formeln und Auszeichnung muss echter Text übrig bleiben.
    return len(kern) >= 3 and len(re.findall(r"[A-Za-zÄÖÜäöüß]", kern)) >= 3
_POSITION_RE = re.compile(r"^(.*), S\. (\d+)$")


def _dokument_von(chunk: Chunk) -> str:
    """Dateiname aus der Beleg-Position ("Deck, S. 5" → "Deck")."""
    treffer = _POSITION_RE.match(chunk.position)
    return treffer.group(1) if treffer else ""


def _folien_rauschen(chunks: List[Chunk]) -> "set[str]":
    """Zeilen, die auf fast jeder Folie stehen — Logo, Modulname, Fußzeile.

    Häufigkeit allein genügt nicht: Ein Abschnitt, der fast den ganzen
    Foliensatz füllt, wiederholt seine Kopfzeile genauso oft wie ein Logo.
    Der Unterschied ist die Position — eine Kopfzeile steht **oben** auf ihrer
    Folie, Logo und Fußzeile stehen darunter. Ohne diese zweite Bedingung
    verlöre ein Foliensatz mit nur einem langen Abschnitt seinen Titel und
    fiele auf die erstbeste Formelzeile zurück.
    """
    zaehler: Dict[str, int] = {}
    oben: Dict[str, int] = {}
    for chunk in chunks:
        zeilen = [z.strip() for z in chunk.text.split("\n") if z.strip()]
        for zeile in set(zeilen):
            zaehler[zeile] = zaehler.get(zeile, 0) + 1
        if zeilen:
            oben[zeilen[0]] = oben.get(zeilen[0], 0) + 1
    grenze = max(2, int(len(chunks) * FOLIEN_RAUSCH_ANTEIL))
    return {zeile for zeile, anzahl in zaehler.items()
            if anzahl >= grenze and oben.get(zeile, 0) < anzahl / 2}


def _folien_kopfzeile(chunk: Chunk, rauschen: "set[str]") -> str:
    """Die Kopfzeile einer Folie — ihr Titel.

    Vorrang hat die **Markdown-Überschrift des Dokument-Parsers**: Marker
    analysiert das Layout der gerenderten Folie und markiert den Titel als
    `#`…`####`. Das trifft bei den REST-Folien 73 % der Fälle und ist dem
    Raten über die Zeilenposition deutlich überlegen — der Parser ordnet die
    Folie nach Layout, nicht nach Lesefluss, sodass oft eine Wahrheitstabelle
    oder eine abgesetzte Formel vor dem Titel steht.

    Erst wo er keine Überschrift gesetzt hat, greift die erste Zeile, die als
    Titel taugt.
    """
    kandidaten = [m.group(1) for m in _FOLIEN_UEBERSCHRIFT_RE.finditer(chunk.text)]
    kandidaten += [z.strip() for z in chunk.text.split("\n")]
    for zeile in kandidaten:
        zeile = zeile.strip().lstrip("#> ").strip()
        if len(zeile) < 3 or zeile in rauschen or zeile.rstrip(".").isdigit():
            continue
        if not _taugt_als_kopfzeile(zeile):
            continue
        return _bereinige_titel(_TITEL_RAUSCH_RE.sub("", zeile).strip(" :–-—"))
    return ""


def _themen_aus_foliensatz(chunks: List[Chunk], start: int) -> List[Thema]:
    """Ein Foliensatz → Themen: Abschnitte bündeln, bis die Zielgröße steht."""
    if not chunks:
        return []
    treffer = _FOLIEN_KAPITEL_RE.search(chunks[0].text)  # steht auf der Titelfolie
    kapitel = treffer.group(1) if treffer else ""
    rauschen = _folien_rauschen(chunks)

    # Aufeinanderfolgende Folien mit gleicher Kopfzeile bilden einen Abschnitt.
    # Die Titelfolie bleibt außen vor: Sie trägt den Namen des Foliensatzes
    # ("Rechnerstrukturen"), nicht den eines Themas — als Abschnitt würde sie
    # dem ersten Thema seinen echten Titel wegnehmen.
    abschnitte: List["tuple[str, List[Chunk]]"] = []
    letzte_kopfzeile = None
    for chunk in chunks[1:]:
        kopfzeile = _folien_kopfzeile(chunk, rauschen)
        if kopfzeile != letzte_kopfzeile or not abschnitte:
            abschnitte.append((kopfzeile, []))
            letzte_kopfzeile = kopfzeile
        abschnitte[-1][1].append(chunk)
    if abschnitte:  # Titelfolie gehört inhaltlich zum ersten Thema
        abschnitte[0][1].insert(0, chunks[0])
    else:
        abschnitte = [(_folien_kopfzeile(chunks[0], rauschen), [chunks[0]])]

    themen: List[Thema] = []

    def _thema_aus(kopfzeile: str, gruppe: List[Chunk]) -> None:
        if not gruppe:
            return
        titel = kopfzeile or f"Folien ab {gruppe[0].position}"
        nummer = start + len(themen) + 1
        themen.append(Thema(
            id=f"t-{nummer:02d}",
            titel=f"{kapitel} {titel}" if kapitel else titel,
            beschreibung=(f"Foliensatz {_dokument_von(gruppe[0])}, "
                          f"{len(gruppe)} Folien ab {gruppe[0].position}"),
            belege=[Beleg(quelle="studienbrief", position=gruppe[0].position,
                          chunk_id=gruppe[0].id)],
        ))

    gruppe: List[Chunk] = []
    gruppen_titel = ""
    for kopfzeile, abschnitt in abschnitte:
        if not gruppe:  # der erste Abschnitt einer Gruppe benennt sie
            gruppen_titel = kopfzeile
        gruppe.extend(abschnitt)
        if len(gruppe) >= ZIEL_FOLIEN_JE_THEMA:
            _thema_aus(gruppen_titel, gruppe)
            gruppe = []
    _thema_aus(gruppen_titel, gruppe)
    return themen


def _qualifiziere_doppelte_titel(themen: List[Thema]) -> List[Thema]:
    """Gleichlautende Titel unterscheidbar machen.

    Foliensätze wiederholen ihre Kopfzeile über lange Strecken ("Digitale
    Schaltfunktionen" trägt bei REST drei Themengruppen). Im Player steht nur
    der Titel — ohne Unterscheidung wären sie nicht auseinanderzuhalten.
    """
    gesamt: Dict[str, int] = {}
    for thema in themen:
        gesamt[thema.titel] = gesamt.get(thema.titel, 0) + 1
    laufend: Dict[str, int] = {}
    for thema in themen:
        if gesamt[thema.titel] > 1:
            laufend[thema.titel] = laufend.get(thema.titel, 0) + 1
            thema.titel = f"{thema.titel} (Teil {laufend[thema.titel]})"
    return themen


def _groesster_themenanteil(themen: List[Thema], chunks: List[Chunk]) -> float:
    """Anteil der Chunks, den das größte Thema sequenziell für sich beansprucht.

    Spiegelt die Zuordnung aus `ordne_chunks_zu`: Ein Thema besitzt alles ab
    seiner Marke bis zur nächsten, das letzte bis zum Dokumentende.
    """
    if not chunks:
        return 0.0
    reihenfolge = {c.id: i for i, c in enumerate(chunks)}
    marken = sorted({reihenfolge[beleg.chunk_id] for thema in themen
                     for beleg in thema.belege if beleg.chunk_id in reihenfolge})
    if not marken:
        return 1.0
    grenzen = marken + [len(chunks)]
    groesstes = max(grenzen[i + 1] - grenzen[i] for i in range(len(marken)))
    return groesstes / len(chunks)


def baue_themenkatalog(studienbrief_chunks: List[Chunk],
                       folien_dokumente: Optional["set[str]"] = None) -> List[Thema]:
    """Themenkatalog aus den Studienbrief-Chunks.

    `folien_dokumente` nennt die Dateinamen, die als Foliensatz erkannt wurden
    (ADR 0008); ihre Chunks laufen über die Folien-Gliederung statt über die
    Überschriften-Erkennung. Leer oder `None` heißt: ausschließlich Prosa —
    dann läuft exakt der bisherige Pfad.
    """
    folien_dokumente = folien_dokumente or set()
    if folien_dokumente:
        folien_chunks = [c for c in studienbrief_chunks
                         if _dokument_von(c) in folien_dokumente]
        prosa_chunks = [c for c in studienbrief_chunks
                        if _dokument_von(c) not in folien_dokumente]
        themen: List[Thema] = []
        # Je Foliensatz getrennt: die Kapitelnummer steht auf seiner Titelfolie,
        # und Kopfzeilen dürfen über Dateigrenzen hinweg nicht zusammenlaufen.
        for dokument in dict.fromkeys(_dokument_von(c) for c in folien_chunks):
            themen += _themen_aus_foliensatz(
                [c for c in folien_chunks if _dokument_von(c) == dokument], len(themen))
        if prosa_chunks:  # gemischtes Modul: Prosa-Teil wie gehabt
            for thema in baue_themenkatalog(prosa_chunks):
                thema.id = f"t-{len(themen) + 1:02d}"
                themen.append(thema)
        return _qualifiziere_doppelte_titel(themen)

    kandidaten = _finde_kandidaten(studienbrief_chunks)
    ebene = _waehle_ebene(kandidaten)
    if ebene is None:
        return _themen_aus_seitenbloecken(studienbrief_chunks)
    gewaehlt = [k for k in kandidaten if k.ebene <= ebene]
    # Nur die tiefste erlaubte Ebene wird zum Thema; flachere sind Kontext.
    auf_ebene = [k for k in gewaehlt if k.ebene == ebene]
    # Studienbriefe wiederholen Titel je Kapitel ("2.2 Einführung", "3.2
    # Einführung", …). Unqualifiziert stünden sie mehrfach gleichlautend im
    # Katalog und wären für Lernende nicht unterscheidbar; die Kapitelnummer
    # trennt sie, ohne dass ein Abschnitt aus der Abdeckung fällt.
    mehrfach = {k.titel for k in auf_ebene
                if sum(1 for a in auf_ebene if a.titel == k.titel) > 1}
    themen: List[Thema] = []
    for k in auf_ebene:
        titel = f"{k.nummer} {k.titel}" if k.titel in mehrfach else k.titel
        themen.append(Thema(
            id=f"t-{len(themen) + 1:02d}", titel=titel,
            beschreibung=f"Abschnitt {k.nummer} des Studienbriefs",
            belege=[Beleg(quelle="studienbrief", position=k.position, chunk_id=k.chunk_id)],
        ))
    if not themen:
        return _themen_aus_seitenbloecken(studienbrief_chunks)
    # Wächter: erkannte "Gliederung", die den Stoff nicht aufteilt, ist keine.
    if (len(studienbrief_chunks) >= MIN_CHUNKS_FUER_WAECHTER
            and _groesster_themenanteil(themen, studienbrief_chunks) > MAX_THEMEN_ANTEIL):
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
    mittig: Dict[str, int] = {}         # Vorkommen mitten im Satz (auswertbar)
    nomen: Dict[str, int] = {}          # davon großgeschrieben
    streuung: Dict[str, set] = {}       # in wie vielen Chunks kommt das Wort vor
    for chunk in transkript_chunks:
        for treffer in _WORT_RE.finditer(chunk.text):
            w = treffer.group(0)
            wl = w.lower()
            if wl in STOPPWOERTER or len(wl) < 6:
                continue
            haeufigkeit[wl] = haeufigkeit.get(wl, 0) + 1
            fundort.setdefault(wl, chunk)
            streuung.setdefault(wl, set()).add(chunk.id)
            # Am Satzanfang ist jedes Wort groß — dort sagt die Schreibung
            # nichts über die Wortart aus, also gar nicht erst mitzählen.
            if not _am_satzanfang(chunk.text, treffer.start()):
                mittig[wl] = mittig.get(wl, 0) + 1
                if w[0].isupper():
                    nomen[wl] = nomen.get(wl, 0) + 1

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

    def _ist_fachbegriff(w: str, n: int) -> bool:
        """Fachbegriff oder Redefüllsel? Zwei Merkmale, beide am Material geeicht.

        Ohne diese Prüfung landen schlicht die häufigsten Transkriptwörter im
        Katalog — bei REST waren das "Bedeutet", "Nämlich" und "Punkte".

        1. **Nomen**: Deutsch schreibt Substantive groß, und ein Thema ist immer
           ein Substantiv. Mitten im Satz großgeschrieben zu sein trennt
           "Schaltfunktion" (99 %) von "bedeutet" (0 %) und "nämlich" (0 %).
        2. **Streuung**: Ein Fachbegriff gehört zu seinem Thema und taucht darum
           nur in wenigen Chunks auf; ein Allerweltswort zieht sich durch die
           ganze Vorlesung. "Punkte" ist ein Nomen, steht aber in 6,4 % aller
           Chunks — "Informationsgehalt" in 4,3 %, "Register" in 3,7 %.
        """
        auswertbar = mittig.get(w, 0)
        # Fehlende Evidenz ist kein Gegenbeweis: Ein Begriff, der stets einen
        # Satz eröffnet ("Hashtabellen speichern …"), lässt sich so nicht
        # beurteilen und wird deshalb nicht verworfen.
        if auswertbar and nomen.get(w, 0) / auswertbar <= MIN_NOMEN_ANTEIL:
            return False
        if len(transkript_chunks) < MIN_CHUNKS_FUER_STREUUNG:
            return True
        return len(streuung.get(w, ())) / len(transkript_chunks) < MAX_STREUUNG

    neue = [(w, n) for w, n in haeufigkeit.items()
            if n >= min_nennungen and w not in themen_woerter and _ist_fachbegriff(w, n)]
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


# Mindestanteil der (stoppwortbereinigten) Themen-Titelwörter, der im Chunk
# vorkommen muss, damit der Chunk überhaupt als Kandidat für dieses Thema
# gilt. Vorher genügte ein einziges gemeinsames Wort ohne Stoppwortfilter
# (Befund 3) — "eines", "diese", "unter", "werden" fingen damit praktisch
# jeden Chunk. Ein Titel hat meist nur 1-3 inhaltstragende Wörter, darum
# reicht die Hälfte davon als belastbares Signal.
MIN_TITEL_UEBERLAPP_ANTEIL = 0.5
# Mehrfachzuordnung (ein Chunk zu mehreren Themen) nur oberhalb dieser
# höheren Schwelle: sonst nimmt der Chunk automatisch jedes Thema mit, dessen
# Titel zufällig ebenfalls (teilweise) passt, selbst wenn ein anderes Thema
# deutlich besser trifft.
MIN_TITEL_UEBERLAPP_ANTEIL_MEHRFACH = 0.75


def _titel_ueberlappung(titel_woerter: "set[str]", chunk_woerter: "set[str]") -> float:
    """Anteil der Titelwörter, die im Chunk vorkommen (0 bei leerem Titel)."""
    if not titel_woerter:
        return 0.0
    return len(titel_woerter & chunk_woerter) / len(titel_woerter)


def ordne_chunks_zu(themen: List[Thema], chunks: List[Chunk]) -> Dict[str, List[Chunk]]:
    """Ordnet jedem Thema die inhaltlich zugehörigen Chunks zu (für die Generierung).

    Studienbrief-Chunks werden sequenziell zugeordnet: Ein Thema `besitzt`
    alles ab seinem Beleg-Chunk bis zum Beleg-Chunk des nächsten Themas.
    Vorlesungs-/Folien-Chunks per Wortüberlappung mit dem Titel — stoppwort-
    bereinigt, mit Mindestquote, an das beste Thema (argmax); nur oberhalb
    einer zweiten, höheren Schwelle geht ein Chunk an mehr als eines.
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

    titel_woerter_je_thema = {
        thema.id: {w.lower() for w in _WORT_RE.findall(thema.titel)} - STOPPWOERTER
        for thema in themen
    }
    andere = [c for c in chunks if c.quelle != "studienbrief"]
    for chunk in andere:
        chunk_woerter = {w.lower() for w in _WORT_RE.findall(chunk.text)} - STOPPWOERTER
        bewertungen = [
            (_titel_ueberlappung(titel_woerter_je_thema[thema.id], chunk_woerter), thema.id)
            for thema in themen
        ]
        bester_score = max((s for s, _ in bewertungen), default=0.0)
        if bester_score < MIN_TITEL_UEBERLAPP_ANTEIL:
            continue
        # Das beste Thema bekommt den Chunk immer; weitere Themen nur, wenn
        # ihre eigene Überlappung ebenfalls die (höhere) Mehrfachschwelle reißt.
        ziel_themen = {tid for score, tid in bewertungen
                       if score == bester_score or score >= MIN_TITEL_UEBERLAPP_ANTEIL_MEHRFACH}
        for tid in ziel_themen:
            zuordnung[tid].append(chunk)
    return zuordnung


# --- Benennung durch das Reasoning-LLM (ADR 0008) ---------------------------

BENENNUNG_SYSTEM = (
    "Du benennst Themen eines Lernpakets für eine Klausurvorbereitung. "
    "Du bekommst je Thema Auszüge aus dem Studienmaterial und gibst einen "
    "kurzen, fachlich präzisen Titel zurück. Erfinde nichts, was nicht im "
    "Auszug steht."
)
# So viel Text je Thema geht in den Prompt — genug, um das Thema zu erkennen,
# wenig genug, dass 40 Themen in einen Aufruf passen.
BENENNUNG_ZEICHEN_JE_THEMA = 600


def _benennungs_prompt(themen: List[Thema], zuordnung: Dict[str, List[Chunk]]) -> str:
    teile = ["Benenne jedes Thema. Antworte als JSON-Objekt {\"t-01\": \"Titel\", …} "
             "mit genau einem Titel je Thema-ID.",
             "Regeln: 3–6 Wörter, deutsches Substantiv-Titel (kein Satz), keine "
             "Formeln, kein Markdown, keine Nummerierung. Wenn der Auszug nichts "
             "hergibt, gib den bisherigen Titel unverändert zurück.", ""]
    for thema in themen:
        auszug = " ".join(c.text for c in zuordnung.get(thema.id, [])[:6])
        auszug = re.sub(r"\s+", " ", auszug)[:BENENNUNG_ZEICHEN_JE_THEMA]
        teile.append(f"{thema.id} (bisher: {thema.titel!r})\n{auszug}\n")
    return "\n".join(teile)


def benenne_themen(themen: List[Thema], zuordnung: Dict[str, List[Chunk]],
                   llm) -> List[Thema]:
    """Lässt das LLM die Themen benennen — ein gebündelter Aufruf für alle.

    Nötig für Foliensätze (ADR 0008): Deren Titel stammen aus der Folien-
    Kopfzeile, und die trägt bei einem Teil der Folien Tabellen- oder
    Formelreste statt eines Namens. Gebündelt statt je Thema, weil ein Aufruf
    mit 40 kurzen Auszügen deutlich billiger ist als 40 Aufrufe — und weil das
    Modell die Titel so gegeneinander abgrenzen kann.

    Scheitert der Aufruf oder liefert er Unbrauchbares, bleiben die bisherigen
    Titel stehen: Die Benennung ist eine Verbesserung, kein Muss.
    """
    if llm is None or not themen:
        return themen
    try:
        antwort = llm.frage(BENENNUNG_SYSTEM, _benennungs_prompt(themen, zuordnung),
                            max_tokens=2048)
        vorschlaege = extrahiere_json(antwort)
    except Exception as fehler:  # pragma: no cover - Netz/Format
        log.warning("Themen-Benennung fehlgeschlagen (%s) — bisherige Titel bleiben.",
                    fehler)
        return themen
    if not isinstance(vorschlaege, dict):
        log.warning("Themen-Benennung lieferte kein Objekt — bisherige Titel bleiben.")
        return themen
    uebernommen = 0
    for thema in themen:
        titel = vorschlaege.get(thema.id)
        if not isinstance(titel, str):
            continue
        titel = _bereinige_titel(_TITEL_RAUSCH_RE.sub("", titel)).strip(" :–-—")
        # Derselbe Maßstab wie für Folien-Kopfzeilen: keine Formeln, keine
        # Tabellenreste, echter Text. Was ihn nicht besteht, wird verworfen.
        if titel and _taugt_als_kopfzeile(titel) and len(titel) <= 80:
            thema.titel = titel
            uebernommen += 1
    log.info("Themen benannt: %d von %d Titeln übernommen", uebernommen, len(themen))
    return _qualifiziere_doppelte_titel(themen)
