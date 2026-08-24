"""Vorlesungs-Audio → Transkript mit Zeitstempeln (Issue #22, ADR 0004).

Reale Implementierung: faster-whisper (Whisper large-v3, VAD gegen
Stille-Halluzination). In Tests ersetzt eine Fake-Implementierung den Adapter —
geprüft wird der Vertrag (Segmente mit Zeitstempeln fließen in den
Themenkatalog), nicht das ASR-Modell selbst.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Protocol

log = logging.getLogger("lernpaket")


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
    """ASR via faster-whisper (extra 'asr'). Läuft lokal — erlaubt laut ADR 0002/0004.

    Gerät/Rechentyp sind über ``LERNPAKET_ASR_DEVICE`` (auto|cpu|cuda) und
    ``LERNPAKET_ASR_COMPUTE`` steuerbar. Default ``auto`` nutzt eine GPU, wenn
    vorhanden. Fehlen dabei die CUDA-Bibliotheken (typischer Ubuntu-Fehler
    „library libcublas.so.12 is not found or cannot be loaded"), wird
    automatisch auf CPU zurückgefallen — die Aufbereitung läuft weiter.

    Der Rechentyp wird, wenn nichts vorgegeben ist, erst beim Laden anhand des
    tatsächlichen Geräts bestimmt: auf GPU ``auto`` (dort wählt CTranslate2
    float16), auf CPU ``int8`` — siehe `_standard_compute_type`.
    """

    def __init__(self, modell: str = "large-v3", sprache: str = "de",
                 device: str = None, compute_type: str = None):
        self.modell = modell
        self.sprache = sprache
        self.device = device or os.environ.get("LERNPAKET_ASR_DEVICE", "auto")
        # Leerer Wert heißt "beim Laden entscheiden" — das echte Gerät steht
        # bei device="auto" erst dann fest.
        self.compute_type = (compute_type
                             or os.environ.get("LERNPAKET_ASR_COMPUTE") or "")
        # Einmal geladen, für alle Videos wiederverwendet: sonst kostet jedes
        # Video erneut das Laden des Modells und eine HuggingFace-Abfrage nach
        # der aktuellen Revision — bei fehlendem Netz ein Timeout je Video.
        self._modell = None

    def _nutzt_gpu(self) -> bool:
        if self.device == "cpu":
            return False
        if self.device != "auto":
            return True
        try:  # pragma: no cover - hängt an der CUDA-Installation
            import ctranslate2  # type: ignore  (Abhängigkeit von faster-whisper)
            return ctranslate2.get_cuda_device_count() > 0
        except Exception:
            return False

    def _standard_compute_type(self) -> str:
        """Rechentyp, wenn keiner vorgegeben ist.

        Auf CPU bewusst ``int8`` statt ``auto``: CTranslate2 quantisiert das
        Modell bei ``auto`` beim Laden auf die breiteste unterstützte Genauigkeit
        um. Auf Apple Silicon dauert das bei large-v3 über eine Viertelstunde,
        ohne dass ein Fehler fällt — der CPU-Rückfall unten greift also nicht,
        der Lauf kriecht nur. Mit ``int8`` lädt dasselbe Modell in Sekunden.
        Auf GPU bleibt ``auto`` richtig (CTranslate2 nimmt dort float16).
        """
        return "auto" if self._nutzt_gpu() else "int8"

    def _lade_modell(self, WhisperModel):
        if self._modell is not None:
            return self._modell
        compute_type = self.compute_type or self._standard_compute_type()
        try:
            self._modell = WhisperModel(self.modell, device=self.device,
                                        compute_type=compute_type)
        except Exception as fehler:  # CUDA-Libs fehlen / GPU nicht nutzbar
            if self.device == "cpu":
                raise
            log.warning("GPU-Transkription nicht möglich (%s) — falle auf CPU zurück. "
                        "Für GPU die CUDA-12-Pakete installieren (siehe README).",
                        str(fehler).splitlines()[0])
            self._modell = WhisperModel(self.modell, device="cpu", compute_type="int8")
        return self._modell

    def transkribiere(self, mp4: Path) -> Transkript:  # pragma: no cover - schweres Modell
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Transkription benötigt faster-whisper "
                "(pip install 'lernpaket-pipeline[asr]')."
            ) from exc
        from ..fortschritt import balken

        modell = self._lade_modell(WhisperModel)
        segmente, info = modell.transcribe(str(mp4), language=self.sprache, vad_filter=True)
        gesamt = round(getattr(info, "duration", 0) or 0) or None
        ergebnis: List[TranskriptSegment] = []
        # Whisper liefert die Segmente fortlaufend beim Rechnen — der Balken
        # wächst nach transkribierten Audiosekunden (s.end) bis zur Gesamtdauer.
        bar = balken(total=gesamt, desc=f"ASR {Path(mp4).name}", unit="s")
        for s in segmente:
            ergebnis.append(TranskriptSegment(start=s.start, ende=s.end, text=s.text))
            bar.update((min(gesamt, round(s.end)) - bar.n) if gesamt else 1)
        bar.close()
        return Transkript(datei=Path(mp4).name, segmente=ergebnis)


def minuten_position(sekunden: float) -> str:
    m, s = divmod(int(sekunden), 60)
    return f"Min. {m:d}:{s:02d}"
