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
| `marker` | marker-pdf (+ surya, torch)     | Formeln/Matrizen/Tabellen aus PDFs |

**Zwei Dinge liegen außerhalb von Pythons Reichweite** (C++-Programme, keine
pip-Pakete, also von keinem Python-Werkzeug installierbar):

Für `ocr`/`folien` die OCR-Engine **tesseract** samt deutschen Sprachdaten:

```bash
brew install tesseract tesseract-lang     # macOS
# Debian/Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-deu
```

Für `marker` das **llama.cpp**-Binary — marker-pdf 2.x rechnet seine Formel- und
Texterkennung über surya, das dafür einen lokalen `llama-server` startet:

```bash
brew install llama.cpp                    # macOS und Linux
```

Kein poppler, kein ffmpeg nötig — die bringt uv/pip mit. Ohne die Extras
(`uv sync`) läuft die reine PDF-Text-Pipeline ganz ohne System-Werkzeuge.

### Formelerfassung: warum `marker` den Unterschied macht

Aus der PDF-Textebene allein lässt sich Mathematik nicht rekonstruieren: eine
Matrix kommt dort spaltenweise zerrissen an, ein Bruch `1/x` als zwei Zeilen
`1` und `x`. Der Dokument-Parser Marker sieht dagegen die **gerenderte Seite**
und liefert echtes LaTeX (`$$x_r = -a(N)_{r,(r+1)}x_{r+1} + \dots$$`), das der
Player mit KaTeX darstellt. Er braucht **Python 3.10–3.13** (nicht 3.9, nicht
3.14) und lädt beim ersten Lauf einige GB Modelle nach `~/.cache`.

Ist das Extra nicht installiert, läuft die Pipeline weiter: sie fällt je Seite
auf eine deterministische Heuristik zurück, die Formelzeilen als LaTeX markiert
— deutlich schwächer, aber ohne ML-Abhängigkeit. Dasselbe passiert, wenn Marker
zur Laufzeit scheitert (z. B. fehlendes `llama-server`-Binary); der Rückfall
steht dann im Log.

Bei **Foliensätzen** ist Marker keine Kür, sondern Bedingung: Folien setzen die
Negation als Überstrich, den die PDF-Textebene überhaupt nicht kennt. Aus
`(a ∙ b) = a + b` (De Morgan) wird ohne Parser eine mathematisch falsche
Aussage — unauffällig falsch, also gefährlich. Deshalb bricht die Aufbereitung
für erkannte Foliensätze ohne Parser ab, statt zu degradieren.

Auch mit Marker bleibt ein Rest: In locker gesetzten Regeltabellen verliert er
einzelne Überstriche (gemessen an `REST_4.2_Bool_Algebra`: 21 korrekt, 8
verloren). Solche Reste sind am verwaisten `\_` erkennbar und landen als
**Materiallücke** im Paket — nachsehen lohnt dort im Original.

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

Den Rechentyp wählt die Pipeline selbst, sofern `LERNPAKET_ASR_COMPUTE` nichts
vorgibt: auf GPU `auto` (CTranslate2 nimmt float16), auf CPU **`int8`**. Das ist
kein Detail — mit `auto` quantisiert CTranslate2 large-v3 beim Laden um und
braucht dafür auf Apple Silicon über eine Viertelstunde, ohne Fehlermeldung;
mit `int8` sind es rund drei Sekunden.

### ASR über Nacht laufen lassen

Transkription ist der mit Abstand teuerste Schritt. Anhaltspunkt von einem
vollständigen Lauf auf einem Apple M3 (CPU, large-v3, int8): **~10 h Audio in
gut 9 Stunden**, also grob Echtzeit. Ein Semester passt damit in eine Nacht,
zwei Semester nicht — rechne es vorher aus.

