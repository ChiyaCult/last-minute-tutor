"""Formel-/Tabellen-/Code-Erfassung aus PDF-Text (Issue #28, ADR 0004).

Rückgrat laut ADR 0004 ist ein Dokument-Parser wie Marker (Formel→LaTeX,
Tabellen, alles nach Markdown). Marker ist ein optionaler Adapter; ohne ihn
läuft eine deterministische Heuristik, die Formelzeilen als LaTeX markiert,
tabellarische Zeilen zu Markdown-Tabellen macht und Codezeilen einzäunt.
Der Player rendert `$...$`/`$$...$$` mit KaTeX.
"""
from __future__ import annotations

import re
from typing import List, Protocol


class DokumentParser(Protocol):
    """Normalisiert den Rohtext einer Seite nach Markdown (Formeln als LaTeX)."""

    def nach_markdown(self, seiten_text: str) -> str: ...


class MarkerParser:
    """Adapter für Marker (extra 'marker'); wandelt ganze PDFs nach Markdown.

    Bewusst dünn gehalten: Marker arbeitet auf Datei-Ebene, deshalb bietet der
    Adapter zusätzlich `pdf_nach_markdown`. Die Pipeline nutzt ihn, wenn das
    Paket installiert ist, sonst die Heuristik unten.
    """

    def pdf_nach_markdown(self, pfad: str) -> str:  # pragma: no cover - schweres Modell
        try:
            from marker.converters.pdf import PdfConverter  # type: ignore
            from marker.models import create_model_dict  # type: ignore
            from marker.output import text_from_rendered  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Marker ist nicht installiert (pip install 'lernpaket-pipeline[marker]')."
            ) from exc
        converter = PdfConverter(artifact_dict=create_model_dict())
        text, _, _ = text_from_rendered(converter(pfad))
        return text

    def nach_markdown(self, seiten_text: str) -> str:  # pragma: no cover
        return seiten_text


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
