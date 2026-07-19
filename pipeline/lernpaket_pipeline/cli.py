"""Kommandozeile der Aufbereitung.

Beispiel:
    lernpaket pfad/zum/modul --ziel ../lernpakete
    lernpaket pfad/zum/modul --mit-asr --mit-folien --mit-ocr   # schwere Werkzeuge zuschalten
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .llm import ANBIETER
from .pipeline import erzeuge_und_schreibe


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="lernpaket",
        description="Aufbereitung: erzeugt aus einem Modulverzeichnis ein Lernpaket.")
    parser.add_argument("modul_dir", type=Path,
                        help="Verzeichnis mit Studienbrief-PDF, Vorlesungs-MP4s, "
                             "optional altklausuren/ und uebungen/")
    parser.add_argument("--ziel", type=Path, default=Path("../lernpakete"),
                        help="Zielverzeichnis für Lernpakete (Default: ../lernpakete)")
    parser.add_argument("--modul-id", default=None)
    parser.add_argument("--titel", default=None)
    parser.add_argument("--llm", default=None, choices=ANBIETER,
                        help="LLM-Anbieter für die Generierung (Default: Umgebung "
                             "LERNPAKET_LLM bzw. Auto-Erkennung; ohne Anbieter Heuristik)")
    parser.add_argument("--llm-modell", default=None,
                        help="Modellname beim gewählten Anbieter (Default: "
                             "LERNPAKET_LLM_MODELL bzw. Anbieter-Standard)")
    parser.add_argument("--mit-asr", action="store_true",
                        help="Vorlesungs-Audio mit faster-whisper transkribieren")
    parser.add_argument("--mit-folien", action="store_true",
                        help="Folien via PySceneDetect extrahieren (impliziert OCR für Folien)")
    parser.add_argument("--mit-ocr", action="store_true",
                        help="OCR-Fallback für Scan-Seiten (tesseract)")
    args = parser.parse_args(argv)

    kwargs = {"llm_anbieter": args.llm, "llm_modell": args.llm_modell}
    if args.mit_asr:
        from .extraktion.audio import FasterWhisperTranskribierer
        kwargs["transkribierer"] = FasterWhisperTranskribierer()
    if args.mit_ocr or args.mit_folien:
        from .extraktion.pdf import TesseractOcr
        if args.mit_ocr:
            kwargs["ocr"] = TesseractOcr()
    if args.mit_folien:
        from .extraktion.folien import PySceneDetectErkenner
        import io

        class _TesseractFolienLeser:
            def lies(self, bild: bytes) -> str:
                try:
                    import pytesseract  # type: ignore
                    from PIL import Image  # type: ignore
                except ImportError as exc:
                    raise RuntimeError(
                        "Folien-OCR benötigt die Extras 'ocr'.") from exc
                return pytesseract.image_to_string(Image.open(io.BytesIO(bild)), lang="deu")

        kwargs["szenen_erkenner"] = PySceneDetectErkenner()
        kwargs["folien_leser"] = _TesseractFolienLeser()

    ziel = erzeuge_und_schreibe(args.modul_dir, args.ziel,
                                modul_id=args.modul_id, titel=args.titel, **kwargs)
    print(f"Lernpaket geschrieben: {ziel}")
    manifest = json.loads((ziel / "manifest.json").read_text(encoding="utf-8"))
    for luecke in manifest.get("materialluecken", []):
        if not luecke.get("thema_id"):  # globale Lücken betreffen die Materiallage
            print(f"⚠️  {luecke['beschreibung']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
