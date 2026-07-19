"""Gemeinsame Fixtures: Beispielmodul mit Studienbrief, Fake-Adapter für ASR/Folien/OCR.

Die Tests prüfen Verträge an der Datei-Grenze (PRD-Testentscheidung); schwere
Werkzeuge (Whisper, PySceneDetect, Tesseract, LLM) werden durch Fakes ersetzt.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from lernpaket_pipeline.extraktion.audio import Transkript, TranskriptSegment

from .pdf_helfer import schreibe_pdf

STUDIENBRIEF_SEITEN: List[List[str]] = [
    [
        "1 Grundlagen der Algorithmik",
        "Dieses Kapitel legt die Begriffe fest.",
        "",
        "1.1 Komplexitaet",
        "Die Komplexitaet ist ein Mass fuer den Aufwand eines Algorithmus",
        "in Abhaengigkeit der Eingabegroesse.",
        "Der Beispielstapel enthaelt genau 42 Elemente.",
    ],
    [
        "1.2 Landau-Notation",
        "Die Landau-Notation bezeichnet das asymptotische Wachstum von Funktionen.",
        "Man schreibt O(n) fuer lineares Wachstum.",
        "T(n) = 2T(n/2) + n",
    ],
    [
        "2 Sortierverfahren",
        "Ein Sortierverfahren ist ein Algorithmus, der Elemente in eine Ordnung bringt.",
        "",
        "2.1 Quicksort",
        "Quicksort ist ein rekursives Sortierverfahren nach dem Teile-und-Herrsche-Prinzip.",
        "Satz: Quicksort sortiert im schlechtesten Fall in quadratischer Zeit.",
        "Der Beweis folgt aus der Rekursionsgleichung der Partitionierung.",
    ],
    [
        "2.2 Mergesort",
        "Mergesort ist ein stabiles Sortierverfahren, das Teillisten mischt.",
        "Das Mischen zweier sortierter Listen ist in linearer Zeit moeglich.",
    ],
]

TRANSKRIPT_SAETZE = (
    "Willkommen zur Vorlesung ueber Algorithmen. "
    "Die Landau-Notation ist klausurrelevant, das müssen Sie können. "
    "Berechnen Sie zur Uebung die Laufzeit von Quicksort. "
    "Hashtabellen speichern Werte unter Schluesseln. "
    "Hashtabellen erlauben Zugriff in konstanter Zeit. "
    "Hashtabellen kommen in vielen Anwendungen vor."
)


@pytest.fixture
def modul_dir(tmp_path: Path) -> Path:
    """Modulverzeichnis mit Studienbrief (Pflichtquelle) — ohne Optionalquellen."""
    modul = tmp_path / "beispielmodul"
    modul.mkdir()
    schreibe_pdf(modul / "studienbrief.pdf", STUDIENBRIEF_SEITEN)
    return modul


@pytest.fixture
def modul_dir_mit_optionalquellen(modul_dir: Path) -> Path:
    (modul_dir / "altklausuren").mkdir()
    schreibe_pdf(modul_dir / "altklausuren" / "klausur-2025.pdf", [[
        "Altklausur Sommersemester",
        "Aufgabe 1: Kreuzen Sie an: Welche der folgenden Aussagen zu Quicksort",
        "trifft zu? a) stabil b) rekursiv c) linear d) konstant",
        "Aufgabe 2: Kreuzen Sie an: Richtig oder falsch: Mergesort ist stabil.",
    ]])
    return modul_dir


class FakeTranskribierer:
    """Liefert ein festes Transkript mit Zeitstempeln statt echter ASR."""

    def __init__(self, text: str = TRANSKRIPT_SAETZE):
        self.saetze = [s.strip() + "." for s in text.split(". ") if s.strip()]

    def transkribiere(self, mp4: Path) -> Transkript:
        segmente = [
            TranskriptSegment(start=20.0 * i, ende=20.0 * i + 18.0, text=satz)
            for i, satz in enumerate(self.saetze)
        ]
        return Transkript(datei=Path(mp4).name, segmente=segmente)


class FakeSzenenErkenner:
    """Zwei eindeutige Folien, eine davon doppelt (Duplikat muss verworfen werden)."""

    def __init__(self, szenen=None):
        self.szenen = szenen or [
            (10.0, b"FOLIE-EINS"),
            (70.0, b"FOLIE-ZWEI"),
            (130.0, b"FOLIE-EINS"),  # Duplikat
        ]

    def erkenne(self, mp4: Path):
        return list(self.szenen)


class FakeFolienLeser:
    """'OCR' der Fake-Folien: bildet Bild-Bytes auf festen Folientext ab."""

    TEXTE = {
        b"FOLIE-EINS": "Quicksort Partitionierung\nT(n) = 2T(n/2) + n",
        b"FOLIE-ZWEI": "Mergesort Mischen sortierter Listen",
    }

    def lies(self, bild: bytes) -> str:
        return self.TEXTE.get(bild, "")


class FakeOcr:
    """OCR-Fake: liefert für jede Scan-Seite festen Text."""

    def __init__(self, text: str = "Erkannter Scantext ueber Sortierverfahren."):
        self.text = text
        self.aufrufe: List[int] = []

    def lese_seite(self, pdf: Path, seitennummer: int) -> str:
        self.aufrufe.append(seitennummer)
        return self.text


@pytest.fixture
def fake_transkribierer() -> FakeTranskribierer:
    return FakeTranskribierer()


@pytest.fixture
def modul_dir_mit_vorlesung(modul_dir: Path) -> Path:
    (modul_dir / "vorlesung-01.mp4").write_bytes(b"kein echtes video")
    return modul_dir
