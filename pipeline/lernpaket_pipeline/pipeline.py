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
import os
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .chunks import chunks_aus_folien, chunks_aus_seiten, chunks_aus_transkript
from .extraktion.audio import Transkribierer, Transkript, TranskriptSegment
from .extraktion.folien import FolienLeser, SzenenErkenner, extrahiere_folien
from .extraktion.formeln import (DokumentParser, SeitenParser,
                                 verwaiste_striche, waehle_parser)
from .fortschritt import balken
from .extraktion.pdf import (FOLIEN, PROSA, DiagrammRenderer, Ocr,
                             PyMuPdfRenderer, Seite, erkenne_dokumentart,
                             finde_abbildungen, ist_verklebt, lies_pdf,
                             seiten_mit_bildern)
from .generierung import Generator, HeuristischerGenerator, LLMGenerator
from .llm import GecachterLLM, hole_llm
from .relevanz import finde_relevanz_marker, gewichte_themen
from .themen import (baue_themenkatalog, benenne_themen,
                     ergaenze_aus_transkript, ordne_chunks_zu)
from .verifikation import verifiziere
from .vertrag import (Abbildung, Beleg, Chunk, Lernpaket, Manifest,
                      Materialluecke, Quelle, pruefe_vertrag, schreibe_lernpaket)
from .zielformat import erkenne_zielformat

EXTRAKTIONS_ORDNER = "extraktion"
# Antwort-Cache des Generierungsschritts, neben Transkript- und Parser-Cache.
GENERIERUNGS_CACHE = "generierung"

log = logging.getLogger("lernpaket")


def _mb(pfad: Path) -> float:
    return pfad.stat().st_size / 1_048_576


@dataclass
class QuellenLage:
    """Die Materiallage eines Moduls — pro Kategorie eine Liste von Dateien.

    Auch der Studienbrief ist eine Liste: ein Modul darf seinen Stoff auf
    mehrere PDFs verteilen (z. B. ein Heft je Studienbrief-Kapitel), ohne dass
    die Pipeline etwas davon still unter den Tisch fallen lässt.
    """

    studienbriefe: List[Path] = field(default_factory=list)
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
    abbildungen: List[Abbildung] = field(default_factory=list)
    erzeugt_am: str = ""


VIDEO_ENDUNGEN = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi")


def _dateien_mit_endung(verzeichnis: Optional[Path], endungen) -> List[Path]:
    if verzeichnis is None or not verzeichnis.is_dir():
        return []
    return sorted(p for p in verzeichnis.iterdir()
                  if p.is_file() and p.suffix.lower() in endungen)


def _vergleichbar(name: str) -> str:
    """Ordnername in Vergleichsform: klein und Unicode-normalisiert (NFC).

    macOS legt Umlaute im Dateisystem zerlegt ab ("u" + Diakritikum, NFD),
    Python-Literale im Quelltext sind zusammengesetzt (NFC). Ohne diese
    Normalisierung wird ein Ordner `übungen/` schlicht nicht gefunden.
    """
    return unicodedata.normalize("NFC", name).lower()


def _unterordner(modul_dir: Path, *namen: str) -> Optional[Path]:
    """Findet einen Unterordner unabhängig von Groß-/Kleinschreibung und Unicode-Form."""
    gesucht = {_vergleichbar(n) for n in namen}
    for eintrag in sorted(modul_dir.iterdir()):
        if eintrag.is_dir() and _vergleichbar(eintrag.name) in gesucht:
            return eintrag
    return None


# Ein Ordner je Kategorie ist das primäre Schema (Groß-/Kleinschreibung egal).
# Es überlebt Umbenennungen der PDFs und eine andere Aufteilung des Stoffs auf
# mehrere Dateien; die Namensregeln darunter bleiben nur als Rückfallebene für
# flach abgelegte Module bestehen.
ORDNER_STUDIENBRIEF = ("studienbrief", "studienbriefe")
ORDNER_VORLESUNG = ("vorlesungen", "vorlesung")
ORDNER_ALTKLAUSUR = ("altklausuren", "altklausur")
ORDNER_UEBUNG = ("uebungen", "übungen", "uebung", "übung")


