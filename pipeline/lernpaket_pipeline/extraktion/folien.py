"""Folien aus Vorlesungsvideos: Wechsel erkennen, Duplikate verwerfen, lesen (Issue #29).

Reale Erkennung: PySceneDetect (AdaptiveDetector) + Frame-Export. Das Lesen der
Folien läuft durch dieselbe Extraktionsschicht wie PDFs (OCR/Parser), damit
Formeln, die nur visuell auf Folien stehen, im Lernpaket landen (ADR 0004).
Beide Schritte sind Adapter; Tests nutzen Fakes und prüfen den Vertrag
(Dedupe + Weiterleitung an die Extraktion).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Protocol


@dataclass
class Folie:
    nummer: int          # fortlaufend nach Dedupe, 1-basiert
    zeit_sekunden: float  # Zeitpunkt des Folienwechsels im Video
    bild: bytes           # PNG/JPEG-Bytes des Standbilds
    text: str = ""        # von der Folien-Extraktion gefüllt


class SzenenErkenner(Protocol):
    """Liefert pro erkanntem Folienwechsel (Zeitpunkt, Standbild-Bytes)."""

    def erkenne(self, mp4: Path) -> List["tuple[float, bytes]"]: ...


class FolienLeser(Protocol):
    """Liest den Text/die Formeln eines Folien-Standbilds (OCR/Parser-Schicht)."""

    def lies(self, bild: bytes) -> str: ...


class PySceneDetectErkenner:
    """Folienwechsel via PySceneDetect (extra 'folien')."""

    def __init__(self, schwelle: float = 3.0):
        self.schwelle = schwelle

    def erkenne(self, mp4: Path):  # pragma: no cover - benötigt OpenCV/Video
        try:
            from scenedetect import AdaptiveDetector, open_video, SceneManager  # type: ignore
            import cv2  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Folien-Erkennung benötigt PySceneDetect/OpenCV "
                "(pip install 'lernpaket-pipeline[folien]')."
            ) from exc
        video = open_video(str(mp4))
        manager = SceneManager()
        manager.add_detector(AdaptiveDetector(adaptive_threshold=self.schwelle))
        manager.detect_scenes(video)
        ergebnisse = []
        cap = cv2.VideoCapture(str(mp4))
        for start, _ in manager.get_scene_list():
            cap.set(cv2.CAP_PROP_POS_MSEC, start.get_seconds() * 1000)
            ok, frame = cap.read()
            if ok:
                ok2, puffer = cv2.imencode(".png", frame)
                if ok2:
                    ergebnisse.append((start.get_seconds(), puffer.tobytes()))
        cap.release()
        return ergebnisse


def _fingerabdruck(bild: bytes) -> str:
    return hashlib.sha256(bild).hexdigest()


def extrahiere_folien(mp4: Path, erkenner: SzenenErkenner, leser: FolienLeser) -> List[Folie]:
    """Erkennt Folienwechsel, verwirft Duplikate und liest jede eindeutige Folie."""
    gesehen = set()
    folien: List[Folie] = []
    for zeit, bild in erkenner.erkenne(mp4):
        abdruck = _fingerabdruck(bild)
        if abdruck in gesehen:
            continue
        gesehen.add(abdruck)
        folien.append(
            Folie(nummer=len(folien) + 1, zeit_sekunden=zeit, bild=bild, text=leser.lies(bild))
        )
    return folien
