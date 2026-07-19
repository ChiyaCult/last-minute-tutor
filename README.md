# Klausur-Lernpaket-Generator

Wiederverwendbares Werkzeug für die Klausurvorbereitung im Fernstudium: erzeugt pro
Modul einmalig offline ein **Lernpaket** (Aufbereitung) und spielt es über einen
lokalen **Player** adaptiv aus (Lernphase). Vokabular: `CONTEXT.md` ·
Entscheidungen: `docs/adrs/` · PRD: `docs/PRD.md` · Datei-Grenze:
`docs/DATEI-VERTRAG.md`.

## Aufbau

```
pipeline/     Python-Batch-Pipeline (Aufbereitung): Materialien → Lernpaket-Dateien
lernpakete/   Ausgabe der Pipeline, Eingabe des Players (Datei-Vertrag)
player/       Node/JS-Player: Diagnosequiz, adaptive Lehrtiefe, Wiederholungsplan,
              Fortschritt (SQLite), Tutormodus (Backend-Proxy)
```

## Aufbereitung (einmalig pro Modul)

```bash
cd pipeline
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/lernpaket pfad/zum/modul --ziel ../lernpakete
```

Das Modulverzeichnis braucht die Pflichtquellen (`studienbrief*.pdf`, `*.mp4`);
`altklausuren/` und `uebungen/` sind Optionalquellen. Schwere Werkzeuge sind
optionale Extras und werden per Flag zugeschaltet:

```bash
pip install -e '.[asr]'    # faster-whisper  → --mit-asr    (Transkription)
pip install -e '.[folien]' # PySceneDetect   → --mit-folien (Folien aus Video)
pip install -e '.[ocr]'    # tesseract/poppler → --mit-ocr  (Scan-PDFs)
```

Die Lehrblöcke und Quizfragen generiert ein LLM (ADR 0002); ohne Anbindung läuft
ein deterministischer Heuristik-Generator (deutlich geringere Qualität, gleicher
Vertrag). Vier Anbieter stehen zur Wahl — per `--llm`/`--llm-modell` oder
Umgebung (`LERNPAKET_LLM`, `LERNPAKET_LLM_MODELL`):

| Anbieter    | Schlüssel/Voraussetzung                | Standardmodell    |
| ----------- | -------------------------------------- | ----------------- |
| `anthropic` | `ANTHROPIC_API_KEY`                    | `claude-sonnet-5` |
| `gemini`    | `GEMINI_API_KEY` (o. `GOOGLE_API_KEY`) | `gemini-flash-latest` |
| `copilot`   | `GITHUB_TOKEN` (GitHub Models)         | `openai/gpt-4o`   |
| `ollama`    | lokaler Ollama-Server (`LERNPAKET_OLLAMA_URL`, Default `localhost:11434`) | `llama3.1` |

```bash
.venv/bin/lernpaket pfad/zum/modul --llm gemini --llm-modell gemini-2.5-flash
LERNPAKET_LLM=ollama LERNPAKET_LLM_MODELL=qwen3 .venv/bin/lernpaket pfad/zum/modul
```

Ohne explizite Wahl werden `anthropic`/`gemini` anhand vorhandener Schlüssel
auto-erkannt; `copilot` und `ollama` müssen explizit gewählt werden. Jedes
Artefakt trägt Belege; ein Verifikationsdurchlauf prüft Antworten gegen die
Quelle (ADR 0003).

## Aufbereitung per Docker (Server-Betrieb)

Alle Abhängigkeiten — Python-Pakete inklusive aller Extras sowie die
Systemwerkzeuge ffmpeg, poppler und tesseract (mit deutschen Sprachdaten) —
stecken im Image (`pipeline/Dockerfile`); auf dem Server ist nur Docker nötig.
Materialien und Ergebnis sind Volumes (`./input` → `/input`, `./lernpakete` →
`/lernpakete`), die Whisper-Modelle (~3 GB) überleben in einem benannten Volume.

```bash
docker compose build
docker compose run --rm pipeline /input/mein_modul --ziel /lernpakete \
    --mit-asr --mit-ocr --mit-folien --llm gemini
```

LLM-Schlüssel kommen aus der Host-Umgebung oder einer `.env` neben der
`docker-compose.yml`; sie werden nie ins Image gebacken. Für ein lokales LLM
bringt das Compose-Profil `ollama` einen Ollama-Dienst mit
(`docker compose --profile ollama up -d ollama`, Modell per
`docker compose exec ollama ollama pull llama3.1`, dann
`docker compose run --rm -e LERNPAKET_LLM=ollama pipeline …`).

## Lernphase (Player)

```bash
cd player
npm install
npm start          # http://localhost:4321
```

Der Player scannt `lernpakete/` (mehrere Module unabhängig), fährt Diagnosequiz →
Lücken → Lehrtiefe, plant fensteradaptiv (Triage ≤ 4 Tage, sonst Spacing, ADR 0006)
und speichert Fortschritt in `player/daten/fortschritt.db`. Der Tutormodus nutzt
dieselbe LLM-Anbieter-Auswahl wie die Pipeline (`LERNPAKET_LLM` bzw.
Auto-Erkennung über `ANTHROPIC_API_KEY`/`GEMINI_API_KEY`) — Schlüssel bleiben in
der Server-Umgebung und erreichen nie das Frontend.

## Tests

```bash
cd pipeline && .venv/bin/python -m pytest   # Verträge der Aufbereitung
cd player && npx vitest run                 # Player-Verhalten an Fixtures
```
