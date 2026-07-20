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

## Aufbereitung (einmalig pro Modul, zwei Schritte)

```bash
cd pipeline
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,asr,ocr]'

.venv/bin/lernpaket extrahieren pfad/zum/modul               # Schritt 1: Material
.venv/bin/lernpaket generieren pfad/zum/modul --ziel ../lernpakete   # Schritt 2: KI
```

**Schritt 1 — Extrahieren** liest alle Materialien ein (Studienbrief-PDF,
Vorlesungsvideos per Whisper-Transkription, Scan-Seiten per OCR, Folien) und
schreibt das Ergebnis nach `<modul>/extraktion/`. Er läuft ohne LLM, nutzt
automatisch alle installierten Werkzeuge (Abwahl per `--ohne-asr`/`--ohne-ocr`/
`--ohne-folien`) und cacht Transkripte pro Video — nur der erste Lauf ist teuer.

**Schritt 2 — Generieren** baut daraus das Lernpaket (Themen, Lehrblöcke,
Quizfragen). Nur hier läuft das LLM — verschiedene Anbieter/Modelle lassen sich
ausprobieren, ohne neu zu extrahieren. `lernpaket pfad/zum/modul` (ohne
Unterkommando) führt weiterhin beides in einem Durchlauf aus.

Das Modulverzeichnis braucht die Pflichtquellen (`studienbrief*.pdf`, Videos als
`*.mp4`/`*.mkv`/…); `altklausuren/` und `uebungen/` sind Optionalquellen. Die
schweren Werkzeuge sind pip-Extras (`asr`, `ocr`, `folien`); OCR braucht
zusätzlich die Systempakete `tesseract` (mit `tesseract-lang`) und `poppler`.

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
.venv/bin/lernpaket generieren pfad/zum/modul --llm gemini
LERNPAKET_LLM=ollama LERNPAKET_LLM_MODELL=qwen3 .venv/bin/lernpaket generieren pfad/zum/modul
```

Ohne explizite Wahl werden `anthropic`/`gemini` anhand vorhandener Schlüssel
auto-erkannt; `copilot` und `ollama` müssen explizit gewählt werden. Jedes
Artefakt trägt Belege; ein Verifikationsdurchlauf prüft Antworten gegen die
Quelle (ADR 0003).

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
