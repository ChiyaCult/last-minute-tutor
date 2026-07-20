"""Reasoning-LLM-Anbindung: remote-only bzw. lokal via Ollama (ADR 0002), austauschbar für Tests.

Vier Anbieter hinter derselben `ReasoningLLM`-Schnittstelle:

- ``anthropic`` — Anthropic Messages API (``ANTHROPIC_API_KEY``)
- ``gemini``    — Google Generative Language API (``GEMINI_API_KEY``/``GOOGLE_API_KEY``)
- ``copilot``   — GitHub Models, OpenAI-kompatibel (``GITHUB_TOKEN``)
- ``ollama``    — lokaler Ollama-Server, OpenAI-kompatibel (kein Schlüssel)

Auswahl über ``LERNPAKET_LLM`` (bzw. CLI ``--llm``), Modell-Override über
``LERNPAKET_LLM_MODELL`` (bzw. ``--llm-modell``). Ohne explizite Wahl werden
Anthropic und Gemini anhand vorhandener Schlüssel automatisch erkannt;
``copilot`` und ``ollama`` müssen explizit gewählt werden (ein gesetztes
``GITHUB_TOKEN`` bzw. ein laufender Ollama-Server sagt nichts über die Absicht).
Schlüssel kommen aus der Umgebung und werden nie in Ausgabedateien geschrieben.
Ohne Anbieter läuft die Pipeline mit dem deterministischen Heuristik-Generator
weiter (graceful degradation) — die Qualität ist dann geringer, aber der
Vertrag identisch.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Optional, Protocol

ANBIETER = ("anthropic", "gemini", "copilot", "ollama")
STANDARD_MODELLE = {
    "anthropic": "claude-sonnet-5",
    # Stabiler Alias statt Versionsnummer: Google mustert konkrete Versionen
    # schnell aus (gemini-2.5-flash lieferte bereits 404); "-latest" bleibt gültig.
    # Pro-Modelle haben im Free Tier kein Kontingent (429) — Flash als Default.
    "gemini": "gemini-flash-latest",
    "copilot": "openai/gpt-4o",
    "ollama": "llama3.1",
}
API_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
COPILOT_URL = "https://models.github.ai/inference"
OLLAMA_URL = "http://localhost:11434"


class ReasoningLLM(Protocol):
    def frage(self, system: str, prompt: str, max_tokens: int = 4096) -> str: ...


def _post_json(url: str, daten: dict, headers: dict, versuche: int = 4) -> dict:
    """POST mit Backoff bei Rate-Limit/Serverfehlern (Free-Tier-Kontingente)."""
    anfrage = urllib.request.Request(
        url, data=json.dumps(daten).encode("utf-8"),
        headers={"content-type": "application/json", **headers})
    for i in range(versuche):
        try:
            with urllib.request.urlopen(anfrage, timeout=300) as antwort:
                return json.loads(antwort.read().decode("utf-8"))
        except urllib.error.HTTPError as fehler:
            if fehler.code not in (429, 500, 502, 503) or i == versuche - 1:
                raise
            retry_after = fehler.headers.get("Retry-After", "")
            pause = float(retry_after) if retry_after.isdigit() else 2.0 ** (i + 2)
            time.sleep(min(90.0, pause))
    raise RuntimeError("unerreichbar")  # pragma: no cover - Schleife endet per return/raise


class AnthropicLLM:
    def __init__(self, api_key: Optional[str] = None, modell: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.modell = modell or STANDARD_MODELLE["anthropic"]
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY ist nicht gesetzt.")

    def frage(self, system: str, prompt: str, max_tokens: int = 4096) -> str:  # pragma: no cover - Netzwerk
        koerper = _post_json(API_URL, {
            "model": self.modell,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }, {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
        return "".join(block.get("text", "") for block in koerper.get("content", []))


class GeminiLLM:
    def __init__(self, api_key: Optional[str] = None, modell: Optional[str] = None):
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY")
                        or os.environ.get("GOOGLE_API_KEY", ""))
        self.modell = modell or STANDARD_MODELLE["gemini"]
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY (oder GOOGLE_API_KEY) ist nicht gesetzt.")

    def frage(self, system: str, prompt: str, max_tokens: int = 4096) -> str:  # pragma: no cover - Netzwerk
        koerper = _post_json(f"{GEMINI_URL}/{self.modell}:generateContent", {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }, {"x-goog-api-key": self.api_key})
        kandidaten = koerper.get("candidates") or [{}]
        teile = kandidaten[0].get("content", {}).get("parts", [])
        return "".join(t.get("text", "") for t in teile)


class OpenAiKompatibelLLM:
    """Chat-Completions-Schnittstelle — deckt GitHub Models (Copilot) und Ollama ab."""

    def __init__(self, basis_url: str, modell: str, api_key: str = ""):
        self.basis_url = basis_url.rstrip("/")
        self.modell = modell
        self.api_key = api_key

    def frage(self, system: str, prompt: str, max_tokens: int = 4096) -> str:  # pragma: no cover - Netzwerk
        headers = {"authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        koerper = _post_json(f"{self.basis_url}/chat/completions", {
            "model": self.modell,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
        }, headers)
        auswahl = koerper.get("choices") or [{}]
        return auswahl[0].get("message", {}).get("content") or ""


def _erzeuge_llm(anbieter: str, modell: Optional[str]) -> ReasoningLLM:
    if anbieter == "anthropic":
        return AnthropicLLM(modell=modell)
    if anbieter == "gemini":
        return GeminiLLM(modell=modell)
    if anbieter == "copilot":
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("COPILOT_API_KEY", "")
        if not token:
            raise RuntimeError("Copilot/GitHub Models benötigt GITHUB_TOKEN "
                               "(oder COPILOT_API_KEY).")
        basis = os.environ.get("LERNPAKET_COPILOT_URL", COPILOT_URL)
        return OpenAiKompatibelLLM(basis, modell or STANDARD_MODELLE["copilot"], token)
    if anbieter == "ollama":
        basis = os.environ.get("LERNPAKET_OLLAMA_URL", OLLAMA_URL).rstrip("/") + "/v1"
        return OpenAiKompatibelLLM(
            basis, modell or os.environ.get("LERNPAKET_OLLAMA_MODELL",
                                            STANDARD_MODELLE["ollama"]))
    raise RuntimeError(f"Unbekannter LLM-Anbieter '{anbieter}' "
                       f"(erlaubt: {', '.join(ANBIETER)}).")


def hole_llm(anbieter: Optional[str] = None,
             modell: Optional[str] = None) -> Optional[ReasoningLLM]:
    """LLM nach Wahl bzw. Auto-Erkennung, sonst None (Heuristik-Pfad).

    Explizite Wahl (Argument oder ``LERNPAKET_LLM``) schlägt fehl, wenn der
    zugehörige Schlüssel fehlt — stiller Rückfall auf die Heuristik wäre dann
    eine Überraschung. Ohne Wahl wird nur auto-erkannt, was eindeutig ist.
    """
    anbieter = anbieter or os.environ.get("LERNPAKET_LLM")
    modell = modell or os.environ.get("LERNPAKET_LLM_MODELL")
    if anbieter:
        return _erzeuge_llm(anbieter.strip().lower(), modell)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _erzeuge_llm("anthropic", modell)
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return _erzeuge_llm("gemini", modell)
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
