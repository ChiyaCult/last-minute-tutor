"""Reasoning-LLM-Anbindung: remote-only (ADR 0002), austauschbar für Tests.

Der Schlüssel kommt aus der Umgebung (ANTHROPIC_API_KEY) und wird nie in
Ausgabedateien geschrieben. Ohne Schlüssel läuft die Pipeline mit dem
deterministischen Heuristik-Generator weiter (graceful degradation) — die
Qualität ist dann geringer, aber der Vertrag identisch.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Optional, Protocol

STANDARD_MODELL = "claude-sonnet-5"
API_URL = "https://api.anthropic.com/v1/messages"


class ReasoningLLM(Protocol):
    def frage(self, system: str, prompt: str, max_tokens: int = 4096) -> str: ...


class AnthropicLLM:
    def __init__(self, api_key: Optional[str] = None, modell: str = STANDARD_MODELL):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.modell = modell
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY ist nicht gesetzt.")

    def frage(self, system: str, prompt: str, max_tokens: int = 4096) -> str:  # pragma: no cover - Netzwerk
        daten = json.dumps({
            "model": self.modell,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        anfrage = urllib.request.Request(API_URL, data=daten, headers={
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        })
        with urllib.request.urlopen(anfrage, timeout=300) as antwort:
            koerper = json.loads(antwort.read().decode("utf-8"))
        return "".join(block.get("text", "") for block in koerper.get("content", []))


def hole_llm() -> Optional[AnthropicLLM]:
    """AnthropicLLM, falls ein Schlüssel gesetzt ist, sonst None (Heuristik-Pfad)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicLLM()
    return None


def extrahiere_json(text: str):
    """Zieht das erste JSON-Objekt/-Array aus einer LLM-Antwort (auch aus ```-Fences)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    for start_zeichen, ende_zeichen in (("{", "}"), ("[", "]")):
        start = text.find(start_zeichen)
        if start == -1:
            continue
        tiefe = 0
        for i in range(start, len(text)):
            if text[i] == start_zeichen:
                tiefe += 1
            elif text[i] == ende_zeichen:
                tiefe -= 1
                if tiefe == 0:
                    return json.loads(text[start:i + 1])
        break
    raise ValueError("Kein JSON in der LLM-Antwort gefunden.")
