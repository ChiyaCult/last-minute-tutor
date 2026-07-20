"""Kommandozeile der Aufbereitung — zwei getrennte Schritte, kaum Flags.

    lernpaket extrahieren pfad/zum/modul
        # Schritt 1: PDFs, Vorlesungen (ASR), OCR, Folien → <modul>/extraktion/
        # nutzt automatisch alle installierten Werkzeuge; Abwahl per --ohne-*
    lernpaket generieren pfad/zum/modul --ziel ../lernpakete
        # Schritt 2: Extraktionsergebnis → Lernpaket; LLM-Wahl per --llm/--llm-modell
    lernpaket pfad/zum/modul --ziel ../lernpakete
        # beides nacheinander (Kompatibilitätsform; --mit-* Flags wie bisher)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

from .llm import ANBIETER
from .pipeline import (erzeuge_und_schreibe, extrahiere_material,
                       generiere_lernpaket, lade_extraktion,
                       schreibe_extraktion)
from .vertrag import schreibe_lernpaket


def _vorhanden(*module: str) -> bool:
    return all(importlib.util.find_spec(m) is not None for m in module)


def _baue_werkzeuge(mit_asr: bool, mit_ocr: bool, mit_folien: bool) -> dict:
    """Erzeugt die Werkzeug-Adapter; wirft bei fehlenden Extras eine klare Meldung."""
    kwargs = {}
    if mit_asr:
        from .extraktion.audio import FasterWhisperTranskribierer
        kwargs["transkribierer"] = FasterWhisperTranskribierer()
    if mit_ocr:
        from .extraktion.pdf import TesseractOcr
        kwargs["ocr"] = TesseractOcr()
    if mit_folien:
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
    return kwargs


def _erkenne_werkzeuge(args) -> dict:
    """Auto-Erkennung installierter Werkzeuge (Abwahl per --ohne-*), mit Bericht."""
    asr = not args.ohne_asr and _vorhanden("faster_whisper")
    ocr = (not args.ohne_ocr and _vorhanden("pytesseract", "fitz", "PIL")
           and shutil.which("tesseract") is not None)
    folien = (not args.ohne_folien and _vorhanden("scenedetect", "pytesseract", "PIL")
              and shutil.which("tesseract") is not None)

    def status(an: bool, abgewaehlt: bool, fehlt: str) -> str:
        if abgewaehlt:
            return "✗ (abgewählt)"
        return "✓" if an else f"✗ ({fehlt})"

    print("Werkzeuge: "
          f"ASR {status(asr, args.ohne_asr, 'faster-whisper fehlt')} · "
          f"OCR {status(ocr, args.ohne_ocr, 'tesseract/Extras fehlen')} · "
          f"Folien {status(folien, args.ohne_folien, 'scenedetect fehlt')}")
    return _baue_werkzeuge(asr, ocr, folien)


def _melde_luecken(materialluecken) -> None:
    for luecke in materialluecken:
        thema_id = (luecke.get("thema_id") if isinstance(luecke, dict)
                    else luecke.thema_id)
        beschreibung = (luecke.get("beschreibung") if isinstance(luecke, dict)
                        else luecke.beschreibung)
        if not thema_id:  # globale Lücken betreffen die Materiallage
            print(f"⚠️  {beschreibung}", file=sys.stderr)


def _cmd_extrahieren(argv) -> int:
    parser = argparse.ArgumentParser(
        prog="lernpaket extrahieren",
        description="Schritt 1: Materialien einlesen (PDF, ASR, OCR, Folien) — ohne LLM. "
                    "Ergebnis liegt unter <modul>/extraktion/ und wird von "
                    "`lernpaket generieren` verwendet.")
    parser.add_argument("modul_dir", type=Path)
    parser.add_argument("--ohne-asr", action="store_true",
                        help="Vorlesungen nicht transkribieren")
    parser.add_argument("--ohne-ocr", action="store_true",
                        help="Scan-Seiten nicht per OCR lesen")
    parser.add_argument("--ohne-folien", action="store_true",
                        help="keine Folien aus den Videos ziehen")
    args = parser.parse_args(argv)

    extraktion = extrahiere_material(args.modul_dir, **_erkenne_werkzeuge(args))
    ziel = schreibe_extraktion(extraktion, args.modul_dir)
    print(f"Extraktion geschrieben: {ziel} ({len(extraktion.chunks)} Chunks)")
    _melde_luecken(extraktion.materialluecken)
    return 0


def _cmd_generieren(argv) -> int:
    parser = argparse.ArgumentParser(
        prog="lernpaket generieren",
        description="Schritt 2: aus dem Extraktionsergebnis das Lernpaket generieren. "
                    "Anbieter-Auswahl siehe README (Auto-Erkennung über Umgebung).")
    parser.add_argument("modul_dir", type=Path)
    parser.add_argument("--ziel", type=Path, default=Path("../lernpakete"))
    parser.add_argument("--modul-id", default=None)
    parser.add_argument("--titel", default=None)
    parser.add_argument("--llm", default=None, choices=ANBIETER)
    parser.add_argument("--llm-modell", default=None)
    args = parser.parse_args(argv)

    extraktion = lade_extraktion(args.modul_dir)
    paket = generiere_lernpaket(
        extraktion,
        modul_id=args.modul_id or args.modul_dir.name.lower().replace(" ", "-"),
        titel=args.titel or args.modul_dir.name,
        llm_anbieter=args.llm, llm_modell=args.llm_modell)
    ziel = schreibe_lernpaket(paket, args.ziel / paket.manifest.modul_id)
    print(f"Lernpaket geschrieben: {ziel}")
    _melde_luecken(paket.manifest.materialluecken)
    return 0


def _cmd_komplett(argv) -> int:
    """Kompatibilitätsform: beide Schritte in einem Lauf (Werkzeuge per --mit-*)."""
    parser = argparse.ArgumentParser(
        prog="lernpaket",
        description="Aufbereitung in einem Durchlauf. Empfohlen sind die getrennten "
                    "Schritte `lernpaket extrahieren` und `lernpaket generieren`.")
    parser.add_argument("modul_dir", type=Path,
                        help="Verzeichnis mit Studienbrief-PDF, Vorlesungsvideos, "
                             "optional altklausuren/ und uebungen/")
    parser.add_argument("--ziel", type=Path, default=Path("../lernpakete"))
    parser.add_argument("--modul-id", default=None)
    parser.add_argument("--titel", default=None)
    parser.add_argument("--llm", default=None, choices=ANBIETER)
    parser.add_argument("--llm-modell", default=None)
    parser.add_argument("--mit-asr", action="store_true")
    parser.add_argument("--mit-folien", action="store_true")
    parser.add_argument("--mit-ocr", action="store_true")
    args = parser.parse_args(argv)

    kwargs = {"llm_anbieter": args.llm, "llm_modell": args.llm_modell}
    kwargs.update(_baue_werkzeuge(args.mit_asr, args.mit_ocr, args.mit_folien))
    ziel = erzeuge_und_schreibe(args.modul_dir, args.ziel,
                                modul_id=args.modul_id, titel=args.titel, **kwargs)
    print(f"Lernpaket geschrieben: {ziel}")
    manifest = json.loads((ziel / "manifest.json").read_text(encoding="utf-8"))
    _melde_luecken(manifest.get("materialluecken", []))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "extrahieren":
        return _cmd_extrahieren(argv[1:])
    if argv and argv[0] == "generieren":
        return _cmd_generieren(argv[1:])
    return _cmd_komplett(argv)


if __name__ == "__main__":
    sys.exit(main())
