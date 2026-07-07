#!/usr/bin/env bash
#
# Erstellt PRD-Eltern-Issue + 13 Slice-Issues für last-minute-tutor.
# Voraussetzung: in das Repo wechseln und `gh auth status` muss OK sein.
#   cd /Users/chiya/Claude/Projects/last-minute-tutor
#   bash create-github-issues.sh
#
set -euo pipefail

# --- Label (idempotent) ---
gh label create ready-for-agent --color FBCA04 \
  --description "Bereit für autonome Bearbeitung" 2>/dev/null || true

echo "Erstelle PRD-Eltern-Issue ..."
PRD=$(gh issue create --label ready-for-agent \
  --title "PRD: Klausur-Lernpaket-Generator" \
  --body "$(cat <<'EOF'
Wiederverwendbares Werkzeug, das pro Modul einmalig offline ein **Lernpaket** erzeugt (**Aufbereitung**) und es über einen lokalen **Player** in der **Lernphase** adaptiv beibringt und abfragt. Vokabular: CONTEXT.md. Entscheidungen: ADR 0001–0005. Offene Bauentscheidungen: docs/OFFENE-PUNKTE.md. Vollständige PRD: docs/PRD.md.

Dieses Issue ist das Eltern-Issue der 13 Umsetzungs-Slices.
EOF
)")
echo "  -> $PRD"

mk () { # mk "<title>" "<body>"  -> echo URL
  gh issue create --label ready-for-agent --title "$1" --body "$2"
}