Miss nicht an kurzen Schnipseln: eine 5-Minuten-Probe ergab hier 0,38× und damit
eine mehr als doppelt so pessimistische Schätzung, weil bei kurzen Stücken das
Aufwärmen des Modells durchschlägt.

**Der Rechner darf dabei nicht schlafen.** Die Pipeline unterdrückt das nicht
selbst (das wäre plattformspezifisch und überraschend) — stell es dem Aufruf
voran:

```bash
# macOS: -i verhindert Idle-Sleep, -s System-Sleep am Netzteil
caffeinate -is lernpaket extrahieren ../input/mein_modul 2>&1 | tee ~/extraktion.log
# Linux: systemd-inhibit --what=idle:sleep lernpaket extrahieren …
```

Zwei Fallstricke dabei: im **Akkubetrieb** schläft macOS trotz `caffeinate`, also
Netzteil anschließen; und bei **zugeklapptem Deckel** schläft das Gerät ohne
externen Monitor ebenfalls.

**Abbrechen ist billig.** Ein erneuter Lauf wertet nur aus, was neu ist:

| Cache | Ort | Schlüssel |
| ----- | --- | --------- |
| Transkripte | `<modul>/extraktion/transkripte/` | Dateiname + Größe |
| Parser-Ergebnis je PDF | `<modul>/extraktion/dokumente/` | Dateiname + Größe + Parser |
| LLM-Antworten der Generierung | `<modul>/extraktion/generierung/` | Modell + Prompt (also auch das Material) |

Du kannst die Arbeit also über mehrere Nächte verteilen. Noch **nicht** gecacht
ist die Folien-Extraktion — die läuft bei jedem Lauf über jedes Video erneut.

Wenn du nur den Studienbrief brauchst, spart `--ohne-asr --ohne-folien` die
gesamte Videoauswertung.

### Semesterbegleitend statt alles am Ende

Der Ablauf ist darauf ausgelegt, mehrfach über dasselbe Modul zu laufen: neue
Vorlesungen in `vorlesungen/` legen, Pipeline erneut starten. Dank der Caches
kostet das nur die neu hinzugekommenen Videos, der Studienbrief wird nicht noch
einmal geparst. Das Ergebnis in `extraktion/` wird dabei jedes Mal vollständig
neu geschrieben — Chunk-IDs verschieben sich, ein zuvor erzeugtes Lernpaket
solltest du danach also neu generieren.

Zwei Fallstricke:

**Nur ein Lauf je Modul gleichzeitig.** Ein zweiter Start bricht mit
„Modul … wird bereits aufbereitet" und Exit-Code 2 ab, statt dem ersten das
Ergebnis zu überschreiben und sich mit ihm die CPU zu teilen. Die Sperre liegt
unter `<modul>/extraktion/.lock` und trägt die PID; stürzt ein Lauf ab, erkennt
der nächste sie als verwaist und übernimmt.

**Doppelte Downloads.** Lädst du Videos über den Browser, entstehen leicht
`vorlesung(1).mp4`-Kopien. Die zählen als eigene Datei — sie werden ein zweites
Mal transkribiert und gewichten ihr Thema doppelt. Vor dem Lauf prüfen:

```bash
# listet inhaltsgleiche Dateien (uniq -w gibt es auf macOS nicht)
shasum -a 256 vorlesungen/*.mp4 \
  | awk '{n[$1]++; f[$1]=f[$1]"\n  "$2} END{for(h in n) if(n[h]>1) print "doppelt:"f[h]}'
```

<details><summary>Alternative ohne uv: klassisch mit pip</summary>

```bash
cd pipeline
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,asr,ocr,folien]'
```

Dasselbe Ergebnis, aber ohne gepinnte Versionen aus `uv.lock`.
</details>

<details><summary>Harmlose Warnung: „Class AVFFrameReceiver is implemented in both …"</summary>

Auf macOS meldet jeder Lauf mit den Extras `asr` und `folien`:

