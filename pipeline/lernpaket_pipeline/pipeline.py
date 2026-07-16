"""Orchestrierung der Aufbereitung: Modulverzeichnis → Lernpaket-Verzeichnis.

Pro Modul unabhängig aufrufbar (Issue #33, ADR 0001). Pflichtquellen
(Studienbrief-PDF, Vorlesungs-MP4) werden vorausgesetzt, Optionalquellen
(Altklausuren, Übungen) genutzt, wenn vorhanden — sonst graceful degradation
mit `relevanz_unsicherheit: hoch` (Issue #31).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .chunks import chunks_aus_folien, chunks_aus_seiten, chunks_aus_transkript
from .extraktion.audio import Transkribierer
from .extraktion.folien import FolienLeser, SzenenErkenner, extrahiere_folien
from .extraktion.formeln import DokumentParser, waehle_parser
from .extraktion.pdf import Ocr, Seite, lies_pdf
from .generierung import Generator, HeuristischerGenerator, LLMGenerator
from .llm import hole_llm
from .relevanz import finde_relevanz_marker, gewichte_themen
from .themen import baue_themenkatalog, ergaenze_aus_transkript, ordne_chunks_zu
from .verifikation import verifiziere
from .vertrag import (Chunk, Lernpaket, Manifest, Materialluecke, Quelle,
                      pruefe_vertrag, schreibe_lernpaket)
from .zielformat import erkenne_zielformat


@dataclass
class QuellenLage:
    studienbrief: Path
    vorlesungen: List[Path] = field(default_factory=list)
    altklausuren: List[Path] = field(default_factory=list)
    uebungen: List[Path] = field(default_factory=list)

    @property
    def optionalquellen_vorhanden(self) -> bool:
        return bool(self.altklausuren or self.uebungen)


def finde_quellen(modul_dir: Path) -> QuellenLage:
    """Erkennt die Materiallage eines Modulverzeichnisses per Konvention.

    - Studienbrief: `studienbrief*.pdf`, sonst das größte PDF auf oberster Ebene.
    - Vorlesungen: `*.mp4` (oberste Ebene oder `vorlesungen/`).
    - Optionalquellen: `altklausuren/*.pdf`, `uebungen/*.pdf` sowie Dateien
      `altklausur*.pdf` / `uebung*.pdf` auf oberster Ebene.
    """
    modul_dir = Path(modul_dir)
    pdfs = sorted(modul_dir.glob("*.pdf"))
    altklausuren = sorted(modul_dir.glob("altklausuren/*.pdf")) + [
        p for p in pdfs if p.name.lower().startswith("altklausur")]
    uebungen = sorted(modul_dir.glob("uebungen/*.pdf")) + [
        p for p in pdfs if p.name.lower().startswith(("uebung", "übung"))]
    kandidaten = [p for p in pdfs if p not in altklausuren and p not in uebungen]
    studienbrief = next(
        (p for p in kandidaten if p.name.lower().startswith("studienbrief")), None)
    if studienbrief is None:
        if not kandidaten:
            raise FileNotFoundError(
                f"Pflichtquelle fehlt: kein Studienbrief-PDF in {modul_dir}")
        studienbrief = max(kandidaten, key=lambda p: p.stat().st_size)
    vorlesungen = sorted(modul_dir.glob("*.mp4")) + sorted(modul_dir.glob("vorlesungen/*.mp4"))
    return QuellenLage(studienbrief=studienbrief, vorlesungen=vorlesungen,
                       altklausuren=altklausuren, uebungen=uebungen)


def _normalisiere_seiten(seiten: List[Seite], parser: DokumentParser) -> List[Seite]:
    return [Seite(nummer=s.nummer, text=parser.nach_markdown(s.text), ist_scan=s.ist_scan)
            for s in seiten]


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
) -> Lernpaket:
    """Führt die komplette Aufbereitung aus und gibt das Lernpaket zurück.

    Alle schweren Werkzeuge sind injizierbar (Tests: Fakes; PRD-Testentscheidung).
    Ohne `generator` wird das Remote-LLM genutzt, wenn ANTHROPIC_API_KEY gesetzt
    ist, sonst der deterministische Heuristik-Generator.
    """
    modul_dir = Path(modul_dir)
    quellen = finde_quellen(modul_dir)
    modul_id = modul_id or modul_dir.name.lower().replace(" ", "-")
    titel = titel or modul_dir.name
    parser = parser or waehle_parser()
    materialluecken: List[Materialluecke] = []

    # 1. Pflichtquelle Studienbrief (Textebene/Scan-Erkennung + OCR-Fallback).
    seiten = lies_pdf(quellen.studienbrief, ocr=ocr)
    scans_ohne_text = [s.nummer for s in seiten if s.ist_scan and not s.text.strip()]
    if scans_ohne_text:
        materialluecken.append(Materialluecke(
            thema_id="", art="schweigen",
            beschreibung=f"{len(scans_ohne_text)} Scan-Seite(n) ohne Textebene und ohne "
                         f"OCR-Ergebnis (z. B. S. {scans_ohne_text[0]}) — Inhalt fehlt im "
                         f"Lernpaket. OCR-Extras installieren und neu aufbereiten.",
        ))
    seiten = _normalisiere_seiten(seiten, parser)
    chunks: List[Chunk] = chunks_aus_seiten(seiten)

    # 2. Vorlesungen: Audio → Transkript, Folien → Standbilder → Extraktion.
    transkript_chunks: List[Chunk] = []
    for mp4 in quellen.vorlesungen:
        if transkribierer is not None:
            transkript = transkribierer.transkribiere(mp4)
            transkript_chunks.extend(chunks_aus_transkript(transkript, len(chunks) + len(transkript_chunks)))
        if szenen_erkenner is not None and folien_leser is not None:
            folien = extrahiere_folien(mp4, szenen_erkenner, folien_leser)
            folien_texte = [
                type(f)(nummer=f.nummer, zeit_sekunden=f.zeit_sekunden, bild=f.bild,
                        text=parser.nach_markdown(f.text)) for f in folien]
            transkript_chunks.extend(
                chunks_aus_folien(folien_texte, len(chunks) + len(transkript_chunks)))
    chunks.extend(transkript_chunks)

    # 3. Optionalquellen (falls vorhanden) als Relevanzsignal einlesen.
    optional_chunks: List[Chunk] = []
    for pfad, quelle in ([(p, "altklausur") for p in quellen.altklausuren]
                         + [(p, "uebung") for p in quellen.uebungen]):
        opt_seiten = _normalisiere_seiten(lies_pdf(pfad, ocr=ocr), parser)
        optional_chunks.extend(
            chunks_aus_seiten(opt_seiten, quelle=quelle,
                              start_zaehler=len(chunks) + len(optional_chunks)))
    chunks.extend(optional_chunks)

    # 4. Themenkatalog: Studienbrief-Struktur + Vorlesungsinhalte, dann gewichten.
    themen = baue_themenkatalog([c for c in chunks if c.quelle == "studienbrief"])
    themen = ergaenze_aus_transkript(themen, [c for c in chunks if c.quelle in ("vorlesung", "folie")])
    treffer = finde_relevanz_marker(chunks)
    gewichte_themen(themen, treffer, optional_chunks)

    # 5. Zielformat aus dem stärksten Relevanzsignal vorschlagen.
    zielformat = erkenne_zielformat(chunks)

    # 6. Generierung (Beleg-Vertrag) + 7. Verifikationsdurchlauf.
    if generator is None:
        llm = hole_llm()
        generator = LLMGenerator(llm) if llm is not None else HeuristischerGenerator()
    zuordnung = ordne_chunks_zu(themen, chunks)
    ergebnis = generator.erzeuge(themen, zuordnung, zielformat.vorschlag)
    materialluecken.extend(ergebnis.materialluecken)
    materialluecken.extend(verifiziere(ergebnis.fragen, ergebnis.lehrbloecke, chunks))

    manifest = Manifest(
        modul_id=modul_id, titel=titel,
        erzeugt_am=(jetzt or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        quellen=(
            [Quelle(art="studienbrief", datei=quellen.studienbrief.name)]
            + [Quelle(art="vorlesung", datei=p.name) for p in quellen.vorlesungen]
            + [Quelle(art="altklausur", datei=p.name) for p in quellen.altklausuren]
            + [Quelle(art="uebung", datei=p.name) for p in quellen.uebungen]),
        optionalquellen_vorhanden=quellen.optionalquellen_vorhanden,
        relevanz_unsicherheit="niedrig" if quellen.optionalquellen_vorhanden else "hoch",
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


def erzeuge_und_schreibe(modul_dir: Path, ziel: Path, **kwargs) -> Path:
    paket = erzeuge_lernpaket(modul_dir, **kwargs)
    return schreibe_lernpaket(paket, Path(ziel) / paket.manifest.modul_id)
