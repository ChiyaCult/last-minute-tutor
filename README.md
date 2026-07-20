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

### Einmalige Installation

Verwaltet mit [uv](https://docs.astral.sh/uv/): ein Befehl legt die venv an,
installiert alles und pinnt exakte Versionen (`uv.lock`, reproduzierbar).

```bash
cd pipeline
uv sync --extra asr --extra ocr --extra folien   # alles inkl. schwerer Werkzeuge
```

uv einmal installieren, falls nicht vorhanden: `brew install uv` (macOS) oder
`curl -LsSf https://astral.sh/uv/install.sh | sh`. Der `uv sync`-Befehl zieht
**alle** Python-Abhängigkeiten in die venv — inklusive ffmpeg (steckt in den
Paketen `av`/`opencv`) und dem PDF-Rendering (PyMuPDF). Die Extras kannst du
weglassen, wenn du das jeweilige Werkzeug nicht brauchst:

| Extra    | Werkzeug                        | wofür                              |
| -------- | ------------------------------- | ---------------------------------- |
| `asr`    | faster-whisper                  | Vorlesungsvideos transkribieren    |
| `ocr`    | pytesseract + PyMuPDF           | Text aus Scan-Seiten lesen         |
| `folien` | PySceneDetect + OpenCV          | Folien-Standbilder aus Videos      |

**Eine einzige Sache liegt außerhalb von Pythons Reichweite** — nur nötig für
`ocr`/`folien`: die OCR-Engine **tesseract** samt deutschen Sprachdaten (ein
C++-Programm, kein pip-Paket, also von keinem Python-Werkzeug installierbar):

```bash
brew install tesseract tesseract-lang     # macOS
# Debian/Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-deu
```

Kein poppler, kein ffmpeg nötig — die bringt uv/pip mit. Ohne die Extras
(`uv sync`) läuft die reine PDF-Text-Pipeline ganz ohne System-Werkzeuge.

### ASR auf GPU (NVIDIA)

GPU-Transkription ist deutlich schneller (die Qualität bleibt identisch — es ist
dasselbe `large-v3`-Modell). faster-whisper nutzt mit `device=auto` automatisch
eine GPU, sobald CUDA verfügbar ist. Fehlen die CUDA-Bibliotheken (typischer
Fehler `library libcublas.so.12 is not found or cannot be loaded`), fällt die
Pipeline selbsttätig auf die CPU zurück und läuft weiter — abgestürzt wird nicht.
`CTranslate2` (das ASR-Backend, hier 4.8) braucht **CUDA 12 + cuDNN 9** und einen
installierten NVIDIA-Treiber (`nvidia-smi`). Drei Wege, GPU wirklich zu nutzen:

**A — CUDA-Libs per pip (kein System-CUDA, schnellster Weg auf Ubuntu):**
```bash
uv sync --extra asr --extra ocr --extra folien --extra gpu   # zieht CUDA-12-Wheels
# CTranslate2 muss die .so-Dateien finden — Loader-Pfad setzen:
export LD_LIBRARY_PATH=$(python -c "import os,nvidia.cublas.lib,nvidia.cudnn.lib;print(os.path.dirname(nvidia.cublas.lib.__file__)+':'+os.path.dirname(nvidia.cudnn.lib.__file__))")
```

**B — System-CUDA:** CUDA-12-Toolkit + cuDNN 9 aus den NVIDIA-Repos installieren
(systemweit, dann entfällt das `LD_LIBRARY_PATH`-Setzen).

**C — GPU-Docker (reproduzierbar für den Server):** Das Profil `gpu` baut aus
`pipeline/Dockerfile.gpu` (CUDA-Basisimage, CUDA/cuDNN inklusive) und reserviert
die GPU. Braucht `nvidia-container-toolkit` auf dem Host:
```bash
docker compose --profile gpu build
docker compose --profile gpu run --rm pipeline-gpu extrahieren /input/mein_modul
```

Das Gerät lässt sich mit `LERNPAKET_ASR_DEVICE=cpu|cuda|auto` (Default `auto`)
fest vorgeben. Häufigste Fehlerquelle bei „cannot be loaded": eine cuDNN-**8**-
statt **9**-Version — das `gpu`-Extra pinnt bereits cuDNN 9.

<details><summary>Alternative ohne uv: klassisch mit pip</summary>

```bash
cd pipeline
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,asr,ocr,folien]'
```

Dasselbe Ergebnis, aber ohne gepinnte Versionen aus `uv.lock`.
</details>

### Ausführung

Mit uv ohne venv-Aktivierung über `uv run`:

```bash
uv run lernpaket extrahieren pfad/zum/modul                     # Schritt 1: Material
uv run lernpaket generieren pfad/zum/modul --ziel ../lernpakete # Schritt 2: KI
```

(Mit dem pip-Weg stattdessen `.venv/bin/lernpaket …`.)

**Schritt 1 — Extrahieren** liest alle Materialien ein (Studienbrief-PDF,
Vorlesungsvideos per Whisper-Transkription, Scan-Seiten per OCR, Folien) und
schreibt das Ergebnis nach `<modul>/extraktion/`. Er läuft ohne LLM, nutzt
automatisch alle installierten Werkzeuge (Abwahl per `--ohne-asr`/`--ohne-ocr`/
`--ohne-folien`) und cacht Transkripte pro Video — nur der erste Lauf ist teuer.
Die erste Zeile der Ausgabe zeigt, was aktiv ist: `Werkzeuge: ASR ✓ · OCR ✓ ·
Folien ✓`.

Danach meldet der Lauf den Fortschritt laufend nach stderr (mit Zeitstempeln),
z. B. `Transkribiere (ASR): KonzMod_07.mkv (193 MB) …` / `Transkript fertig: …
412 Segmente in 1870 s`; `--quiet` schaltet die Logs ab. Im Terminal zeigen die
langen Schritte zusätzlich einen Fortschrittsbalken — ASR nach Audiosekunden,
das PDF-Lesen/OCR nach Seiten und die Folien-Szenenerkennung nach Frames. Bei
nicht-interaktiver Ausgabe (Docker, Logdatei) schalten sich die Balken
automatisch ab, die Logs bleiben.

> **Lange ASR-Läufe wach halten (macOS):** Die Transkription mehrerer
> Vorlesungen kann Stunden dauern und pausiert, sobald der Mac schläft. Mit
> `caffeinate` bleibt er wach, bis der Lauf endet:
>
> ```bash
> caffeinate -i -s uv run lernpaket extrahieren pfad/zum/modul
> ```
>
> Läuft die Extraktion schon, koppel `caffeinate` an ihre Prozess-ID (endet dann
> von selbst): `caffeinate -i -s -w $(pgrep -f "lernpaket extrahieren") &`. Der
> Transkript-Cache schützt bei Abbruch — schon fertige Videos werden nicht neu
> transkribiert, ein Neustart macht nur den Rest.

**Schritt 2 — Generieren** baut daraus das Lernpaket (Themen, Lehrblöcke,
Quizfragen). Nur hier läuft das LLM — verschiedene Anbieter/Modelle lassen sich
ausprobieren, ohne neu zu extrahieren. `lernpaket pfad/zum/modul` (ohne
Unterkommando) führt weiterhin beides in einem Durchlauf aus.

Das Modulverzeichnis braucht die Pflichtquellen (`studienbrief*.pdf`, Videos als
`*.mp4`/`*.mkv`/…); `altklausuren/` und `uebungen/` sind Optionalquellen.

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
uv run lernpaket generieren pfad/zum/modul --llm gemini
LERNPAKET_LLM=ollama LERNPAKET_LLM_MODELL=qwen3 uv run lernpaket generieren pfad/zum/modul
```

Ohne explizite Wahl werden `anthropic`/`gemini` anhand vorhandener Schlüssel
auto-erkannt; `copilot` und `ollama` müssen explizit gewählt werden. Jedes
Artefakt trägt Belege; ein Verifikationsdurchlauf prüft Antworten gegen die
Quelle (ADR 0003).

## Aufbereitung per Docker (Server-Betrieb)

Docker ist eine **zusätzliche** Option für den Server-Betrieb — die lokale
Installation oben (uv bzw. pip) bleibt davon unberührt und ist für die tägliche
Arbeit weiterhin der einfachste Weg.

Alle Abhängigkeiten — Python-Pakete inklusive aller Extras sowie die OCR-Engine
tesseract (mit deutschen Sprachdaten) — stecken im Image (`pipeline/Dockerfile`);
auf dem Server ist nur Docker nötig. Der Build nutzt `uv sync --frozen` mit der
`uv.lock`, installiert also exakt dieselben Versionen wie lokal. Materialien und
Ergebnis sind Volumes (`./input` → `/input`, `./lernpakete` → `/lernpakete`), die
Whisper-Modelle (~3 GB) überleben in einem benannten Volume.

```bash
docker compose build
docker compose run --rm pipeline extrahieren /input/mein_modul
docker compose run --rm pipeline generieren /input/mein_modul \
    --ziel /lernpakete --llm gemini
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
cd pipeline && uv run pytest   # Verträge der Aufbereitung
cd player && npx vitest run    # Player-Verhalten an Fixtures
```
