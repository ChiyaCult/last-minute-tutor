"""Vorlesungs-Audio → Transkript mit Zeitstempeln (Issue #22, ADR 0004).

Reale Implementierung: faster-whisper (Whisper large-v3, VAD gegen
Stille-Halluzination). In Tests ersetzt eine Fake-Implementierung den Adapter —
geprüft wird der Vertrag (Segmente mit Zeitstempeln fließen in den
Themenkatalog), nicht das ASR-Modell selbst.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Protocol


@dataclass
class TranskriptSegment:
    start: float  # Sekunden
    ende: float
    text: str


@dataclass
class Transkript:
    datei: str
    segmente: List[TranskriptSegment]

    def als_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segmente)


class Transkribierer(Protocol):
    def transkribiere(self, mp4: Path) -> Transkript: ...


class FasterWhisperTranskribierer:
    """ASR via faster-whisper (extra 'asr'). Läuft lokal — erlaubt laut ADR 0002/0004."""

    def __init__(self, modell: str = "large-v3", sprache: str = "de"):
        self.modell = modell
        self.sprache = sprache

    def transkribiere(self, mp4: Path) -> Transkript:  # pragma: no cover - schweres Modell
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Transkription benötigt faster-whisper "
                "(pip install 'lernpaket-pipeline[asr]')."
            ) from exc
        modell = WhisperModel(self.modell, device="auto", compute_type="auto")
        segmente, _ = modell.transcribe(str(mp4), language=self.sprache, vad_filter=True)
        return Transkript(
            datei=Path(mp4).name,
            segmente=[TranskriptSegment(start=s.start, ende=s.end, text=s.text) for s in segmente],
        )


def minuten_position(sekunden: float) -> str:
    m, s = divmod(int(sekunden), 60)
    return f"Min. {m:d}:{s:02d}"
