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

Mit gesetztem `ANTHROPIC_API_KEY` generiert das Remote-Spitzenmodell die Lehrblöcke
und Quizfragen (ADR 0002); ohne Schlüssel läuft ein deterministischer
Heuristik-Generator (geringere Qualität, gleicher Vertrag). Jedes Artefakt trägt
Belege; ein Verifikationsdurchlauf prüft Antworten gegen die Quelle (ADR 0003).

## Lernphase (Player)

```bash
cd player
npm install
npm start          # http://localhost:4321
```

Der Player scannt `lernpakete/` (mehrere Module unabhängig), fährt Diagnosequiz →
Lücken → Lehrtiefe, plant fensteradaptiv (Triage ≤ 4 Tage, sonst Spacing, ADR 0006)
und speichert Fortschritt in `player/daten/fortschritt.db`. Für den Tutormodus
`ANTHROPIC_API_KEY` in der Server-Umgebung setzen — der Schlüssel bleibt im Backend.

## Tests

```bash
cd pipeline && .venv/bin/python -m pytest   # Verträge der Aufbereitung
cd player && npx vitest run                 # Player-Verhalten an Fixtures
```
