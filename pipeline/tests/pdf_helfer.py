"""Erzeugt minimale PDFs für Fixtures — Textseiten und textlose 'Scan'-Seiten.

Handgeschriebenes PDF 1.4 mit Standardfont Helvetica (WinAnsi), damit die
Fixtures deterministisch und abhängigkeitsfrei bleiben.
"""
from __future__ import annotations

from pathlib import Path
from typing import List


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _seiten_strom(zeilen: List[str]) -> bytes:
    befehle = ["BT", "/F1 11 Tf", "14 TL", "50 750 Td"]
    for i, zeile in enumerate(zeilen):
        if i > 0:
            befehle.append("T*")
        befehle.append(f"({_escape(zeile)}) Tj")
    befehle.append("ET")
    return "\n".join(befehle).encode("latin-1", errors="replace")


def schreibe_pdf(pfad: Path, seiten: List[List[str]],
                 scan_seiten: List[int] = ()) -> Path:
    """Schreibt ein PDF. `seiten` = Liste von Zeilen-Listen; Seitennummern in
    `scan_seiten` (1-basiert) erhalten KEINE Textebene (nur ein graues Rechteck).
    """
    objekte: List[bytes] = []

    def obj(inhalt: bytes) -> int:
        objekte.append(inhalt)
        return len(objekte)

    font_nr_platzhalter = None
    kids = []
    inhalte_nrn = []
    for nummer, zeilen in enumerate(seiten, start=1):
        if nummer in scan_seiten:
            strom = b"0.8 g 50 400 500 300 re f"
        else:
            strom = _seiten_strom(zeilen)
        nr = obj(b"<< /Length " + str(len(strom)).encode() + b" >>\nstream\n"
                 + strom + b"\nendstream")
        inhalte_nrn.append(nr)

    font_nr = obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                  b"/Encoding /WinAnsiEncoding >>")
    seiten_baum_nr = len(objekte) + len(seiten) + 1  # nach den Page-Objekten
    for inhalt_nr in inhalte_nrn:
        nr = obj(b"<< /Type /Page /Parent " + str(seiten_baum_nr).encode()
                 + b" 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 "
                 + str(font_nr).encode() + b" 0 R >> >> /Contents "
                 + str(inhalt_nr).encode() + b" 0 R >>")
        kids.append(f"{nr} 0 R")
    baum_nr = obj(b"<< /Type /Pages /Kids [" + " ".join(kids).encode()
                  + b"] /Count " + str(len(seiten)).encode() + b" >>")
    assert baum_nr == seiten_baum_nr
    katalog_nr = obj(b"<< /Type /Catalog /Pages " + str(baum_nr).encode() + b" 0 R >>")

    puffer = bytearray(b"%PDF-1.4\n")
    positionen = [0]
    for i, inhalt in enumerate(objekte, start=1):
        positionen.append(len(puffer))
        puffer += f"{i} 0 obj\n".encode() + inhalt + b"\nendobj\n"
    xref_pos = len(puffer)
    puffer += f"xref\n0 {len(objekte) + 1}\n".encode()
    puffer += b"0000000000 65535 f \n"
    for pos in positionen[1:]:
        puffer += f"{pos:010d} 00000 n \n".encode()
    puffer += (f"trailer\n<< /Size {len(objekte) + 1} /Root {katalog_nr} 0 R >>\n"
               f"startxref\n{xref_pos}\n%%EOF\n").encode()
    pfad = Path(pfad)
    pfad.write_bytes(bytes(puffer))
    return pfad