```
objc[…]: Class AVFFrameReceiver is implemented in both …/cv2/.dylibs/libavdevice.61…
         and …/av/.dylibs/libavdevice.62… This may cause spurious casting failures
         and mysterious crashes.
```

Ursache: `opencv-python` (für `folien`) und `av` (Abhängigkeit von faster-whisper)
bringen je ein eigenes ffmpeg mit — hier in den Generationen 61 und 62. Beide
registrieren dieselben Objective-C-Klassen aus `libavdevice`.

Folgenlos, weil `libavdevice` die *Aufnahmegeräte* bereitstellt (Kamera,
Bildschirm). Die Pipeline nimmt nichts auf, sie liest Dateien — das erledigen
`libavformat`/`libavcodec`. Die doppelt registrierten Klassen werden nie
instanziiert.

Der naheliegende Ausweg funktioniert **nicht**: `opencv-python-headless` bündelt
dasselbe `libavdevice`, und `scenedetect` führt `opencv-python` ohnehin als harte
Abhängigkeit — beide Varianten nebeneinander liefern dasselbe `cv2`-Modul und
überschreiben sich. Die Warnung bleibt also am besten stehen.
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

### Modulverzeichnis: Struktur & Benennung

Die Quellen werden **per Konvention** erkannt (`finde_quellen`). Empfohlen ist
**ein Ordner je Kategorie** — dieses Schema überlebt Umbenennungen der PDFs und
eine andere Aufteilung des Stoffs auf mehrere Dateien:

```
Mathe_2a/                           ← Ordnername wird zu Titel & modul-id
  studienbrief/                     ← Pflicht; Dateinamen beliebig
    MAT2a_Studienbrief_OHNE_Lösungen-1.pdf
  vorlesungen/
    fau-itsec-mathe2a-260416-sb01-lgs.mp4
    fau-itsec-mathe2a-260430-sb02-funktionen.mp4
  übungen/                          ← optional
    HOCHLADEN_Lösungen_zu_den_Übungen_Kapitel_1.pdf
    HOCHLADEN_Lösungen_zu_den_Übungen_Kapitel_2.pdf
  altklausuren/                     ← optional
    ws2018.pdf
```

Die Regeln im Detail:

| Quelle | Erkennung | Dateitypen |
| ------ | --------- | ---------- |
| **Studienbrief** (Pflicht) | **Alle** PDFs im Ordner `studienbrief/` (bzw. `studienbriefe/`). Ohne diesen Ordner: `studienbrief*.pdf` auf oberster Ebene, sonst als Fallback das **größte** übrige PDF oben. Fehlt jedes PDF → Abbruch. | `.pdf` |
| **Vorlesungen** | Videodateien im Ordner `vorlesungen/` **oder** auf oberster Ebene. Fehlen sie, läuft die Aufbereitung weiter (als Materiallücke vermerkt). | `.mp4` `.mkv` `.webm` `.mov` `.m4v` `.avi` |
| **Altklausuren** (optional) | PDFs im Ordner `altklausuren/` **oder** oberste-Ebene-PDFs, deren Name mit `altklausur` beginnt. | `.pdf` |
| **Übungen** (optional) | PDFs im Ordner `uebungen/`/`übungen/` **oder** oberste-Ebene-PDFs, deren Name mit `uebung`/`übung` beginnt. | `.pdf` |

Weitere Annahmen:

