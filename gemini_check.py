#!/usr/bin/env python
"""Welches Gemini-Modell antwortet gerade? Und wie stabil?

    ./pipeline/.venv/bin/python gemini_check.py

Hintergrund: `gemini-flash-latest` zeigt immer auf das neueste Flash-Modell und
damit auf das am stärksten belegte. Im Free Tier äußert sich das als 503
("model overloaded") — kein Kontingentproblem, sondern Verdrängung. Ein älteres,
stabiles Modell hat oft Kapazität übrig.

Listet die verfügbaren Modelle, schickt an jeden Kandidaten drei kleine
Anfragen und meldet, welche durchkommen. Drei statt einer, weil ein einzelner
Treffer nichts über Stabilität sagt — genau daran ist der Lauf gescheitert.

Der Schlüssel kommt aus GEMINI_API_KEY/GOOGLE_API_KEY und wird nirgends
ausgegeben.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASIS = "https://generativelanguage.googleapis.com/v1beta"
VERSUCHE_JE_MODELL = 3
ABSTAND = 3.2  # wie die Pipeline: knapp unter 20 Anfragen/Minute


def schluessel() -> str:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    print("GEMINI_API_KEY (oder GOOGLE_API_KEY) ist nicht gesetzt.")
    raise SystemExit(1)


def hole(url: str, key: str, daten=None) -> tuple[int, dict | str]:
    anfrage = urllib.request.Request(
        url, headers={"x-goog-api-key": key, "content-type": "application/json"},
        data=json.dumps(daten).encode() if daten else None)
    try:
        with urllib.request.urlopen(anfrage, timeout=60) as antwort:
            return 200, json.loads(antwort.read().decode())
    except urllib.error.HTTPError as fehler:
        try:
            koerper = json.loads(fehler.read().decode())
            text = koerper.get("error", {}).get("message", "")[:110]
        except Exception:
            text = fehler.reason
        return fehler.code, text
    except Exception as fehler:  # Netzfehler
        return 0, str(fehler)[:110]


def main() -> int:
    key = schluessel()
    code, antwort = hole(f"{BASIS}/models", key)
    if code != 200:
        print(f"Modellliste nicht abrufbar (HTTP {code}): {antwort}")
        return 1

    kandidaten = []
    for m in antwort.get("models", []):
        name = m.get("name", "").removeprefix("models/")
        methoden = m.get("supportedGenerationMethods") or m.get(
            "supported_generation_methods") or []
        # Nur Textgenerierung, keine Embedding-/Vision-Sondermodelle.
        if "generateContent" not in methoden:
            continue
        if any(x in name for x in ("embedding", "aqa", "imagen", "veo", "tts")):
            continue
        kandidaten.append(name)

    # Flash zuerst: Pro-Modelle haben im Free Tier oft gar kein Kontingent.
    kandidaten.sort(key=lambda n: (("flash" not in n), "latest" in n, n))
    print(f"{len(kandidaten)} Textmodelle verfügbar. Teste je {VERSUCHE_JE_MODELL} "
          f"Anfragen mit {ABSTAND}s Abstand.\n")
    print(f"{'Modell':<42} {'Ergebnis':<26} Codes")
    print("-" * 84)

    brauchbar = []
    for name in kandidaten:
        codes = []
        for _ in range(VERSUCHE_JE_MODELL):
            code, _antwort = hole(
                f"{BASIS}/models/{name}:generateContent", key,
                {"contents": [{"role": "user", "parts": [{"text": "Sag nur: ok"}]}],
                 "generationConfig": {"maxOutputTokens": 5}})
            codes.append(code)
            time.sleep(ABSTAND)
        treffer = codes.count(200)
        if treffer == VERSUCHE_JE_MODELL:
            urteil, brauchbar_ = "STABIL", True
        elif treffer:
            urteil, brauchbar_ = f"wackelig ({treffer}/{VERSUCHE_JE_MODELL})", False
        else:
            urteil, brauchbar_ = "keine Antwort", False
        if brauchbar_:
            brauchbar.append(name)
        print(f"{name:<42} {urteil:<26} {codes}")

    print()
    if brauchbar:
        empfehlung = brauchbar[0]
        print(f"Empfehlung: {empfehlung}\n")
        print("  export LERNPAKET_LLM_MODELL=" + empfehlung)
    else:
        print("Kein Modell antwortet stabil. 503 heißt Überlastung auf Googles "
              "Seite — später erneut versuchen oder lokal generieren.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
