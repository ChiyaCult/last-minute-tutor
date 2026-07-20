"""Orchestrierung der Aufbereitung in zwei getrennten Schritten:

1. **Extraktion** (`extrahiere_material`): Modulverzeichnis → Chunks +
   Quellenlage + Materiallücken. Teuer (ASR, OCR), aber LLM-frei; das Ergebnis
   wird als `extraktion/` im Modulverzeichnis persistiert und ASR-Transkripte
   werden pro Video gecacht — erneute Läufe kosten Sekunden.
2. **Generierung** (`generiere_lernpaket`): Extraktionsergebnis → Lernpaket
   (Themen, Lehrblöcke, Quiz, Manifest). Hier läuft das LLM; verschiedene
   Anbieter/Modelle lassen sich ausprobieren, ohne neu zu extrahieren.

Pro Modul unabhängig aufrufbar (Issue #33, ADR 0001). Pflichtquellen
(Studienbrief-PDF, Vorlesungsvideos) werden vorausgesetzt, Optionalquellen
(Altklausuren, Übungen) genutzt, wenn vorhanden — sonst graceful degradation
mit `relevanz_unsicherheit: hoch` (Issue #31).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .chunks import chunks_aus_folien, chunks_aus_seiten, chunks_aus_transkript
from .extraktion.audio import Transkribierer, Transkript, TranskriptSegment
from .extraktion.folien import FolienLeser, SzenenErkenner, extrahiere_folien
from .extraktion.formeln import DokumentParser, waehle_parser
from .extraktion.pdf import (Ocr, Seite, ist_verklebt, lies_pdf,
                             seiten_mit_bildern)
from .generierung import Generator, HeuristischerGenerator, LLMGenerator
from .llm import hole_llm
from .relevanz import finde_relevanz_marker, gewichte_themen
from .themen import baue_themenkatalog, ergaenze_aus_transkript, ordne_chunks_zu
from .verifikation import verifiziere
from .vertrag import (Chunk, Lernpaket, Manifest, Materialluecke, Quelle,
                      pruefe_vertrag, schreibe_lernpaket)
from .zielformat import erkenne_zielformat

EXTRAKTIONS_ORDNER = "extraktion"

log = logging.getLogger("lernpaket")


def _mb(pfad: Path) -> float:
    return pfad.stat().st_size / 1_048_576


@dataclass
class QuellenLage:
    studienbrief: Path
    vorlesungen: List[Path] = field(default_factory=list)
    altklausuren: List[Path] = field(default_factory=list)
    uebungen: List[Path] = field(default_factory=list)

    @property
    def optionalquellen_vorhanden(self) -> bool:
        return bool(self.altklausuren or self.uebungen)


@dataclass
class Extraktion:
    """Persistierbares Ergebnis des Extraktionsschritts (LLM-frei)."""

    quellen: List[Quelle] = field(default_factory=list)
    optionalquellen_vorhanden: bool = False
    chunks: List[Chunk] = field(default_factory=list)
    materialluecken: List[Materialluecke] = field(default_factory=list)
    erzeugt_am: str = ""


VIDEO_ENDUNGEN = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi")


def _dateien_mit_endung(verzeichnis: Optional[Path], endungen) -> List[Path]:
    if verzeichnis is None or not verzeichnis.is_dir():
        return []
    return sorted(p for p in verzeichnis.iterdir()
                  if p.is_file() and p.suffix.lower() in endungen)


def _unterordner(modul_dir: Path, *namen: str) -> Optional[Path]:
    """Findet einen Unterordner unabhängig von Groß-/Kleinschreibung."""
    for eintrag in sorted(modul_dir.iterdir()):
        if eintrag.is_dir() and eintrag.name.lower() in namen:
            return eintrag
    return None


def finde_quellen(modul_dir: Path) -> QuellenLage:
    """Erkennt die Materiallage eines Modulverzeichnisses per Konvention.

    - Studienbrief: `studienbrief*.pdf`, sonst das größte PDF auf oberster Ebene.
    - Vorlesungen: Videodateien (`VIDEO_ENDUNGEN`) auf oberster Ebene oder in
      `vorlesungen/` (Groß-/Kleinschreibung egal).
    - Optionalquellen: PDFs in `altklausuren/` / `uebungen/` sowie Dateien
      `altklausur*.pdf` / `uebung*.pdf` auf oberster Ebene.
    """
    modul_dir = Path(modul_dir)
    pdfs = sorted(modul_dir.glob("*.pdf"))
    altklausuren = _dateien_mit_endung(
        _unterordner(modul_dir, "altklausuren"), (".pdf",)) + [
        p for p in pdfs if p.name.lower().startswith("altklausur")]
    uebungen = _dateien_mit_endung(
        _unterordner(modul_dir, "uebungen", "übungen"), (".pdf",)) + [
        p for p in pdfs if p.name.lower().startswith(("uebung", "übung"))]
    kandidaten = [p for p in pdfs if p not in altklausuren and p not in uebungen]
    studienbrief = next(
        (p for p in kandidaten if p.name.lower().startswith("studienbrief")), None)
    if studienbrief is None:
        if not kandidaten:
            raise FileNotFoundError(
                f"Pflichtquelle fehlt: kein Studienbrief-PDF in {modul_dir}")
        studienbrief = max(kandidaten, key=lambda p: p.stat().st_size)
    vorlesungen = (_dateien_mit_endung(modul_dir, VIDEO_ENDUNGEN)
                   + _dateien_mit_endung(_unterordner(modul_dir, "vorlesungen"),
                                         VIDEO_ENDUNGEN))
    return QuellenLage(studienbrief=studienbrief, vorlesungen=vorlesungen,
                       altklausuren=altklausuren, uebungen=uebungen)


def _normalisiere_seiten(seiten: List[Seite], parser: DokumentParser) -> List[Seite]:
    return [Seite(nummer=s.nummer, text=parser.nach_markdown(s.text), ist_scan=s.ist_scan)
            for s in seiten]


def _transkribiere_mit_cache(transkribierer: Transkribierer, video: Path,
                             cache_dir: Optional[Path]) -> Transkript:
    """ASR mit Datei-Cache: gleiche Datei (Name+Größe) wird nie zweimal transkribiert."""
    cache_datei = cache_dir / f"{video.name}.json" if cache_dir else None
    groesse = video.stat().st_size
    if cache_datei and cache_datei.exists():
        daten = json.loads(cache_datei.read_text(encoding="utf-8"))
        if daten.get("groesse") == groesse:
            log.info("Transkript aus Cache: %s (%d Segmente)",
                     video.name, len(daten.get("segmente", [])))
            return Transkript(datei=video.name, segmente=[
                TranskriptSegment(**s) for s in daten.get("segmente", [])])
    log.info("Transkribiere (ASR): %s (%.0f MB) …", video.name, _mb(video))
    start = time.perf_counter()
    transkript = transkribierer.transkribiere(video)
    log.info("Transkript fertig: %s — %d Segmente in %.0f s",
             video.name, len(transkript.segmente), time.perf_counter() - start)
    if cache_datei:
        cache_datei.parent.mkdir(parents=True, exist_ok=True)
        cache_datei.write_text(json.dumps(
            {"datei": video.name, "groesse": groesse,
             "segmente": [asdict(s) for s in transkript.segmente]},
            ensure_ascii=False), encoding="utf-8")
    return transkript


def extrahiere_material(
    modul_dir: Path,
    ocr: Optional[Ocr] = None,
    transkribierer: Optional[Transkribierer] = None,
    szenen_erkenner: Optional[SzenenErkenner] = None,
    folien_leser: Optional[FolienLeser] = None,
    parser: Optional[DokumentParser] = None,
    jetzt: Optional[datetime] = None,
) -> Extraktion:
    """Schritt 1: Materialien → Chunks + Materiallücken. Läuft ohne LLM.

    Alle schweren Werkzeuge sind injizierbar (Tests: Fakes; PRD-Testentscheidung).
    ASR-Transkripte werden unter `<modul>/extraktion/transkripte/` gecacht.
    """
    modul_dir = Path(modul_dir)
    quellen = finde_quellen(modul_dir)
    parser = parser or waehle_parser()
    materialluecken: List[Materialluecke] = []
    log.info("Extraktion: Modul '%s'", modul_dir.name)
    log.info("Quellen: Studienbrief %s · %d Vorlesung(en) · %d Altklausur(en) · %d Übung(en)",
             quellen.studienbrief.name, len(quellen.vorlesungen),
             len(quellen.altklausuren), len(quellen.uebungen))

    # Vorlesungslage prüfen: fehlende oder unausgewertete Videos werden gemeldet
    # statt still geschluckt (gleiche Linie wie Scan-Seiten, ADR 0003).
    if not quellen.vorlesungen:
        materialluecken.append(Materialluecke(
            thema_id="", art="schweigen",
            beschreibung="Keine Vorlesungsvideos gefunden (gesucht: "
                         + "/".join(f"*{e}" for e in VIDEO_ENDUNGEN)
                         + " auf oberster Ebene oder in vorlesungen/) — "
                         "Vorlesungsinhalte fehlen als Themen- und Relevanzquelle.",
        ))
    elif transkribierer is None and szenen_erkenner is None:
        materialluecken.append(Materialluecke(
            thema_id="", art="schweigen",
            beschreibung=f"{len(quellen.vorlesungen)} Vorlesungsvideo(s) gefunden, "
                         "aber nicht ausgewertet — Extras 'asr'/'folien' "
                         "installieren und erneut extrahieren.",
        ))

    # 1. Pflichtquelle Studienbrief (Textebene/Scan-Erkennung + OCR-Fallback).
    log.info("Lese Studienbrief-PDF %s%s …", quellen.studienbrief.name,
             " (mit OCR)" if ocr is not None else "")
    seiten = lies_pdf(quellen.studienbrief, ocr=ocr)
    log.info("Studienbrief: %d Seite(n) gelesen", len(seiten))
    scans_ohne_text = [s.nummer for s in seiten if s.ist_scan and not s.text.strip()]
    if scans_ohne_text:
        if ocr is None:
            hinweis = "Inhalt fehlt im Lernpaket. OCR-Extras installieren und neu aufbereiten."
        else:
            hinweis = ("trotz OCR kein Text erkannt — vermutlich Leerseiten "
                       "(dann fehlt nichts) oder unlesbare Scans.")
        materialluecken.append(Materialluecke(
            thema_id="", art="schweigen",
            beschreibung=f"{len(scans_ohne_text)} Scan-Seite(n) ohne Textebene und ohne "
                         f"OCR-Ergebnis (z. B. S. {scans_ohne_text[0]}) — {hinweis}",
        ))
    verklebte = [s.nummer for s in seiten if not s.ist_scan and ist_verklebt(s.text)]
    if verklebte:
        materialluecken.append(Materialluecke(
            thema_id="", art="schweigen",
            beschreibung=f"{len(verklebte)} Seite(n) mit verklebtem Text ohne "
                         f"Leerzeichen (z. B. S. {verklebte[0]}) — auch die "
                         "Zweitextraktion (pdfminer) konnte die Wortgrenzen nicht "
                         "rekonstruieren; Inhalte dieser Seiten sind nur "
                         "eingeschränkt nutzbar.",
        ))
    scan_nummern = {s.nummer for s in seiten if s.ist_scan}
    diagramm_seiten = [n for n in seiten_mit_bildern(quellen.studienbrief)
                       if n not in scan_nummern]
    if diagramm_seiten:
        materialluecken.append(Materialluecke(
            thema_id="", art="schweigen",
            beschreibung=f"{len(diagramm_seiten)} Seite(n) enthalten eingebettete "
                         f"Abbildungen/Diagramme (z. B. S. {diagramm_seiten[0]}) — "
                         "die Text-Extraktion erfasst nur Text, Diagramminhalte "
                         "fehlen im Lernpaket.",
        ))
    seiten = _normalisiere_seiten(seiten, parser)
    chunks: List[Chunk] = chunks_aus_seiten(seiten)

    # 2. Vorlesungen: Audio → Transkript (mit Cache), Folien → Standbilder.
    transkript_cache = modul_dir / EXTRAKTIONS_ORDNER / "transkripte"
    transkript_chunks: List[Chunk] = []
    anzahl = len(quellen.vorlesungen)
    for i, video in enumerate(quellen.vorlesungen, start=1):
        if transkribierer is not None or szenen_erkenner is not None:
            log.info("Vorlesung %d/%d: %s", i, anzahl, video.name)
        if transkribierer is not None:
            transkript = _transkribiere_mit_cache(transkribierer, video, transkript_cache)
            transkript_chunks.extend(
                chunks_aus_transkript(transkript, len(chunks) + len(transkript_chunks)))
        if szenen_erkenner is not None and folien_leser is not None:
            log.info("Folien-Erkennung: %s …", video.name)
            start = time.perf_counter()
            folien = extrahiere_folien(video, szenen_erkenner, folien_leser)
            folien_texte = [
                type(f)(nummer=f.nummer, zeit_sekunden=f.zeit_sekunden, bild=f.bild,
                        text=parser.nach_markdown(f.text)) for f in folien]
            transkript_chunks.extend(
                chunks_aus_folien(folien_texte, len(chunks) + len(transkript_chunks)))
            log.info("Folien fertig: %s — %d Folie(n) in %.0f s",
                     video.name, len(folien_texte), time.perf_counter() - start)
    chunks.extend(transkript_chunks)

    # 3. Optionalquellen (falls vorhanden) als Relevanzsignal einlesen.
    optional_chunks: List[Chunk] = []
    optionalquellen = ([(p, "altklausur") for p in quellen.altklausuren]
                       + [(p, "uebung") for p in quellen.uebungen])
    if optionalquellen:
        log.info("Lese %d Optionalquelle(n) (Altklausuren/Übungen) …", len(optionalquellen))
    for pfad, quelle in optionalquellen:
        opt_seiten = _normalisiere_seiten(lies_pdf(pfad, ocr=ocr), parser)
        optional_chunks.extend(
            chunks_aus_seiten(opt_seiten, quelle=quelle,
                              start_zaehler=len(chunks) + len(optional_chunks)))
    chunks.extend(optional_chunks)
    log.info("Extraktion fertig: %d Chunks, %d Materiallücke(n)",
             len(chunks), len(materialluecken))

    return Extraktion(
        quellen=(
            [Quelle(art="studienbrief", datei=quellen.studienbrief.name)]
            + [Quelle(art="vorlesung", datei=p.name) for p in quellen.vorlesungen]
            + [Quelle(art="altklausur", datei=p.name) for p in quellen.altklausuren]
            + [Quelle(art="uebung", datei=p.name) for p in quellen.uebungen]),
        optionalquellen_vorhanden=quellen.optionalquellen_vorhanden,
        chunks=chunks,
        materialluecken=materialluecken,
        erzeugt_am=(jetzt or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def schreibe_extraktion(extraktion: Extraktion, modul_dir: Path) -> Path:
    """Persistiert das Extraktionsergebnis unter `<modul>/extraktion/`."""
    ziel = Path(modul_dir) / EXTRAKTIONS_ORDNER
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "extraktion.json").write_text(json.dumps({
        "erzeugt_am": extraktion.erzeugt_am,
        "quellen": [asdict(q) for q in extraktion.quellen],
        "optionalquellen_vorhanden": extraktion.optionalquellen_vorhanden,
        "materialluecken": [asdict(m) for m in extraktion.materialluecken],
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (ziel / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in extraktion.chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False, sort_keys=True) + "\n")
    return ziel


def lade_extraktion(modul_dir: Path) -> Extraktion:
    """Liest ein persistiertes Extraktionsergebnis; wirft FileNotFoundError, wenn keins da ist."""
    ziel = Path(modul_dir) / EXTRAKTIONS_ORDNER
    kopf_datei = ziel / "extraktion.json"
    if not kopf_datei.exists():
        raise FileNotFoundError(
            f"Kein Extraktionsergebnis in {ziel} — zuerst `lernpaket extrahieren` ausführen.")
    kopf = json.loads(kopf_datei.read_text(encoding="utf-8"))
    chunks = []
    for zeile in (ziel / "chunks.jsonl").read_text(encoding="utf-8").splitlines():
        if zeile.strip():
            chunks.append(Chunk(**json.loads(zeile)))
    return Extraktion(
        quellen=[Quelle(**q) for q in kopf.get("quellen", [])],
        optionalquellen_vorhanden=kopf.get("optionalquellen_vorhanden", False),
        chunks=chunks,
        materialluecken=[Materialluecke(**m) for m in kopf.get("materialluecken", [])],
        erzeugt_am=kopf.get("erzeugt_am", ""),
    )


def generiere_lernpaket(
    extraktion: Extraktion,
    modul_id: str,
    titel: str,
    generator: Optional[Generator] = None,
    jetzt: Optional[datetime] = None,
    llm_anbieter: Optional[str] = None,
    llm_modell: Optional[str] = None,
) -> Lernpaket:
    """Schritt 2: Extraktionsergebnis → Lernpaket (Themen, Lehrblöcke, Quiz).

    Ohne `generator` wählt `hole_llm` den LLM-Anbieter (`llm_anbieter`/`llm_modell`,
    sonst Umgebung); ohne Anbieter läuft der deterministische Heuristik-Generator.
    """
    chunks = extraktion.chunks
    materialluecken = list(extraktion.materialluecken)

    # Themenkatalog: Studienbrief-Struktur + Vorlesungsinhalte, dann gewichten.
    themen = baue_themenkatalog([c for c in chunks if c.quelle == "studienbrief"])
    themen = ergaenze_aus_transkript(
        themen, [c for c in chunks if c.quelle in ("vorlesung", "folie")])
    treffer = finde_relevanz_marker(chunks)
    optional_chunks = [c for c in chunks if c.quelle in ("altklausur", "uebung")]
    gewichte_themen(themen, treffer, optional_chunks)

    zielformat = erkenne_zielformat(chunks)
    log.info("Generierung: %d Thema/Themen, Zielformat-Vorschlag '%s'",
             len(themen), zielformat.vorschlag)

    if generator is None:
        llm = hole_llm(llm_anbieter, llm_modell)
        generator = LLMGenerator(llm) if llm is not None else HeuristischerGenerator()
    log.info("Generator: %s", type(generator).__name__)
    zuordnung = ordne_chunks_zu(themen, chunks)
    start = time.perf_counter()
    ergebnis = generator.erzeuge(themen, zuordnung, zielformat.vorschlag)
    log.info("Generierung fertig: %d Lehrblock/-blöcke, %d Frage(n) in %.0f s",
             len(ergebnis.lehrbloecke), len(ergebnis.fragen), time.perf_counter() - start)
    materialluecken.extend(ergebnis.materialluecken)
    materialluecken.extend(verifiziere(ergebnis.fragen, ergebnis.lehrbloecke, chunks))

    manifest = Manifest(
        modul_id=modul_id, titel=titel,
        erzeugt_am=(jetzt or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        quellen=extraktion.quellen,
        optionalquellen_vorhanden=extraktion.optionalquellen_vorhanden,
        relevanz_unsicherheit="niedrig" if extraktion.optionalquellen_vorhanden else "hoch",
        zielformat=zielformat,
        materialluecken=materialluecken,
    )
    paket = Lernpaket(manifest=manifest, themen=themen,
                      lehrbloecke=ergebnis.lehrbloecke, fragen=ergebnis.fragen,
                      chunks=chunks)
    fehler = pruefe_vertrag(paket)
    if fehler:
        raise ValueError("Lernpaket verletzt den Datei-Vertrag:\n" + "\n".join(fehler))
    return paket


def erzeuge_lernpaket(
    modul_dir: Path,
    modul_id: Optional[str] = None,
    titel: Optional[str] = None,
    ocr: Optional[Ocr] = None,
    transkribierer: Optional[Transkribierer] = None,
    szenen_erkenner: Optional[SzenenErkenner] = None,
    folien_leser: Optional[FolienLeser] = None,
    generator: Optional[Generator] = None,
    parser: Optional[DokumentParser] = None,
    jetzt: Optional[datetime] = None,
    llm_anbieter: Optional[str] = None,
    llm_modell: Optional[str] = None,
) -> Lernpaket:
    """Beide Schritte in einem Durchlauf (Extraktion im Speicher, dann Generierung)."""
    modul_dir = Path(modul_dir)
    extraktion = extrahiere_material(
        modul_dir, ocr=ocr, transkribierer=transkribierer,
        szenen_erkenner=szenen_erkenner, folien_leser=folien_leser,
        parser=parser, jetzt=jetzt)
    return generiere_lernpaket(
        extraktion,
        modul_id=modul_id or modul_dir.name.lower().replace(" ", "-"),
        titel=titel or modul_dir.name,
        generator=generator, jetzt=jetzt,
        llm_anbieter=llm_anbieter, llm_modell=llm_modell)


def erzeuge_und_schreibe(modul_dir: Path, ziel: Path, **kwargs) -> Path:
    paket = erzeuge_lernpaket(modul_dir, **kwargs)
    return schreibe_lernpaket(paket, Path(ziel) / paket.manifest.modul_id)