echo "1/13 Durchstich ..."
S1=$(mk "1 · Durchstich: Minimal-Pipeline → Datei-Vertrag → Player" "$(cat <<EOF
**Parent:** $PRD
**Typ:** HITL — legt das Lernpaket-Dateischema fest (offener Punkt #3, ADR 0005)
**Blocked by:** —

**Was zu bauen:** Schmaler End-to-End-Durchstich. Python-Pipeline nimmt ein text-only PDF und erzeugt ein Lernpaket (1–2 Themen, je ein paar Quizfragen mit Beleg-Feld) als Dateien nach einem hier festzulegenden Schema. JS/Node-Player lädt die Dateien, zeigt ein Diagnosequiz, nimmt Antworten. Etabliert Datei-Vertrag, Pipeline-/Player-Skelett und Test-Harness.

**Akzeptanzkriterien:**
- [ ] Pipeline erzeugt aus einem Beispiel-PDF deterministisch die Lernpaket-Dateien; das Schema ist dokumentiert.
- [ ] Jede Quizfrage trägt ein Beleg-Feld (Inhalt darf zunächst leer sein).
- [ ] Player lädt eine Fixture, zeigt das Diagnosequiz, erfasst eine Antwort.
- [ ] Test-Harness läuft für Pipeline und Player getrennt.
EOF
)")
echo "  -> $S1"

echo "2/13 Audio → Transkript ..."
S2=$(mk "2 · Vorlesungs-Audio → Transkript → Themenkatalog" "$(cat <<EOF
**Parent:** $PRD
**Typ:** AFK
**Blocked by:** $S1

**Was zu bauen:** MP4-Audio via Whisper-Familie (faster-whisper/WhisperX) transkribieren; Inhalt fließt in den Themenkatalog.

**Akzeptanzkriterien:**
- [ ] MP4-Audio wird mit Zeitstempeln transkribiert.
- [ ] Transkriptinhalt erzeugt/ergänzt Themen im Themenkatalog.
- [ ] Player zeigt aus Audio gewonnene Themen.
EOF
)")
echo "  -> $S2"

echo "3/13 Relevanzsignal ..."
S3=$(mk "3 · Relevanzsignal aus Transkript" "$(cat <<EOF
**Parent:** $PRD
**Typ:** AFK
**Blocked by:** $S2

**Was zu bauen:** Mündliche Relevanzmarker ("das ist klausurrelevant") aus dem Transkript extrahieren und damit den Themenkatalog gewichten/filtern.

**Akzeptanzkriterien:**
- [ ] Relevanzmarker werden aus dem Transkript erkannt.
- [ ] Themen werden entsprechend gewichtet/gefiltert.
- [ ] Test: Transkript mit Markern priorisiert die markierten Themen.
EOF
)")
echo "  -> $S3"

echo "4/13 Zielformat ..."
S4=$(mk "4 · Zielformat erkennen-dann-bestätigen + format-parametrisches Quiz" "$(cat <<EOF
**Parent:** $PRD
**Typ:** AFK
**Blocked by:** $S1

**Was zu bauen:** Zielformat aus dem stärksten Relevanzsignal vorschlagen, im Player bestätigen/korrigieren, Quiz im bestätigten Format erzeugen.

**Akzeptanzkriterien:**
- [ ] Tool schlägt pro Modul ein Zielformat vor.
- [ ] Player erlaubt Bestätigen oder Korrigieren.
- [ ] Quizfragen werden parametrisch im Format erzeugt (MC, Rechnen, Freitext, Beweis).
EOF
)")
echo "  -> $S4"

echo "5/13 Treue ..."
S5=$(mk "5 · Treue: Verifikationsdurchlauf + Materiallücke" "$(cat <<EOF
**Parent:** $PRD
**Typ:** AFK (ADR 0003)
**Blocked by:** $S1

**Was zu bauen:** Zweiter Verifikationsdurchlauf gegen die Quelle; Materiallücke markieren statt erfinden; Belege im Player anzeigen.

**Akzeptanzkriterien:**
- [ ] Verifikation prüft Quizantworten und Numerisches/Formelhaftes gegen die Quelle und markiert Abweichungen.
- [ ] Schweigt/widerspricht das Material, entsteht eine Materiallücke statt erfundenem Inhalt.
- [ ] Player zeigt Belege und Materiallücken an.
EOF
)")
echo "  -> $S5"

echo "6/13 Adaptive Lehrtiefe ..."
S6=$(mk "6 · Adaptive Lehrtiefe: Diagnose → Lücke → Freischaltung" "$(cat <<EOF
**Parent:** $PRD
**Typ:** AFK
**Blocked by:** $S1

**Was zu bauen:** Aus dem Diagnosequiz Lücken bestimmen und gezielt Lehrblöcke freischalten; Beherrschtes nur auffrischen.

**Akzeptanzkriterien:**
- [ ] Lücken werden aus den Diagnose-Antworten korrekt bestimmt.
- [ ] Nur für Lücken wird Lehrtiefe freigeschaltet.
- [ ] Test gegen Fixture: korrekte Freischalt-Entscheidung je Antwortmuster.
EOF
)")
echo "  -> $S6"

echo "7/13 Wiederholungsplan ..."
S7=$(mk "7 · Wiederholungsplan + Fortschritts-Persistenz" "$(cat <<EOF
**Parent:** $PRD
**Typ:** HITL — SRS-Algorithmus offen (offener Punkt #1)
**Blocked by:** $S6

**Was zu bauen:** Themen pro Modul über die verfügbaren Tage verteilen (fensteradaptiv), Fortschritt in SQLite persistieren.

**Akzeptanzkriterien:**
- [ ] Verteilung kippt bei 3 Tagen in Triage, bei 2 Wochen in echtes Spacing.
- [ ] Schwache Themen kommen gezielt mehrfach zurück.
- [ ] Fortschritt persistiert über simulierte Sessions (SQLite).
EOF
)")
echo "  -> $S7"

echo "8/13 Formel-/Diagramm-Extraktion ..."
S8=$(mk "8 · Formel-/Diagramm-/Code-Extraktion (PDF) + Rendering" "$(cat <<EOF
**Parent:** $PRD
**Typ:** AFK (ADR 0004)
**Blocked by:** $S1

**Was zu bauen:** Formel→LaTeX, Tabellen und Code via Marker/MinerU erfassen; Player rendert Formeln via KaTeX.

**Akzeptanzkriterien:**
- [ ] Formeln werden als LaTeX, Tabellen strukturiert erfasst.
- [ ] Player rendert Formeln korrekt.
- [ ] Test an einem kleinen formelhaltigen Fixture.
EOF
)")
echo "  -> $S8"

echo "9/13 Folien aus Video ..."
S9=$(mk "9 · Folien aus Video → Extraktion" "$(cat <<EOF
**Parent:** $PRD
**Typ:** AFK
**Blocked by:** $S2, $S8

**Was zu bauen:** Folienwechsel via PySceneDetect erkennen, Duplikate entfernen, eindeutige Folien durch dieselbe Extraktion schicken.

**Akzeptanzkriterien:**
- [ ] Folienwechsel werden erkannt, Duplikate verworfen.
- [ ] Eindeutige Folien laufen durch die Extraktion.
- [ ] Auf Folien gezeigte Formeln erscheinen im Lernpaket.
EOF
)")
echo "  -> $S9"

echo "10/13 Scan-Fallback ..."
S10=$(mk "10 · Scan-Fallback (Bild-PDF → OCR)" "$(cat <<EOF
**Parent:** $PRD
**Typ:** AFK
**Blocked by:** $S8

**Was zu bauen:** Erkennungsschritt Textebene-vs-Scan; bei reinem Scan Volltext-OCR der Seiten.

**Akzeptanzkriterien:**
- [ ] Textebene vs. Scan wird zuverlässig unterschieden.
- [ ] Bei Scan läuft Volltext-OCR.
- [ ] Test: Scan-PDF ohne Textebene liefert verwertbaren Text.
EOF
)")
echo "  -> $S10"

echo "11/13 Optionalquellen ..."
S11=$(mk "11 · Optionalquellen + graceful degradation" "$(cat <<EOF
**Parent:** $PRD
**Typ:** AFK (ADR 0001)
**Blocked by:** $S3

**Was zu bauen:** Altklausuren/Extra-Übungs-PDFs als Relevanzsignal aufnehmen, wenn vorhanden; ohne sie läuft die Pipeline durch.

**Akzeptanzkriterien:**
- [ ] Optionalquellen stärken das Relevanzsignal, wenn vorhanden.
- [ ] Ohne sie erzeugt die Pipeline ein valides Lernpaket (höhere Unsicherheit).
- [ ] Test: gleicher Modul-Input mit/ohne Optionalquellen liefert beide Male ein valides Lernpaket.
EOF
)")
echo "  -> $S11"

echo "12/13 Tutormodus ..."
S12=$(mk "12 · Tutormodus: geerdetes Live-Q&A + Nachgenerieren" "$(cat <<EOF
**Parent:** $PRD
**Typ:** HITL — Embedding-/Index-Setup offen (offener Punkt #2, ADR 0002/0003)
**Blocked by:** $S1, $S8

**Was zu bauen:** Player-Backend proxyt Remote-LLM-Calls (API-Schlüssel nur lokal), Antworten geerdet via Retrieval mit Belegen, freie Rückfragen und Nachgenerieren von Lehrinhalt.

**Akzeptanzkriterien:**
- [ ] Backend proxyt den Call; der Schlüssel landet nie im Frontend.
- [ ] Antworten sind in den Modulmaterialien geerdet und tragen Belege.
- [ ] Nutzer kann freie Rückfragen stellen und zusätzlichen Lehrinhalt nachgenerieren.
EOF
)")
echo "  -> $S12"

echo "13/13 Mehr-Modul-Unabhängigkeit ..."
S13=$(mk "13 · Mehr-Modul-Unabhängigkeit + Modulauswahl" "$(cat <<EOF
**Parent:** $PRD
**Typ:** AFK
**Blocked by:** $S1

**Was zu bauen:** Pipeline pro Modul unabhängig; Player verwaltet 2–3 unabhängige Lernpakete mit Modulauswahl.

**Akzeptanzkriterien:**
- [ ] Pipeline läuft je Modul unabhängig.
- [ ] Player verwaltet 2–3 Lernpakete mit Modulauswahl.
- [ ] Fortschritt wird je Modul getrennt gehalten.
EOF
)")
echo "  -> $S13"

echo
echo "Fertig. Eltern-Issue: $PRD"