def finde_quellen(modul_dir: Path) -> QuellenLage:
    """Erkennt die Materiallage eines Modulverzeichnisses per Konvention.

    Primär zählt der Kategorie-Ordner: `studienbrief/`, `vorlesungen/`,
    `altklausuren/`, `uebungen/` (bzw. `übungen/`). Alle passenden Dateien
    darin gehören zur Kategorie — auch mehrere Studienbrief-PDFs.

    Fällt ein Ordner weg, greifen die alten Namensregeln auf oberster Ebene:
    `studienbrief*.pdf` (sonst das größte übrige PDF), `altklausur*.pdf`,
    `uebung*.pdf` und Videodateien.
    """
    modul_dir = Path(modul_dir)
    pdfs = sorted(modul_dir.glob("*.pdf"))
    altklausuren = _dateien_mit_endung(
        _unterordner(modul_dir, *ORDNER_ALTKLAUSUR), (".pdf",)) + [
        p for p in pdfs if _vergleichbar(p.name).startswith("altklausur")]
    uebungen = _dateien_mit_endung(
        _unterordner(modul_dir, *ORDNER_UEBUNG), (".pdf",)) + [
        p for p in pdfs if _vergleichbar(p.name).startswith(("uebung", "übung"))]
    studienbriefe = _dateien_mit_endung(
        _unterordner(modul_dir, *ORDNER_STUDIENBRIEF), (".pdf",))
    if not studienbriefe:
        kandidaten = [p for p in pdfs if p not in altklausuren and p not in uebungen]
        benannt = [p for p in kandidaten if _vergleichbar(p.name).startswith("studienbrief")]
        if benannt:
            studienbriefe = benannt
        elif kandidaten:
            studienbriefe = [max(kandidaten, key=lambda p: p.stat().st_size)]
        else:
            raise FileNotFoundError(
                f"Pflichtquelle fehlt: kein Studienbrief-PDF in {modul_dir} "
                f"(erwartet: Ordner {ORDNER_STUDIENBRIEF[0]}/ oder ein PDF auf "
                "oberster Ebene)")
    vorlesungen = (_dateien_mit_endung(modul_dir, VIDEO_ENDUNGEN)
                   + _dateien_mit_endung(_unterordner(modul_dir, *ORDNER_VORLESUNG),
                                         VIDEO_ENDUNGEN))
    return QuellenLage(studienbriefe=studienbriefe, vorlesungen=vorlesungen,
                       altklausuren=altklausuren, uebungen=uebungen)


class ModulBelegt(RuntimeError):
    """Ein anderer Prozess bereitet dieses Modul gerade auf."""


class FoliensatzOhneDokumentParser(RuntimeError):
    """Foliensatz erkannt, aber kein Dokument-Parser verfügbar (ADR 0008).

    Bewusst ein Abbruch statt der sonst üblichen Degradation: Ein Lernpaket mit
    lautlos falschen Formeln kostet Lernzeit und schadet in der Klausur — es ist
    schlechter als gar keines.
    """


