"""Optionale Fortschrittsbalken für die langen Schritte (ASR, OCR).

`balken()` liefert einen tqdm-Balken, wenn tqdm installiert **und** die Ausgabe
ein Terminal ist. Sonst (Docker, Logdatei, Pipe, oder tqdm fehlt) ein stiller
No-Op — dann bleiben die strukturierten Logs die verlässliche Fortschrittsquelle.
So bleibt die Ausgabe in Dateien/Containern sauber (keine \\r-Artefakte).
"""
from __future__ import annotations

from typing import Optional


class _StillerBalken:
    """Tut nichts — Schnittstelle kompatibel zu tqdm (update/close/Context)."""

    n = 0
    total = None

    def update(self, n: float = 1) -> None:  # noqa: D401 - No-Op
        pass

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def balken(total: Optional[float] = None, desc: str = "", unit: str = "it"):
    """tqdm-Balken oder stiller No-Op (bei fehlendem tqdm / nicht-TTY-Ausgabe)."""
    try:
        from tqdm import tqdm  # type: ignore
    except ImportError:
        return _StillerBalken()
    # disable=None → tqdm schaltet sich selbst ab, wenn stderr kein Terminal ist.
    return tqdm(total=total, desc=desc, unit=unit, disable=None, leave=False)
