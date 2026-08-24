"""Formel-/Tabellen-/Code-Erfassung aus PDF-Text (Issue #28, ADR 0004).

Rückgrat laut ADR 0004 ist ein Dokument-Parser wie Marker (Formel→LaTeX,
Tabellen, alles nach Markdown). Marker ist ein optionaler Adapter; ohne ihn
läuft eine deterministische Heuristik, die Formelzeilen als LaTeX markiert,
tabellarische Zeilen zu Markdown-Tabellen macht und Codezeilen einzäunt.
Der Player rendert `$...$`/`$$...$$` mit KaTeX.
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
from pathlib import Path
from typing import Dict, List, Protocol, runtime_checkable

log = logging.getLogger("lernpaket")

# Surya (unter Marker) legt für jeden lokalen Inferenzserver eine Sentinel-Datei
# mit PID und Port ab. Das ist der einzige Weg, die Server gezielt wieder
# loszuwerden — siehe `MarkerParser.schliesse`.
_DIENST_VERZEICHNIS = Path("~/.cache/datalab/surya").expanduser()


def _dienst_sentinels() -> Dict[str, Path]:
    """Sentinel-Dateien laufender surya-Inferenzserver (Dateiname → Pfad)."""
    if not _DIENST_VERZEICHNIS.is_dir():
        return {}
    return {p.name: p for p in _DIENST_VERZEICHNIS.glob("*_server.json")}


class DokumentParser(Protocol):
    """Normalisiert den Rohtext einer Seite nach Markdown (Formeln als LaTeX)."""

    def nach_markdown(self, seiten_text: str) -> str: ...


@runtime_checkable
class SeitenParser(Protocol):
    """Parser, der ein ganzes PDF liest und Markdown je Seitennummer liefert.

    Marker arbeitet auf Datei- statt Zeilenebene: Layout, Matrizen und Formeln
    erschließen sich erst aus der gerenderten Seite, nicht aus dem Rohtext, den
    `lies_pdf` zieht. Die Pipeline fragt diese Fähigkeit optional ab und fällt
    je Seite auf `nach_markdown` zurück, wo sie fehlt.
    """

    def pdf_nach_seiten(self, pfad: Path) -> Dict[int, str]: ...


# Marker stellt jeder Seite '{<index>}' + 48 Bindestriche voran (paginate_output).
_SEITENMARKE_RE = re.compile(r"^\{(\d+)\}-{20,}\s*$", re.MULTILINE)

# Leere Sprunganker aus den PDF-Querverweisen — reines Rauschen für LLM und Anzeige.
_ANKER_RE = re.compile(r'<span\s+id="[^"]*"\s*></span>\s*')
# Hoch-/Tiefstellung, die Buchstaben umschließt: In den Studienbriefen setzt
# Marker gewöhnliche Variablen des Fließtexts hoch ("*<sup>f</sup>* ∶ *<sup>D</sup>*"
# für "f ∶ D") — die Markierung stammt aus der Zeichenposition im PDF und ist
# unzuverlässig, im selben Satz bleibt das echte Quadrat in "x 2" ungesetzt.
# Rein numerische Hochstellung bleibt darum stehen (echte Exponenten gehen nicht
# verloren), buchstabige wird ausgepackt.
_SUPSUB_BUCHSTABEN_RE = re.compile(r"<(su[pb])>(?=[^<>]*[^\W\d_])([^<>]*)</\1>")


# Ein Überstrich, den der Dokument-Parser nicht an seinen Operanden binden
# konnte: Er bleibt als alleinstehender (escapter) Unterstrich stehen. In
# Foliensätzen ist das die Negation — "R8a a + a = 1 \_" statt "a + ā = 1".
# Der Fehler ist damit erkennbar und wird als Materiallücke gemeldet, statt
# lautlos als falsche Formel weiterzulaufen (ADR 0003, ADR 0008).
_VERWAISTER_STRICH_RE = re.compile(r"(?<![\\\w])\\_(?![\w])|(?<!\S)_+(?!\S)")


def verwaiste_striche(text: str) -> int:
    """Anzahl der Überstriche ohne Operand — verlorene Negationen."""
    return len(_VERWAISTER_STRICH_RE.findall(text))


def raeume_marker_text_auf(text: str) -> str:
    """Entfernt Marker-Artefakte, die den Text unlesbar machen."""
    text = _ANKER_RE.sub("", text)
    return _SUPSUB_BUCHSTABEN_RE.sub(r"\2", text)


def spalte_marker_seiten(markdown: str) -> Dict[int, str]:
    """Paginiertes Marker-Markdown → {Seitennummer: Text}.

    Markers Seitenindex ist 0-basiert, Seitennummern im Lernpaket sind
    1-basiert (Beleg-Positionen "S. N") — daher +1.
    """
    treffer = list(_SEITENMARKE_RE.finditer(markdown))
    ergebnis: Dict[int, str] = {}
    for i, marke in enumerate(treffer):
        ende = treffer[i + 1].start() if i + 1 < len(treffer) else len(markdown)
        ergebnis[int(marke.group(1)) + 1] = raeume_marker_text_auf(
            markdown[marke.end():ende]).strip()
    return ergebnis


class MarkerParser:
    """Adapter für Marker (extra 'marker'), ADR-0004-Rückgrat der Erfassung.

    Die Modelle werden einmal je Instanz geladen (mehrere Sekunden) und über
    alle PDFs eines Laufs wiederverwendet.
    """

    def __init__(self) -> None:
        self._converter = None
        self._heuristik = HeuristikParser()
        self._fremde_dienste: set = set()

    def _converter_holen(self):  # pragma: no cover - schweres Modell
        if self._converter is None:
            # Vor dem ersten Start festhalten, welche Inferenzserver bereits
            # laufen: die gehören einem anderen Prozess, der sie mitten im
            # Betrieb nicht verlieren darf. `schliesse` fasst sie nicht an.
            self._fremde_dienste = set(_dienst_sentinels())
            try:
                from marker.converters.pdf import PdfConverter  # type: ignore
                from marker.models import create_model_dict  # type: ignore
                from marker.config.parser import ConfigParser  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "Marker ist nicht installiert "
                    "(pip install 'lernpaket-pipeline[marker]')."
                ) from exc
            konfiguration = ConfigParser({
                "paginate_output": True,      # Seitengrenzen für Beleg-Positionen
                "output_format": "markdown",
                "disable_image_extraction": True,  # Bilder rendert PyMuPdfRenderer
            })
            self._converter = PdfConverter(
                artifact_dict=create_model_dict(),
                config=konfiguration.generate_config_dict(),
                renderer=konfiguration.get_renderer(),
            )
        return self._converter

    def pdf_nach_seiten(self, pfad: Path) -> Dict[int, str]:  # pragma: no cover
        return spalte_marker_seiten(self._converter_holen()(str(pfad)).markdown)

    def nach_markdown(self, seiten_text: str) -> str:  # pragma: no cover
        # Für losen Text (Folien-OCR) kann Marker nichts tun — es braucht die
        # PDF-Seite. Ohne Delegation bliebe solcher Text gänzlich unnormalisiert.
        return self._heuristik.nach_markdown(seiten_text)

    def schliesse(self) -> None:
        """Beendet die Inferenzserver, die dieser Lauf gestartet hat.

        Marker startet bis zu drei lokale Server; der größte (llamacpp, die
        Formelerkennung) hält rund 2,7 GB. Von allein verschwinden sie zu spät
        oder gar nicht: den llamacpp-Server räumt surya erst per `atexit` ab,
        also nach der Transkription, die noch Stunden dauern kann — und
        `fast_layout`/`ocr_error` sind fest auf keep-alive gesetzt und
        überleben den Prozess sogar ganz. Nach der PDF-Phase wird keiner von
        ihnen mehr gebraucht.

        Fremde Server (liefen schon vor dem ersten Marker-Aufruf) bleiben
        unangetastet — sie können zu einem parallelen Lauf gehören.
        """
        for name, pfad in _dienst_sentinels().items():
            if name in self._fremde_dienste:
                continue
            try:
                daten = json.loads(pfad.read_text(encoding="utf-8"))
                pid = int(daten["pid"])
            except (OSError, ValueError, KeyError):
                continue  # Sentinel unlesbar oder schon weg
            try:
                os.kill(pid, signal.SIGTERM)
                log.info("Inferenzserver beendet: %s (pid %d)",
                         daten.get("backend", name), pid)
            except ProcessLookupError:
                pass  # war schon beendet — Sentinel trotzdem aufräumen
            except OSError as fehler:  # pragma: no cover - defensiv
                log.warning("Inferenzserver %s (pid %d) ließ sich nicht "
                            "beenden: %s", name, pid, fehler)
                continue
            try:
                pfad.unlink()
            except OSError:  # pragma: no cover - defensiv
                pass
        self._converter = None
        self._fremde_dienste = set()


# --- Deterministische Heuristik -------------------------------------------------

_MATH_ZEICHEN = re.compile(r"[=∑∏∫√≤≥≠±·×÷^]|\\frac|\\sum|O\(")
_MATH_STARK = re.compile(
    r"(^|\s)[A-Za-z]\s*\([A-Za-z0-9, ]*\)\s*=|=.*[+\-*/^].*|[∑∏∫√]|≤|≥|\\frac"
)
_CODE_HINWEIS = re.compile(
    r"^\s*(def |class |for |while |if |return |import |function |var |let |const |#include|public |private )"
)
_TABELLEN_TRENNER = re.compile(r"\S(\t+| {3,})\S")


def ist_formelzeile(zeile: str) -> bool:
    z = zeile.strip()
    if not z or len(z) > 120:
        return False
    if _CODE_HINWEIS.search(z):
        return False
    # Eine Formelzeile ist kurz, enthält starke Mathe-Muster und wenig Prosa.
    woerter = [w for w in re.split(r"\s+", z) if len(w) > 3 and w.isalpha()]
    return bool(_MATH_STARK.search(z)) and len(woerter) <= 3


def ist_codezeile(zeile: str) -> bool:
    return bool(_CODE_HINWEIS.search(zeile))


def ist_tabellenzeile(zeile: str) -> bool:
    return bool(_TABELLEN_TRENNER.search(zeile)) and len(zeile.strip()) > 0


def _zeile_zu_latex(zeile: str) -> str:
    """Best-effort-Normalisierung einer Textformel nach LaTeX."""
    z = zeile.strip()
    ersetzungen = {"≤": r"\le ", "≥": r"\ge ", "≠": r"\ne ", "·": r"\cdot ",
                   "×": r"\times ", "∑": r"\sum ", "∏": r"\prod ", "∫": r"\int ",
                   "√": r"\sqrt ", "±": r"\pm ", "→": r"\to ", "∞": r"\infty "}
    for roh, latex in ersetzungen.items():
        z = z.replace(roh, latex)
    return z


class HeuristikParser:
    """Deterministischer Fallback-Parser ohne ML-Abhängigkeiten."""

    def nach_markdown(self, seiten_text: str) -> str:
        zeilen = seiten_text.splitlines()
        ergebnis: List[str] = []
        i = 0
        while i < len(zeilen):
            zeile = zeilen[i]
            if ist_codezeile(zeile):
                block = [zeile]
                i += 1
                while i < len(zeilen) and (ist_codezeile(zeilen[i]) or zeilen[i].startswith((" ", "\t"))):
                    block.append(zeilen[i])
                    i += 1
                ergebnis.extend(["```", *block, "```"])
                continue
            if ist_formelzeile(zeile):
                ergebnis.append(f"$${_zeile_zu_latex(zeile)}$$")
                i += 1
                continue
            if ist_tabellenzeile(zeile) and i + 1 < len(zeilen) and ist_tabellenzeile(zeilen[i + 1]):
                block = []
                while i < len(zeilen) and ist_tabellenzeile(zeilen[i]):
                    zellen = [c.strip() for c in re.split(r"\t+| {3,}", zeilen[i].strip())]
                    block.append("| " + " | ".join(zellen) + " |")
                    i += 1
                if block:
                    spalten = block[0].count("|") - 1
                    block.insert(1, "|" + " --- |" * spalten)
                ergebnis.extend(block)
                continue
            ergebnis.append(zeile)
            i += 1
        return "\n".join(ergebnis)


def waehle_parser() -> DokumentParser:
    """Marker, falls installiert (ADR 0004 Default), sonst Heuristik."""
    try:  # pragma: no cover - abhängig von Umgebung
        import marker  # type: ignore # noqa: F401
        return MarkerParser()
    except ImportError:
        return HeuristikParser()