@contextmanager
def modulsperre(modul_dir: Path):
    """Lässt nur einen Aufbereitungslauf je Modul zu.

    Zwei gleichzeitige Läufe sind immer ein Versehen: sie überschreiben
    einander das Ergebnis, teilen sich die CPU und schreiben in denselben
    Transkript-Cache. Die Sperre trägt die PID ein; ist der eingetragene
    Prozess nicht mehr am Leben (Absturz, Stromausfall), wird sie als verwaist
    übernommen statt das Modul dauerhaft zu blockieren.
    """
    sperre = Path(modul_dir) / EXTRAKTIONS_ORDNER / ".lock"
    sperre.parent.mkdir(parents=True, exist_ok=True)
    inhalt = json.dumps({"pid": os.getpid(),
                         "seit": datetime.now(timezone.utc).isoformat()})
    for versuch in (1, 2):
        try:
            # O_EXCL: atomar — zwei gleichzeitig startende Läufe können nicht
            # beide gewinnen.
            fd = os.open(sperre, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, inhalt.encode("utf-8"))
            os.close(fd)
            break
        except FileExistsError:
            fremde_pid = None
            try:
                fremde_pid = int(json.loads(sperre.read_text(encoding="utf-8"))["pid"])
            except (OSError, ValueError, KeyError, TypeError):
                pass  # unlesbar → wie verwaist behandeln
            if versuch == 2 or (fremde_pid is not None and _lebt(fremde_pid)):
                raise ModulBelegt(
                    f"Modul '{Path(modul_dir).name}' wird bereits aufbereitet"
                    + (f" (PID {fremde_pid})" if fremde_pid else "")
                    + f". Läuft dort nichts mehr, {sperre} löschen.")
            log.warning("Verwaiste Sperre von PID %s entfernt — der Prozess "
                        "lebt nicht mehr.", fremde_pid)
            sperre.unlink(missing_ok=True)
    try:
        yield
    finally:
        try:  # nur die eigene Sperre lösen
            if json.loads(sperre.read_text(encoding="utf-8"))["pid"] == os.getpid():
                sperre.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError, TypeError):  # pragma: no cover
            pass


