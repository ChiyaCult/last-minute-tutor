"""Reasoning-LLM-Anbindung: remote-only bzw. lokal via Ollama (ADR 0002), austauschbar für Tests.

Vier Anbieter hinter derselben `ReasoningLLM`-Schnittstelle:

- ``anthropic`` — Anthropic Messages API (``ANTHROPIC_API_KEY``)
- ``gemini``    — Google Generative Language API (``GEMINI_API_KEY``/``GOOGLE_API_KEY``)
- ``copilot``   — GitHub Models, OpenAI-kompatibel (``GITHUB_TOKEN``)
- ``ollama``    — lokaler Ollama-Server, native ``/api/chat``-Route (kein Schlüssel)

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

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Protocol

log = logging.getLogger("lernpaket")

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

# Kontextfenster für Ollama. Ohne Angabe nimmt der Server seinen eigenen Default
# (aktuell 4096 Token) und kürzt längere Prompts KOMMENTARLOS — der Generierungs-
# Prompt liegt mit bis zu 12 Chunks à 1400 Zeichen darüber, das Modell sähe die
# hinteren Chunks nie und würde deren chunk_ids trotzdem erfinden.
# Ollama clamped selbst auf das Maximum des Modells, zu hoch ist also harmlos.
# Achtung: nur die native /api/chat-Route wertet `options` aus — die OpenAI-
# kompatible /v1/chat/completions verwirft sie stillschweigend (nachgemessen).
OLLAMA_CTX = 32768


def _ollama_ctx() -> int:
    roh = os.environ.get("LERNPAKET_OLLAMA_CTX", "")
    return int(roh) if roh.isdigit() and int(roh) > 0 else OLLAMA_CTX

# Versuche je Anfrage bei Rate-Limit/Serverfehler. Die Aufbereitung läuft
# unbeaufsichtigt und einmalig — ein 503 des Anbieters ist typischerweise nach
# ein bis zwei Minuten vorbei, und so lange zu warten ist allemal billiger, als
# das Thema heuristisch abzufrühstücken. Backoff: 4, 8, 16, 32, 64 Sekunden.
VERSUCHE = 6


class ReasoningLLM(Protocol):
    def frage(self, system: str, prompt: str, max_tokens: int = 4096) -> str: ...


class LLMDienstNichtVerfuegbar(RuntimeError):
    """Der Anbieter ist auch nach allen Wiederholversuchen nicht erreichbar.

    Bricht den Lauf ab, statt ihn stillschweigend in geringerer Qualität zu
    Ende zu bringen: Wer ein LLM angefordert hat, will kein heuristisches
    Ersatzpaket, das später niemand mehr als solches erkennt. Dank des
    Antwort-Caches kostet ein späterer zweiter Anlauf nur die noch fehlenden
    Aufrufe.
    """


# Diese Fehler gehen vorüber — der Dienst ist überlastet oder kurz weg.
# Alles andere (401 Schlüssel falsch, 400 Anfrage kaputt, 404 Modell weg) ist
# dauerhaft und wird durch Wiederholen nicht besser.
VORUEBERGEHENDE_CODES = (408, 409, 425, 429, 500, 502, 503, 504)


def ist_voruebergehend(fehler: BaseException) -> bool:
    """Lohnt ein späterer zweiter Anlauf?"""
    if isinstance(fehler, urllib.error.HTTPError):
        return fehler.code in VORUEBERGEHENDE_CODES
    # Netzfehler ohne HTTP-Antwort (DNS, Verbindungsabbruch, Timeout).
    return isinstance(fehler, (urllib.error.URLError, TimeoutError, OSError))


class GecachterLLM:
    """Legt jede Antwort unter dem Hash ihrer Anfrage ab und liest sie wieder.

    Der Generierungsschritt kostet Kontingent; ein zweiter Anlauf nach einem
    Abbruch soll nur die noch fehlenden Themen bezahlen. Der Schlüssel umfasst
    Modell, System-Prompt und Prompt — ändert sich das Material (und damit die
    Chunk-Texte im Prompt), greift der Cache bewusst nicht mehr.

    Gleiche Bauart wie der Transkript- und der Parser-Cache: eine Datei je
    Eintrag unter `<modul>/extraktion/`, für den Nutzer löschbar.
    """

    def __init__(self, llm: ReasoningLLM, verzeichnis: Optional[Path]):
        self.llm = llm
        self.verzeichnis = Path(verzeichnis) if verzeichnis else None
        self.treffer = 0
        self.aufrufe = 0

    @property
    def modell(self) -> str:
        return getattr(self.llm, "modell", type(self.llm).__name__)

    def _datei(self, system: str, prompt: str) -> Optional[Path]:
        if self.verzeichnis is None:
            return None
        schluessel = hashlib.sha256(
            "\x00".join((self.modell, system, prompt)).encode("utf-8")).hexdigest()
        return self.verzeichnis / f"{schluessel[:32]}.json"

    def frage(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        datei = self._datei(system, prompt)
        if datei is not None and datei.exists():
            try:
                self.treffer += 1
                return json.loads(datei.read_text(encoding="utf-8"))["antwort"]
            except (OSError, ValueError, KeyError):
                log.warning("Cache-Eintrag unlesbar, wird neu geholt: %s", datei.name)
        antwort = self.llm.frage(system, prompt, max_tokens=max_tokens)
        self.aufrufe += 1
        if datei is not None:
            try:
                datei.parent.mkdir(parents=True, exist_ok=True)
                datei.write_text(json.dumps(
                    {"modell": self.modell, "prompt": prompt, "antwort": antwort},
                    ensure_ascii=False), encoding="utf-8")
            except OSError as fehler:  # pragma: no cover - Platte voll o. Ä.
                log.warning("Antwort konnte nicht gecacht werden (%s).", fehler)
        return antwort


# Zeit, die eine einzelne Anfrage brauchen darf. Für Remote-Anbieter ist eine
# Antwort nach 5 Minuten praktisch tot. Lokale Inferenz ist eine andere Welt:
# ein 27B auf einem M3 braucht für einen 9k-Token-Prompt gut 400 Sekunden
# (gemessen), und ein Timeout gilt als vorübergehender Fehler — der Lauf bräche
# also beim ersten Thema ab, statt einfach zu warten.
ZEITLIMIT = 300
ZEITLIMIT_LOKAL = 3600


def _zeitlimit(name: str, standard: int) -> int:
    roh = os.environ.get(name, "")
    return int(roh) if roh.isdigit() and int(roh) > 0 else standard


def _post_json(url: str, daten: dict, headers: dict, versuche: int = VERSUCHE,
               zeitlimit: int = ZEITLIMIT) -> dict:
    """POST mit Backoff bei Rate-Limit/Serverfehlern (Free-Tier-Kontingente)."""
    anfrage = urllib.request.Request(
        url, data=json.dumps(daten).encode("utf-8"),
        headers={"content-type": "application/json", **headers})
    for i in range(versuche):
        try:
            with urllib.request.urlopen(anfrage, timeout=zeitlimit) as antwort:
                return json.loads(antwort.read().decode("utf-8"))
        except urllib.error.HTTPError as fehler:
            if fehler.code not in VORUEBERGEHENDE_CODES or i == versuche - 1:
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


class OllamaLLM:
    """Lokaler Ollama-Server über die native ``/api/chat``-Route.

    Nicht die OpenAI-kompatible Route, obwohl die bequemer wäre: nur ``/api/chat``
    wertet ``options.num_ctx`` aus. Über ``/v1/chat/completions`` bleibt das
    Kontextfenster bei 4096 Token, und der Prompt wird stumm abgeschnitten.

    ``think`` wird bewusst abgeschaltet: Reasoning-Modelle (Qwen3 & Co.) würden
    sonst einen Gutteil des Token-Budgets in einen ``<think>``-Block stecken, den
    hier ohnehin niemand liest. ``LERNPAKET_OLLAMA_THINK=1`` schaltet es an;
    ``extrahiere_json`` kommt mit beidem zurecht.
    """

    def __init__(self, basis_url: str, modell: str):
        self.basis_url = basis_url.rstrip("/")
        self.modell = modell

    def frage(self, system: str, prompt: str, max_tokens: int = 4096) -> str:  # pragma: no cover - Netzwerk
        denken = os.environ.get("LERNPAKET_OLLAMA_THINK", "") == "1"
        koerper = _post_json(f"{self.basis_url}/api/chat", {
            "model": self.modell,
            "stream": False,
            "think": denken,
            "options": {"num_ctx": _ollama_ctx(), "num_predict": max_tokens},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
        }, {}, zeitlimit=_zeitlimit("LERNPAKET_OLLAMA_TIMEOUT", ZEITLIMIT_LOKAL))
        return koerper.get("message", {}).get("content") or ""


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
        basis = os.environ.get("LERNPAKET_OLLAMA_URL", OLLAMA_URL)
        return OllamaLLM(
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


# LaTeX und JSON vertragen sich schlecht: "\\overline{Q}" ist gültiges LaTeX,
# aber "\\o" ist keine gültige JSON-Escape-Sequenz. Da der System-Prompt Formeln
# als LaTeX verlangt, produzieren Modelle das systematisch — gemessen an einem
# Thema über Schaltfunktionen. Der Fehler ist ein JSONDecodeError (erbt von
# ValueError) und würde als stille Materiallücke enden.
# Repariert wird nur, was JSON nicht als Escape kennt; gültige Sequenzen
# (\n, \", \uXXXX) bleiben unangetastet.
_KAPUTTES_ESCAPE_RE = re.compile(r'\\(?!["\\/bfnrtu])')


def _repariere_escapes(text: str) -> str:
    return _KAPUTTES_ESCAPE_RE.sub(r"\\\\", text)


# Reasoning-Modelle stellen ihrer Antwort einen Gedankengang voran. Der enthält
# regelmäßig geschweifte Klammern (verworfene JSON-Entwürfe), auf die die Suche
# nach dem ersten "{" sonst hereinfällt.
_DENK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _ohne_denkblock(text: str) -> str:
    text = _DENK_RE.sub("", text)
    # Abgeschnittener Gedankengang (Token-Budget alle): ab hier steht nichts
    # Verwertbares mehr — lieber sauber als Materiallücke melden als Denktext
    # als Lehrblock auszuliefern.
    offen = text.lower().rfind("<think>")
    return text[:offen] if offen != -1 else text


def extrahiere_json(text: str):
    """Zieht das erste JSON-Objekt/-Array aus einer LLM-Antwort (auch aus ```-Fences)."""
    text = _ohne_denkblock(text).strip()
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
                    roh = text[start:i + 1]
                    try:
                        return json.loads(roh)
                    except json.JSONDecodeError:
                        # Zweiter Anlauf mit reparierten Backslashes, statt ein
                        # sonst brauchbares Ergebnis wegen LaTeX zu verwerfen.
                        return json.loads(_repariere_escapes(roh))
        break
    raise ValueError("Kein JSON in der LLM-Antwort gefunden.")
