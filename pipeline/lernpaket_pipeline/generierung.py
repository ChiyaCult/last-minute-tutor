"""Generierung von Lehrblöcken und format-parametrischen Quizfragen (Issues #21, #24, #25, #26).

Treue-Vertrag (ADR 0003): Jedes Artefakt trägt Belege auf Chunks; behauptet
wird nur Belegbares. Schweigt das Material zu einem Thema, entsteht eine
Materiallücke statt erfundenem Inhalt.

Zwei Generatoren mit gleichem Vertrag:
- `HeuristischerGenerator` — deterministisch, offline, kostenlos. Default ohne
  API-Schlüssel und Grundlage der Tests (PRD: Generierung auf Vertragsebene testen).
- `LLMGenerator` — Remote-Spitzenmodell (ADR 0002); erzwingt den Beleg-Vertrag
  nachträglich: Artefakte ohne gültigen Chunk-Beleg werden verworfen und als
  Materiallücke gemeldet.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Tuple

from .extraktion.formeln import ist_formelzeile
from .llm import (LLMDienstNichtVerfuegbar, ReasoningLLM, extrahiere_json,
                  ist_voruebergehend)
from .relevanz import _MARKER_RE, _WORT_RE
from .vertrag import Beleg, Chunk, Frage, Lehrblock, Materialluecke, Thema

ALLE_FORMATE = ("mc", "rechnen", "freitext", "beweis")

log = logging.getLogger("lernpaket")

_SATZ_RE = re.compile(r"(?<=[.!?])\s+")
_DEFINITION_RE = re.compile(
    r"\b(ist|sind|bezeichnet|heißt|nennt man|versteht man unter|bedeutet|beschreibt)\b",
    re.IGNORECASE,
)
_ZAHL_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)(?![\w.])")
_SATZ_AUSSAGE_RE = re.compile(r"\b(Satz|Lemma|Theorem|gilt|genau dann)\b")


@dataclass
class GenerierungsErgebnis:
    lehrbloecke: List[Lehrblock] = field(default_factory=list)
    fragen: List[Frage] = field(default_factory=list)
    materialluecken: List[Materialluecke] = field(default_factory=list)


class Generator(Protocol):
    def erzeuge(self, themen: List[Thema], zuordnung: Dict[str, List[Chunk]],
                zielformat: str) -> GenerierungsErgebnis: ...


def _saetze(chunks: List[Chunk]) -> List[Tuple[str, Chunk]]:
    ergebnis: List[Tuple[str, Chunk]] = []
    for chunk in chunks:
        flach = re.sub(r"\s+", " ", chunk.text).strip()
        for satz in _SATZ_RE.split(flach):
            satz = satz.strip()
            if 25 <= len(satz) <= 400:
                ergebnis.append((satz, chunk))
    return ergebnis


def _beleg(chunk: Chunk) -> Beleg:
    return Beleg(quelle=chunk.quelle, position=chunk.position, chunk_id=chunk.id)


def _kuerze(text: str, max_len: int = 160) -> str:
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


class HeuristischerGenerator:
    """Deterministische Extraktiv-Generierung: nur wörtlich Belegbares."""

    def erzeuge(self, themen: List[Thema], zuordnung: Dict[str, List[Chunk]],
                zielformat: str) -> GenerierungsErgebnis:
        ergebnis = GenerierungsErgebnis()
        definitionen_je_thema: Dict[str, str] = {}

        for thema in themen:
            chunks = zuordnung.get(thema.id, [])
            saetze = _saetze(chunks)
            if not saetze:
                ergebnis.materialluecken.append(Materialluecke(
                    thema_id=thema.id, art="schweigen",
                    beschreibung=f"Zum Thema '{thema.titel}' liefern die Materialien "
                                 f"keinen verwertbaren Inhalt — nichts erfunden.",
                ))
                continue

            titel_woerter = {w.lower() for w in _WORT_RE.findall(thema.titel)}
            definitionen = [
                (s, c) for s, c in saetze
                if _DEFINITION_RE.search(s)
                and (not titel_woerter or titel_woerter & {w.lower() for w in _WORT_RE.findall(s)})
            ]
            if not definitionen:
                definitionen = [(s, c) for s, c in saetze if _DEFINITION_RE.search(s)][:1]
            if definitionen:
                definitionen_je_thema[thema.id] = definitionen[0][0]

            kern = definitionen[:2] or saetze[:2]
            ergebnis.lehrbloecke.append(Lehrblock(
                id=f"lb-{thema.id}-1", thema_id=thema.id, tiefe="auffrischung",
                inhalt_markdown=f"## {thema.titel}\n\n"
                                + "\n".join(f"- {s}" for s, _ in kern),
                belege=sorted({_beleg(c).chunk_id: _beleg(c) for _, c in kern}.values(),
                              key=lambda b: b.chunk_id),
            ))

            formeln = []
            for chunk in chunks:
                for zeile in chunk.text.splitlines():
                    z = zeile.strip()
                    if z.startswith("$$") or ist_formelzeile(z):
                        formeln.append((z if z.startswith("$$") else f"$${z}$$", chunk))
            vertiefung_saetze = [p for p in saetze if p not in kern][:6]
            if vertiefung_saetze or formeln:
                teile = [f"## {thema.titel} — Vertiefung", ""]
                teile += [f"{s}" for s, _ in vertiefung_saetze]
                teile += [f for f, _ in formeln[:4]]
                quellen = {c.id: c for _, c in vertiefung_saetze}
                quellen.update({c.id: c for _, c in formeln[:4]})
                ergebnis.lehrbloecke.append(Lehrblock(
                    id=f"lb-{thema.id}-2", thema_id=thema.id, tiefe="vertiefung",
                    inhalt_markdown="\n\n".join(teile),
                    belege=[_beleg(c) for c in sorted(quellen.values(), key=lambda c: c.id)],
                ))

        for idx, thema in enumerate(themen):
            chunks = zuordnung.get(thema.id, [])
            saetze = _saetze(chunks)
            if not saetze:
                continue
            fragen = self._fragen_fuer_thema(idx, thema, saetze, definitionen_je_thema, themen)
            # Diagnose: eine Frage pro Thema, bevorzugt im vorgeschlagenen Zielformat.
            diagnose = next((f for f in fragen if f.format == zielformat), None) or (
                fragen[0] if fragen else None)
            if diagnose:
                diagnose.diagnose = True
            ergebnis.fragen.extend(fragen)
        return ergebnis

    def _fragen_fuer_thema(self, idx: int, thema: Thema,
                           saetze: List[Tuple[str, Chunk]],
                           definitionen: Dict[str, str],
                           alle_themen: List[Thema]) -> List[Frage]:
        fragen: List[Frage] = []
        definition = definitionen.get(thema.id)
        def_chunk = next((c for s, c in saetze if s == definition), None)

        # freitext — geht immer, wenn es wenigstens einen brauchbaren Satz gibt.
        antwort_satz, antwort_chunk = (definition, def_chunk) if definition else saetze[0]
        fragen.append(Frage(
            id=f"q-{thema.id}-freitext-1", thema_id=thema.id, format="freitext",
            frage_markdown=f"Erläutere in eigenen Worten: **{thema.titel}**.",
            antwort=antwort_satz,
            erklaerung_markdown=f"Laut Material: {antwort_satz}",
            belege=[_beleg(antwort_chunk)] if antwort_chunk else [],
        ))

        # mc — Definition als korrekte Option, Definitionen anderer Themen als Distraktoren.
        if definition and def_chunk is not None:
            distraktoren = [
                _kuerze(d) for tid, d in sorted(definitionen.items()) if tid != thema.id
            ][:3]
            while len(distraktoren) < 3:
                distraktoren.append(
                    f"{thema.titel} wird im Studienbrief nicht behandelt.")
            optionen = distraktoren[:3]
            korrekt_pos = idx % 4
            optionen.insert(korrekt_pos, _kuerze(definition))
            fragen.append(Frage(
                id=f"q-{thema.id}-mc-1", thema_id=thema.id, format="mc",
                frage_markdown=f"Welche Aussage zu **{thema.titel}** trifft laut Material zu?",
                optionen=optionen, antwort="ABCD"[korrekt_pos],
                erklaerung_markdown=f"Korrekt ist: {definition}",
                belege=[_beleg(def_chunk)],
            ))

        # rechnen — nur, wenn das Material einen Satz mit konkreter Zahl hergibt.
        # Zahlen am Satzanfang sind Abschnittsnummern, keine Werte.
        for satz, chunk in saetze:
            zahlen = [m.group(1) for m in _ZAHL_RE.finditer(satz) if m.start() > 0]
            if len(zahlen) == 1:
                zahl = zahlen[0]
                fragen.append(Frage(
                    id=f"q-{thema.id}-rechnen-1", thema_id=thema.id, format="rechnen",
                    frage_markdown="Ergänze den Wert aus dem Material: "
                                   + satz.replace(zahl, "**?**", 1),
                    antwort=zahl,
                    erklaerung_markdown=f"Laut Material: {satz}",
                    belege=[_beleg(chunk)],
                ))
                break

        # beweis — nur bei satzartigen Aussagen im Material.
        for satz, chunk in saetze:
            if _SATZ_AUSSAGE_RE.search(satz):
                folge = [s for s, c in saetze if s != satz and c.id == chunk.id][:2]
                fragen.append(Frage(
                    id=f"q-{thema.id}-beweis-1", thema_id=thema.id, format="beweis",
                    frage_markdown=f"Skizziere Begründung/Beweis der Aussage: „{_kuerze(satz, 220)}“",
                    antwort=" ".join(folge) if folge else satz,
                    erklaerung_markdown="Belegstelle im Material beachten.",
                    belege=[_beleg(chunk)],
                ))
                break
        return fragen


# So viele Chunks gehen je Thema in den Generierungs-Prompt. 30 × 1400 Zeichen
# sind rund 14k Token — passt in jedes hier vorgesehene Kontextfenster, auch
# lokal (Ollama mit LERNPAKET_OLLAMA_CTX=32768).
MAX_PROMPT_CHUNKS = 30

# So viele dauerhafte Fehler in Folge gelten als Konfigurationsproblem statt als
# Materialproblem. Anlass: ein falscher Ollama-Modellname ließ alle 19 Themen mit
# HTTP 404 scheitern, und die Pipeline schrieb ein leeres Paket mit Exit-Code 0.
MAX_DAUERFEHLER = 3

# Quoten je Quelle, damit der Studienbrief den Prompt nicht monopolisiert.
# Gemessener Anlass: ohne Quoten landeten 8 von 14 Themen mit ausschließlich
# Studienbrief-Chunks im Prompt, obwohl ihnen bis zu 228 Folien-Chunks
# zugeordnet waren — `ordne_chunks_zu` hängt Nicht-Studienbrief hinten an, und
# ein simples Abschneiden erwischte davon nichts.
PROMPT_QUOTEN = (("studienbrief", 12), ("folie", 8), ("vorlesung", 6),
                 ("altklausur", 2), ("uebung", 2))


def klausur_vokabular(zuordnung: Dict[str, List[Chunk]]) -> Dict[str, int]:
    """Wortschatz der Altklausuren/Übungen — das schriftliche Relevanzsignal.

    Aus der Zuordnung statt aus allen Chunks, damit der Generator-Vertrag
    unverändert bleibt.
    """
    haeufigkeit: Dict[str, int] = {}
    gesehen: set = set()
    for chunks in zuordnung.values():
        for chunk in chunks:
            if chunk.quelle not in ("altklausur", "uebung") or chunk.id in gesehen:
                continue
            gesehen.add(chunk.id)
            for wort in set(_WORT_RE.findall(chunk.text.lower())):
                haeufigkeit[wort] = haeufigkeit.get(wort, 0) + 1
    return haeufigkeit


def _chunk_score(chunk: Chunk, titel_woerter: "set[str]",
                 klausur: Dict[str, int]) -> float:
    woerter = {w.lower() for w in _WORT_RE.findall(chunk.text)}
    score = 3.0 * len(titel_woerter & woerter) / max(len(titel_woerter), 1)
    if klausur:
        naehe = sum(klausur.get(w, 0) for w in woerter)
        score += 2.0 * min(1.0, naehe / 60.0)
    if _MARKER_RE.search(chunk.text):
        score += 2.5  # der Professor hat es mündlich als klausurrelevant markiert
    return score


def waehle_prompt_chunks(thema: Thema, chunks: List[Chunk],
                         klausur: Dict[str, int]) -> List[Chunk]:
    """Wählt die Chunks für den Prompt: nach Relevanz sortiert, Quellen gemischt.

    Vorher wurden schlicht die ersten Chunks genommen — also Studienbrief in
    Seitenreihenfolge, weil `ordne_chunks_zu` in dieser Reihenfolge einsammelt.
    Vorlesungsmarker und Altklausurnähe blieben dabei ungenutzt.
    """
    if len(chunks) <= MAX_PROMPT_CHUNKS:
        return chunks
    titel_woerter = {w.lower() for w in _WORT_RE.findall(thema.titel)}
    sortiert = sorted(chunks, key=lambda c: -_chunk_score(c, titel_woerter, klausur))

    gewaehlt: List[Chunk] = []
    genommen: set = set()
    for quelle, quote in PROMPT_QUOTEN:
        for chunk in sortiert:
            if len(gewaehlt) >= MAX_PROMPT_CHUNKS:
                break
            if chunk.quelle == quelle and chunk.id not in genommen:
                gewaehlt.append(chunk)
                genommen.add(chunk.id)
                quote -= 1
                if quote <= 0:
                    break
    # Restplätze (etwa weil eine Quelle im Modul fehlt) nach reinem Score füllen.
    for chunk in sortiert:
        if len(gewaehlt) >= MAX_PROMPT_CHUNKS:
            break
        if chunk.id not in genommen:
            gewaehlt.append(chunk)
            genommen.add(chunk.id)
    # Dokumentreihenfolge wiederherstellen: zusammenhängender Text liest sich
    # für das Modell besser als nach Score durchgeschütteltes Material.
    reihenfolge = {c.id: i for i, c in enumerate(chunks)}
    return sorted(gewaehlt, key=lambda c: reihenfolge[c.id])


_SYSTEM_PROMPT = (
    "Du erzeugst Lernmaterial strikt aus den übergebenen Quell-Chunks. "
    "Treue-Vertrag: Behaupte NUR, was ein Chunk belegt, und gib zu jedem Artefakt "
    "die chunk_ids der Belege an. Wenn das Material zu einem Punkt schweigt oder "
    "sich widerspricht, melde eine materialluecke statt zu erfinden. "
    "Formeln als LaTeX in $...$/$$...$$. Antworte ausschließlich mit JSON."
)


class LLMGenerator:
    """Generierung über das Remote-Spitzenmodell; erzwingt den Beleg-Vertrag."""

    def __init__(self, llm: ReasoningLLM):
        self.llm = llm

    def erzeuge(self, themen: List[Thema], zuordnung: Dict[str, List[Chunk]],
                zielformat: str) -> GenerierungsErgebnis:
        """Erzeugt je Thema einen LLM-Aufruf.

        Kein heuristischer Ersatz: Wer ein LLM angefordert hat, bekommt entweder
        LLM-Inhalt oder eine ehrliche Fehlermeldung. Ein stillschweigend
        heruntergestuftes Paket sähe später aus wie ein vollwertiges.
        """
        ergebnis = GenerierungsErgebnis()
        klausur = klausur_vokabular(zuordnung)
        dauerfehler = 0
        for nummer, thema in enumerate(themen, start=1):
            alle_chunks = zuordnung.get(thema.id, [])
            # Nur das Gezeigte darf belegt werden: sonst nimmt der Vertrag eine
            # chunk_id an, die das Modell nie gesehen hat.
            chunks = waehle_prompt_chunks(thema, alle_chunks, klausur)
            if not chunks:
                ergebnis.materialluecken.append(Materialluecke(
                    thema_id=thema.id, art="schweigen",
                    beschreibung=f"Kein Material zum Thema '{thema.titel}'.",
                ))
                continue
            try:
                roh = self.llm.frage(_SYSTEM_PROMPT,
                                     self._prompt(thema, chunks, zielformat))
            except Exception as fehler:
                if ist_voruebergehend(fehler):
                    # Der Dienst ist weg — weiterzufragen liefert nur weitere
                    # Fehlschläge. Abbrechen; der Antwort-Cache hält die bereits
                    # bezahlten Themen fest, ein zweiter Anlauf setzt dort auf.
                    raise LLMDienstNichtVerfuegbar(
                        f"LLM-Anbieter nicht erreichbar bei Thema {nummer} von "
                        f"{len(themen)} ('{thema.titel}'): {fehler}. Die bis hierhin "
                        "erzeugten Themen liegen im Antwort-Cache — derselbe Aufruf "
                        "später wiederholt kostet nur die noch fehlenden."
                    ) from fehler
                # Dauerhafter Fehler (Anfrage zu groß, Modell weg): Wiederholen
                # hilft nicht, also markieren und mit dem nächsten Thema weiter.
                dauerfehler += 1
                if dauerfehler >= MAX_DAUERFEHLER:
                    # Dreimal derselbe dauerhafte Fehler heißt: nicht das
                    # Material ist schuld, sondern die Konfiguration (Modellname
                    # falsch, Anfrage grundsätzlich abgelehnt). Weiterzumachen
                    # produziert ein leeres Paket, das später aussieht wie ein
                    # vollwertiges — genau das soll nicht passieren.
                    raise LLMDienstNichtVerfuegbar(
                        f"LLM-Aufruf schlägt dauerhaft fehl ({dauerfehler}× in Folge, "
                        f"zuletzt bei Thema {nummer} von {len(themen)} "
                        f"('{thema.titel}')): {fehler}. Das deutet auf die "
                        "Konfiguration hin, nicht auf das Material — Modellname "
                        "und Anbieter prüfen. Es wurde kein Paket geschrieben."
                    ) from fehler
                log.warning("LLM-Aufruf für Thema '%s' dauerhaft fehlgeschlagen: %s",
                            thema.titel, fehler)
                ergebnis.materialluecken.append(Materialluecke(
                    thema_id=thema.id, art="schweigen",
                    beschreibung=f"Thema '{thema.titel}': LLM-Aufruf fehlgeschlagen "
                                 f"({fehler}) — für dieses Thema fehlen Lehrblöcke "
                                 "und Fragen im Paket."))
                continue
            dauerfehler = 0
            self._uebernehme(thema, chunks, roh, ergebnis)
        for frage in ergebnis.fragen:
            if frage.thema_id and frage.format == zielformat:
                # eine Diagnosefrage pro Thema
                if not any(f.diagnose and f.thema_id == frage.thema_id for f in ergebnis.fragen):
                    frage.diagnose = True
        # Letzte Sicherung: Ein Paket ohne einen einzigen Lehrblock und ohne eine
        # einzige Frage ist kein Lernpaket. Lieber laut abbrechen als etwas
        # schreiben, das erst drei Tage vor der Klausur als leer auffällt.
        if themen and not ergebnis.lehrbloecke and not ergebnis.fragen:
            raise LLMDienstNichtVerfuegbar(
                f"Die Generierung lieferte für keines der {len(themen)} Themen "
                "einen Lehrblock oder eine Frage. Es wurde kein Paket geschrieben; "
                "die Materiallücken nennen den Grund je Thema.")
        return ergebnis

    def _prompt(self, thema: Thema, chunks: List[Chunk], zielformat: str) -> str:
        chunk_text = "\n\n".join(
            f"[{c.id} | {c.quelle} {c.position}]\n{c.text}" for c in chunks
        )
        return (
            f"Thema: {thema.titel}\nZielformat der Klausur: {zielformat}\n\n"
            f"Quell-Chunks:\n{chunk_text}\n\n"
            "Erzeuge JSON mit Feldern:\n"
            "{\"lehrbloecke\": [{\"tiefe\": \"auffrischung\"|\"vertiefung\", "
            "\"inhalt_markdown\": str, \"chunk_ids\": [str]}],\n"
            " \"fragen\": [{\"format\": \"mc\"|\"rechnen\"|\"freitext\"|\"beweis\", "
            "\"frage_markdown\": str, \"optionen\": [str]|null, \"antwort\": str, "
            "\"erklaerung_markdown\": str, \"chunk_ids\": [str]}],\n"
            " \"materialluecken\": [{\"beschreibung\": str, \"art\": \"schweigen\"|\"widerspruch\"}]}\n"
            f"Genau 1 Auffrischungs- und 1 Vertiefungs-Lehrblock; 2–4 Fragen, "
            f"darunter mindestens eine im Format '{zielformat}'."
        )

    def _uebernehme(self, thema: Thema, chunks: List[Chunk], roh: str,
                    ergebnis: GenerierungsErgebnis) -> None:
        gueltige_ids = {c.id: c for c in chunks}

        def belege_von(chunk_ids: Optional[List[str]]) -> List[Beleg]:
            return [_beleg(gueltige_ids[cid]) for cid in (chunk_ids or []) if cid in gueltige_ids]

        try:
            daten = extrahiere_json(roh)
        except ValueError:
            ergebnis.materialluecken.append(Materialluecke(
                thema_id=thema.id, art="schweigen",
                beschreibung=f"Generierung zum Thema '{thema.titel}' lieferte kein "
                             f"auswertbares Ergebnis.",
            ))
            return
        for i, lb in enumerate(daten.get("lehrbloecke", []), start=1):
            belege = belege_von(lb.get("chunk_ids"))
            if not belege:
                ergebnis.materialluecken.append(Materialluecke(
                    thema_id=thema.id, art="schweigen",
                    beschreibung=f"Lehrblock ohne gültigen Beleg verworfen ('{thema.titel}').",
                ))
                continue
            ergebnis.lehrbloecke.append(Lehrblock(
                id=f"lb-{thema.id}-{i}", thema_id=thema.id,
                tiefe=lb.get("tiefe", "vertiefung"),
                inhalt_markdown=lb.get("inhalt_markdown", ""), belege=belege))
        zaehler: Dict[str, int] = {}
        for fr in daten.get("fragen", []):
            belege = belege_von(fr.get("chunk_ids"))
            fmt = fr.get("format", "freitext")
            if fmt not in ALLE_FORMATE or not belege:
                continue
            zaehler[fmt] = zaehler.get(fmt, 0) + 1
            ergebnis.fragen.append(Frage(
                id=f"q-{thema.id}-{fmt}-{zaehler[fmt]}", thema_id=thema.id, format=fmt,
                frage_markdown=fr.get("frage_markdown", ""),
                optionen=fr.get("optionen") if fmt == "mc" else None,
                antwort=str(fr.get("antwort", "")),
                erklaerung_markdown=fr.get("erklaerung_markdown", ""), belege=belege))
        for ml in daten.get("materialluecken", []):
            ergebnis.materialluecken.append(Materialluecke(
                thema_id=thema.id, beschreibung=ml.get("beschreibung", ""),
                art=ml.get("art", "schweigen")))