def _lebt(pid: int) -> bool:
    """True, wenn ein Prozess mit dieser PID existiert."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - fremder Nutzer, lebt also
        return True
    return True


def _seiten_markdown_mit_cache(parser: DokumentParser, pdf: Path,
                               cache_dir: Optional[Path]) -> Dict[int, str]:
    """Marker-Ergebnis je PDF, mit Datei-Cache (Schlüssel: Name + Größe).

    Ohne Cache kostet jeder erneute Lauf das vollständige Neu-Parsen des
    Studienbriefs — bei 239 Seiten rund 19 Minuten, obwohl sich am PDF nichts
    geändert hat. Das trifft vor allem den semesterbegleitenden Ablauf, bei dem
    nur neue Vorlesungen dazukommen.
    """
    cache_datei = cache_dir / f"{pdf.name}.json" if cache_dir else None
    groesse = pdf.stat().st_size
    kennung = type(parser).__name__
    if cache_datei and cache_datei.exists():
        try:
            daten = json.loads(cache_datei.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            daten = {}
        # Parser-Name mit im Schlüssel: nach einem Wechsel des Backends wäre
        # der alte Text sonst stillschweigend weiterverwendet worden.
        if daten.get("groesse") == groesse and daten.get("parser") == kennung:
            seiten = {int(n): t for n, t in daten.get("seiten", {}).items()}
            log.info("Dokument-Parser aus Cache: %s (%d Seiten)",
                     pdf.name, len(seiten))
            return seiten
    start = time.perf_counter()
    je_seite = parser.pdf_nach_seiten(pdf)  # type: ignore[attr-defined]
    log.info("Dokument-Parser: %d Seite(n) aus %s in %.0f s",
             len(je_seite), pdf.name, time.perf_counter() - start)
    if cache_datei:
        cache_datei.parent.mkdir(parents=True, exist_ok=True)
        cache_datei.write_text(json.dumps(
            {"datei": pdf.name, "groesse": groesse, "parser": kennung,
             "seiten": {str(n): t for n, t in je_seite.items()}},
            ensure_ascii=False), encoding="utf-8")
    return je_seite


def _folien_titel(seite: Seite) -> str:
    """Kopfzeile einer Folie als Abbildungs-Beschriftung (ADR 0008).

    Folien haben keine Bildunterschrift; ihre erste Zeile benennt die Folie und
    ist im Player das einzige Label, das die Abbildung unterscheidbar macht.
    Die Seiten sind hier bereits normalisiert, tragen also Markdown-Auszeichnung
    des Dokument-Parsers ("### Regeln für ein Element:") — die gehört nicht ins
    Label.
    """
    for zeile in (z.strip() for z in seite.text.split("\n")):
        zeile = zeile.lstrip("#*_ ").rstrip("*_ ")
        if len(zeile) >= 3 and not zeile.rstrip(".").isdigit():
            return zeile[:80]
    return f"Folie {seite.nummer}"


def _normalisiere_seiten(seiten: List[Seite], parser: DokumentParser,
                         pdf: Optional[Path] = None,
                         cache_dir: Optional[Path] = None) -> List[Seite]:
    """Seitentexte nach Markdown normalisieren (Formeln als LaTeX).

    Kann der Parser ganze PDFs (Marker), liefert er den fachlich weit besseren
    Text — er sieht die gerenderte Seite und rettet damit Matrizen und Brüche,
    die im Rohtext spaltenweise zerfallen. Seiten, für die er nichts liefert
    (und der Fehlerfall), fallen auf die zeilenweise Heuristik zurück.
    """
    je_seite: Dict[int, str] = {}
    if pdf is not None and isinstance(parser, SeitenParser):
        try:
            je_seite = _seiten_markdown_mit_cache(parser, pdf, cache_dir)
        except Exception as fehler:  # pragma: no cover - defensiv
            log.warning("Dokument-Parser fehlgeschlagen für %s (%s) — "
                        "Rückfall auf Heuristik.", pdf.name, fehler)
    return [Seite(nummer=s.nummer,
                  text=je_seite.get(s.nummer) or parser.nach_markdown(s.text),
                  ist_scan=s.ist_scan)
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
    diagramm_renderer: Optional[DiagrammRenderer] = None,
    mit_diagrammen: bool = True,
    dokumentart: Optional[str] = None,
) -> Extraktion:
    """Schritt 1: Materialien → Chunks + Materiallücken. Läuft ohne LLM.

    Alle schweren Werkzeuge sind injizierbar (Tests: Fakes; PRD-Testentscheidung).
    Gecacht werden ASR-Transkripte (`<modul>/extraktion/transkripte/`) und das
    Parser-Ergebnis je PDF (`<modul>/extraktion/dokumente/`) — ein erneuter Lauf
    wertet nur neu hinzugekommenes Material aus. Solange er läuft, ist das Modul
    per Sperre gegen einen zweiten Lauf geschützt (`ModulBelegt`).
    """
    modul_dir = Path(modul_dir)
    with modulsperre(modul_dir):
        return _extrahiere_material(
            modul_dir, ocr=ocr, transkribierer=transkribierer,
            szenen_erkenner=szenen_erkenner, folien_leser=folien_leser,
            parser=parser, jetzt=jetzt, diagramm_renderer=diagramm_renderer,
            mit_diagrammen=mit_diagrammen, dokumentart=dokumentart)


def _extrahiere_material(
    modul_dir: Path,
    ocr: Optional[Ocr] = None,
    transkribierer: Optional[Transkribierer] = None,
    szenen_erkenner: Optional[SzenenErkenner] = None,
    folien_leser: Optional[FolienLeser] = None,
    parser: Optional[DokumentParser] = None,
    jetzt: Optional[datetime] = None,
    diagramm_renderer: Optional[DiagrammRenderer] = None,
    mit_diagrammen: bool = True,
    dokumentart: Optional[str] = None,
) -> Extraktion:
    """Der eigentliche Extraktionslauf, innerhalb der Modulsperre."""
    quellen = finde_quellen(modul_dir)
    parser = parser or waehle_parser()
    materialluecken: List[Materialluecke] = []
    log.info("Extraktion: Modul '%s'", modul_dir.name)
    log.info("Quellen: %d Studienbrief-PDF(s) · %d Vorlesung(en) · %d Altklausur(en) "
             "· %d Übung(en)", len(quellen.studienbriefe), len(quellen.vorlesungen),
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
    # Mehrere Studienbrief-PDFs werden nacheinander gelesen; ihre Chunks und
    # Abbildungen tragen dann den Dateinamen in Position bzw. ID, damit Belege
    # eindeutig bleiben.
    chunks: List[Chunk] = []
    abbildungen: List[Abbildung] = []
    dokumentarten: Dict[str, str] = {}
    mehrteilig = len(quellen.studienbriefe) > 1
    for index, studienbrief in enumerate(quellen.studienbriefe, start=1):
        label = studienbrief.stem if mehrteilig else ""
        # Seitenangaben in Meldungen: mit Datei, sobald es mehrere gibt.
        def _pos(nummer: int) -> str:
            return f"{label}, S. {nummer}" if label else f"S. {nummer}"

        log.info("Lese Studienbrief-PDF %s%s …", studienbrief.name,
                 " (mit OCR)" if ocr is not None else "")
        seiten = lies_pdf(studienbrief, ocr=ocr)
        log.info("Studienbrief %s: %d Seite(n) gelesen", studienbrief.name, len(seiten))

        # Dokumentart bestimmen (ADR 0008) — sie steuert Themenableitung und
        # Abbildungserfassung und landet zur Nachprüfbarkeit im Manifest.
        art = dokumentart or erkenne_dokumentart(studienbrief, seiten)
        dokumentarten[studienbrief.name] = art
        log.info("Dokumentart %s: %s", studienbrief.name, art)
        if art == FOLIEN and not isinstance(parser, SeitenParser):
            raise FoliensatzOhneDokumentParser(
                f"{studienbrief.name} ist ein Foliensatz, aber es steht kein "
                "Dokument-Parser bereit (Extra 'marker'). Folien setzen die "
                "Negation als Überstrich, den die PDF-Textebene nicht kennt — "
                "ohne Parser wären die Formeln im Lernpaket nicht bloß dünn, "
                "sondern lautlos falsch (ADR 0008). Abhilfe: "
                "pip install 'lernpaket-pipeline[marker]' — oder, wenn die "
                "Erkennung danebenliegt, --dokumentart prosa.")
        scans_ohne_text = [s.nummer for s in seiten if s.ist_scan and not s.text.strip()]
        if scans_ohne_text:
            if ocr is None:
                hinweis = ("Inhalt fehlt im Lernpaket. OCR-Extras installieren "
                           "und neu aufbereiten.")
            else:
                hinweis = ("trotz OCR kein Text erkannt — vermutlich Leerseiten "
                           "(dann fehlt nichts) oder unlesbare Scans.")
            materialluecken.append(Materialluecke(
                thema_id="", art="schweigen",
                beschreibung=f"{len(scans_ohne_text)} Scan-Seite(n) ohne Textebene und "
                             f"ohne OCR-Ergebnis (z. B. {_pos(scans_ohne_text[0])}) "
                             f"— {hinweis}",
            ))
        verklebte = [s.nummer for s in seiten if not s.ist_scan and ist_verklebt(s.text)]
        if verklebte:
            materialluecken.append(Materialluecke(
                thema_id="", art="schweigen",
                beschreibung=f"{len(verklebte)} Seite(n) mit verklebtem Text ohne "
                             f"Leerzeichen (z. B. {_pos(verklebte[0])}) — weder "
                             "Zweitextraktion (pdfminer) noch OCR konnten die "
                             "Wortgrenzen rekonstruieren (meist Diagramm-"
                             "Beschriftungen); diese Inhalte sind nur eingeschränkt "
                             "nutzbar.",
            ))
        # Diagramme werden als Bilder erfasst (s. u.); nur Rasterbild-Seiten ohne
        # Bildunterschrift bleiben unerfasst und werden als Materiallücke vermerkt.
        # Bei Foliensätzen entfällt das: dort wird ohnehin jede Folie gerendert.
        beschriftete = {n for n, _ in finde_abbildungen(seiten)}
        scan_nummern = {s.nummer for s in seiten if s.ist_scan}
        ungefasste_bilder = [] if art == FOLIEN else [
            n for n in seiten_mit_bildern(studienbrief)
            if n not in scan_nummern and n not in beschriftete]
        if ungefasste_bilder:
            materialluecken.append(Materialluecke(
                thema_id="", art="schweigen",
                beschreibung=f"{len(ungefasste_bilder)} Seite(n) mit Rasterbild ohne "
                             f"Bildunterschrift (z. B. {_pos(ungefasste_bilder[0])}) "
                             "— nicht als Abbildung erfasst.",
            ))
        seiten = _normalisiere_seiten(
            seiten, parser, pdf=studienbrief,
            cache_dir=modul_dir / EXTRAKTIONS_ORDNER / "dokumente")

        # Überstriche, die der Parser nicht an ihren Operanden binden konnte:
        # in Foliensätzen die Negation. Gemeldet statt still falsch gerechnet.
        striche = [(s.nummer, verwaiste_striche(s.text)) for s in seiten]
        betroffen = [(n, anzahl) for n, anzahl in striche if anzahl]
        if betroffen:
            materialluecken.append(Materialluecke(
                thema_id="", art="widerspruch",
                beschreibung=(
                    f"{sum(a for _, a in betroffen)} verwaiste(r) Überstrich(e) auf "
                    f"{len(betroffen)} Seite(n) (z. B. {_pos(betroffen[0][0])}) — "
                    "ein Negationsstrich ließ sich seinem Operanden nicht zuordnen. "
                    "Die betroffenen Formeln können ohne Negation dastehen und "
                    "damit das Gegenteil behaupten; im Original nachsehen.")))
        sb_chunks = chunks_aus_seiten(seiten, start_zaehler=len(chunks), dokument=label)
        chunks.extend(sb_chunks)

        # Diagramme: beschriftete Seiten (Bildunterschrift) als PNG rendern und mit
        # Beleg auf den Seiten-Chunk versehen (Thema-Zuordnung im Generierungsschritt).
        # Foliensätze tragen keine Bildunterschriften — ihre Diagramme (KV-Dia-
        # gramme, Schaltnetze, Automatengraphen) wären sonst unsichtbar, obwohl
        # sie den Kern der Folie ausmachen. Dort ist jede Folie eine Abbildung.
        if not mit_diagrammen:
            abbildung_seiten = []
        elif art == FOLIEN:
            abbildung_seiten = [(s.nummer, _folien_titel(s)) for s in seiten]
        else:
            abbildung_seiten = finde_abbildungen(seiten)
        if not abbildung_seiten:
            continue
        renderer = diagramm_renderer or PyMuPdfRenderer()
        chunk_je_seite = {c.position: c for c in sb_chunks}
        log.info("Rendere %d Abbildung(en) aus %s …",
                 len(abbildung_seiten), studienbrief.name)
        bar = balken(total=len(abbildung_seiten), desc="Abbildungen", unit="Seite")
        for nummer, titel in abbildung_seiten:
            chunk = chunk_je_seite.get(_pos(nummer))
            belege = [Beleg(quelle="studienbrief", position=_pos(nummer),
                            chunk_id=chunk.id if chunk else "")]
            try:
                bild = renderer.rendere(studienbrief, nummer)
            except Exception as fehler:  # pragma: no cover - defensiv
                log.warning("Abbildung %s konnte nicht gerendert werden: %s",
                            _pos(nummer), fehler)
                bar.update(1)
                continue
            abb_id = (f"abb-{index:02d}-{nummer:04d}" if mehrteilig
                      else f"abb-{nummer:04d}")
            abbildungen.append(Abbildung(
                id=abb_id, thema_id="", datei=f"bilder/{abb_id}.png",
                titel=titel, belege=belege, bild=bild))
            bar.update(1)
        bar.close()

    # PDF-Phase vorbei: die Inferenzserver des Dokument-Parsers werden nicht
    # mehr gebraucht. Sie jetzt zu beenden statt am Prozessende gibt mehrere
    # Gigabyte für die Transkription frei, die gleich Stunden läuft.
    schliessen = getattr(parser, "schliesse", None)
    if callable(schliessen):
        try:
            schliessen()
        except Exception as fehler:  # pragma: no cover - defensiv
            log.warning("Dokument-Parser ließ sich nicht schließen: %s", fehler)

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
                chunks_aus_folien(folien_texte, len(chunks) + len(transkript_chunks),
                                  dokument=video.name))
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
        # Mehrere Dateien je Kategorie: Dateiname in die Position, sonst zeigen
        # alle Belege mehrdeutig auf "S. 1".
        anzahl_der_art = sum(1 for _, q in optionalquellen if q == quelle)
        optional_chunks.extend(
            chunks_aus_seiten(opt_seiten, quelle=quelle,
                              start_zaehler=len(chunks) + len(optional_chunks),
                              dokument=pfad.stem if anzahl_der_art > 1 else ""))
    chunks.extend(optional_chunks)
    log.info("Extraktion fertig: %d Chunks, %d Materiallücke(n)",
             len(chunks), len(materialluecken))

    return Extraktion(
        quellen=(
            [Quelle(art="studienbrief", datei=p.name,
                    dokumentart=dokumentarten.get(p.name, PROSA))
             for p in quellen.studienbriefe]
            + [Quelle(art="vorlesung", datei=p.name) for p in quellen.vorlesungen]
            + [Quelle(art="altklausur", datei=p.name) for p in quellen.altklausuren]
            + [Quelle(art="uebung", datei=p.name) for p in quellen.uebungen]),
        optionalquellen_vorhanden=quellen.optionalquellen_vorhanden,
        chunks=chunks,
        materialluecken=materialluecken,
        abbildungen=abbildungen,
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
        "abbildungen": [{"id": a.id, "datei": a.datei, "titel": a.titel,
                         "belege": [asdict(b) for b in a.belege]}
                        for a in extraktion.abbildungen],
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (ziel / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in extraktion.chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False, sort_keys=True) + "\n")
    if extraktion.abbildungen:
        (ziel / "bilder").mkdir(exist_ok=True)
        for abb in extraktion.abbildungen:
            if abb.bild:
                (ziel / abb.datei).write_bytes(abb.bild)
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
    abbildungen = []
    for a in kopf.get("abbildungen", []):
        bild_pfad = ziel / a["datei"]
        abbildungen.append(Abbildung(
            id=a["id"], thema_id="", datei=a["datei"], titel=a.get("titel", ""),
            belege=[Beleg(**b) for b in a.get("belege", [])],
            bild=bild_pfad.read_bytes() if bild_pfad.exists() else b""))
    return Extraktion(
        quellen=[Quelle(**q) for q in kopf.get("quellen", [])],
        optionalquellen_vorhanden=kopf.get("optionalquellen_vorhanden", False),
        chunks=chunks,
        materialluecken=[Materialluecke(**m) for m in kopf.get("materialluecken", [])],
        abbildungen=abbildungen,
        erzeugt_am=kopf.get("erzeugt_am", ""),
    )


def _folien_dokumente(extraktion: Extraktion) -> "set[str]":
    """Dokument-Kennungen der Foliensätze, wie sie in den Chunk-Positionen stehen.

    `chunks_aus_seiten` stellt der Position nur bei mehreren Studienbrief-PDFs
    den Dateinamen voran; bei einer einzigen Datei lautet die Kennung "". Diese
    Umrechnung muss hier stimmen, sonst findet der Themenkatalog die Folien
    nicht wieder.
    """
    briefe = [q for q in extraktion.quellen if q.art == "studienbrief"]
    mehrteilig = len(briefe) > 1
    return {Path(q.datei).stem if mehrteilig else ""
            for q in briefe if q.dokumentart == FOLIEN}


def generiere_lernpaket(
    extraktion: Extraktion,
    modul_id: str,
    titel: str,
    generator: Optional[Generator] = None,
    jetzt: Optional[datetime] = None,
    llm_anbieter: Optional[str] = None,
    llm_modell: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> Lernpaket:
    """Schritt 2: Extraktionsergebnis → Lernpaket (Themen, Lehrblöcke, Quiz).

    Ohne `generator` wählt `hole_llm` den LLM-Anbieter (`llm_anbieter`/`llm_modell`,
    sonst Umgebung); ohne Anbieter läuft der deterministische Heuristik-Generator.
    """
    chunks = extraktion.chunks
    materialluecken = list(extraktion.materialluecken)

    # Themenkatalog: Studienbrief-Struktur + Vorlesungsinhalte, dann gewichten.
    # Foliensätze gliedern sich anders als Prosa (ADR 0008); welche Datei welche
    # Art hat, steht im Extraktionsergebnis und überlebt so den Schrittwechsel.
    folien_dokumente = _folien_dokumente(extraktion)
    if folien_dokumente:
        log.info("Foliensätze im Studienbrief: %d von %d Datei(en)",
                 len(folien_dokumente),
                 sum(1 for q in extraktion.quellen if q.art == "studienbrief"))
    themen = baue_themenkatalog([c for c in chunks if c.quelle == "studienbrief"],
                                folien_dokumente=folien_dokumente)
    themen = ergaenze_aus_transkript(
        themen, [c for c in chunks if c.quelle in ("vorlesung", "folie")])
    treffer = finde_relevanz_marker(chunks)
    optional_chunks = [c for c in chunks if c.quelle in ("altklausur", "uebung")]
    gewichte_themen(themen, treffer, optional_chunks)

    zielformat = erkenne_zielformat(chunks)
    log.info("Generierung: %d Thema/Themen, Zielformat-Vorschlag '%s'",
             len(themen), zielformat.vorschlag)

    llm = None
    if generator is None:
        llm = hole_llm(llm_anbieter, llm_modell)
        if llm is not None:
            # Antwort-Cache: Ein abgebrochener Lauf (Anbieter weg) soll beim
            # zweiten Anlauf nur die noch fehlenden Aufrufe kosten.
            llm = GecachterLLM(llm, cache_dir)
            generator = LLMGenerator(llm)
        else:
            generator = HeuristischerGenerator()
    log.info("Generator: %s", type(generator).__name__)
    zuordnung = ordne_chunks_zu(themen, chunks)
    # Foliensatz-Titel stammen aus der Folien-Kopfzeile und tragen bei einem
    # Teil der Folien Tabellen- oder Formelreste statt eines Namens (ADR 0008).
    # Der Prosa-Pfad bleibt unangetastet: Dort sind die Titel echte Kapitel-
    # überschriften, die eine Umbenennung nur verschlechtern könnte.
    if folien_dokumente and llm is not None:
        themen = benenne_themen(themen, zuordnung, llm)
    # Abbildungen dem Thema ihres Beleg-Chunks zuordnen (leer, wenn ohne Treffer).
    thema_je_chunk = {c.id: tid for tid, cs in zuordnung.items() for c in cs}
    abbildungen = [
        Abbildung(id=a.id, datei=a.datei, titel=a.titel, belege=a.belege, bild=a.bild,
                  thema_id=next((thema_je_chunk.get(b.chunk_id, "") for b in a.belege
                                 if thema_je_chunk.get(b.chunk_id)), ""))
        for a in extraktion.abbildungen]
    start = time.perf_counter()
    ergebnis = generator.erzeuge(themen, zuordnung, zielformat.vorschlag)
    log.info("Generierung fertig: %d Lehrblock/-blöcke, %d Frage(n) in %.0f s",
             len(ergebnis.lehrbloecke), len(ergebnis.fragen), time.perf_counter() - start)
    if isinstance(llm, GecachterLLM) and (llm.treffer or llm.aufrufe):
        log.info("LLM-Aufrufe: %d neu, %d aus dem Cache", llm.aufrufe, llm.treffer)
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
                      chunks=chunks, abbildungen=abbildungen)
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
        llm_anbieter=llm_anbieter, llm_modell=llm_modell,
        cache_dir=modul_dir / EXTRAKTIONS_ORDNER / GENERIERUNGS_CACHE)


def erzeuge_und_schreibe(modul_dir: Path, ziel: Path, **kwargs) -> Path:
    paket = erzeuge_lernpaket(modul_dir, **kwargs)
    return schreibe_lernpaket(paket, Path(ziel) / paket.manifest.modul_id)