- **Mehrere PDFs je Kategorie** sind ausdrücklich erlaubt — auch beim Studienbrief (z. B. ein Heft je Kapitel). Sobald eine Kategorie aus mehr als einer Datei besteht, tragen die Belege den Dateinamen mit (`teil_b, S. 12` statt bloß `S. 12`), damit Seitenangaben eindeutig bleiben.
- **Groß-/Kleinschreibung** der Unterordner ist egal (`Vorlesungen/`, `ALTKLAUSUREN/` … werden erkannt); die Ordnernamen selbst müssen aber genau `studienbrief` / `vorlesungen` / `altklausuren` / `uebungen` (bzw. `übungen`) lauten. Umlaute werden Unicode-normalisiert verglichen, ein von macOS zerlegt abgelegtes `übungen/` (NFD) wird also gefunden.
- **Reihenfolge der PDF-Zuordnung:** Ein oberste-Ebene-PDF wird zuerst auf die Präfixe `altklausur…`/`uebung…` geprüft; erst die restlichen PDFs kommen als Studienbrief infrage. Benenne den Studienbrief also **nicht** mit diesen Präfixen. Mit `studienbrief/`-Ordner entfällt diese Stolperfalle.
- **modul-id & Titel** werden aus dem Ordnernamen abgeleitet (id: kleingeschrieben, Leerzeichen → `-`). Überschreibbar per `--modul-id` / `--titel`.
- **Scan-PDFs** ohne Textebene werden per OCR gelesen (Extra `ocr`). **Verklebter Text** ohne Leerzeichen (bei vielen Studienbriefen die halbe Datei) wird zweistufig repariert: erst über pdfminer (Wortgrenzen aus Glyphen-Abständen), dann für hartnäckige Reste (meist Diagramm-Beschriftungen) per OCR der gerenderten Seite. Was danach noch klebt, wird als Materiallücke vermerkt.
- **Dokumentart des Studienbriefs** wird je PDF erkannt (ADR 0008): **Prosa** (dichtes
  Heft, Gliederung über nummerierte Überschriften) oder **Foliensatz** (Querformat und
  wenig Text je Seite — Gliederung über Kapitel der Titelfolie und Folien-Kopfzeilen,
  jede Folie wird als Abbildung gerendert). Ein Modul darf beides mischen. Die erkannte
  Art steht im Manifest (`quellen[].dokumentart`) und lässt sich mit
  `--dokumentart prosa|folien` erzwingen. **Foliensätze brauchen zwingend das Extra
  `marker`** — ohne es bricht die Aufbereitung ab, statt Formeln lautlos falsch zu
  übernehmen (s. u.). Bei Foliensätzen **benennt zusätzlich das LLM die Themen**
  (ein gebündelter Aufruf im Generierungsschritt): Die Folien-Kopfzeile trägt bei
  einem Teil der Folien Tabellen- oder Formelreste statt eines Namens. Ohne
  LLM-Anbindung bleiben die Kopfzeilen stehen. Der Prosa-Pfad wird nie umbenannt —
  dort sind die Titel echte Kapitelüberschriften.
- **Diagramme** (Struktur/Verbindungen) erfasst die Textextraktion nicht — eingebettete Abbildungen werden als Materiallücke markiert; ihre *Text*-Beschriftungen holt die OCR-Stufe teilweise mit ab.
- Schritt 1 legt sein Zwischenergebnis unter `<modul>/extraktion/` ab — das Modulverzeichnis muss also **beschreibbar** sein.

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

**Wenn der Anbieter aussetzt**, bricht der Generierungsschritt mit Exit-Code 3 ab,
statt heimlich auf die Heuristik zurückzufallen — ein heruntergestuftes Paket sieht
später aus wie ein vollwertiges, und das merkst du erst beim Lernen. Jede Anfrage
wird zuvor bis zu sechsmal wiederholt (Backoff bis 64 s), und **jede beantwortete
Anfrage landet im Cache**: Derselbe Aufruf später wiederholt kostet nur die noch
fehlenden Themen. Ändert sich das Material, ändert sich der Prompt und der Cache
greift bewusst nicht mehr. Ein *dauerhafter* Fehler bei einem einzelnen Thema
(z. B. Anfrage zu groß) stoppt den Lauf nicht: Das Thema wird als Materiallücke
vermerkt und bleibt ohne Lehrblöcke — auch hier ohne heuristischen Ersatz.

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
