# Offene Punkte für die Bauphase

Bewusst noch nicht entschiedene Design-/Implementierungsfragen. Keine Features (die liegen in `BACKLOG.md`), sondern Entscheidungen, die beim Bau fallen müssen.

> **Stand Bauphase (Juli 2026): alle drei Punkte sind entschieden.**
> 1. SRS-Algorithmus → fensteradaptive Eigenlogik, **ADR 0006**.
> 2. Embedding-/Retrieval-Setup → BM25 über die Aufbereitungs-Chunks, **ADR 0007**.
> 3. Datei-Vertrags-Struktur → **docs/DATEI-VERTRAG.md**.
>
> Die ursprünglichen Fragestellungen bleiben unten als Kontext stehen.

## 1. Spaced-Repetition-Algorithmus im Wiederholungsplan

Welcher Algorithmus steuert das verteilte Wiederholen pro Modul (siehe Glossar **Wiederholungsplan**)? Kandidaten: SM-2 (klassisch, Anki) oder FSRS (modern, datengetrieben). Besonderheit hier: Das Fenster ist sehr kurz (3 Tage bis 2 Wochen), die meisten SRS-Verfahren sind auf Wochen/Monate ausgelegt — der Scheduler muss auf komprimierten Zeitskalen sinnvoll arbeiten und bei 3 Tagen in Triage kippen. Zu klären: Standardverfahren übernehmen oder eine schlanke, fenstergerechte Eigenlogik.

## 2. Embedding-/Retrieval-Setup für den Tutormodus

Womit wird der Retrieval-Index für den **Tutormodus** gebaut? Offen: welches Embedding-Modell (lokal vs. remote — fällt laut ADR 0004 in die Vorverarbeitungs-Klasse, darf also lokal sein), welcher Vektor-Index (z. B. sqlite-vec/FAISS/LanceDB — sqlite-vec würde zur SQLite-Entscheidung aus ADR 0005 passen), und ob die Chunks aus der Aufbereitung 1:1 wiederverwendet werden. Bezug: ADR 0004 (Werkzeug-Kategorie), Glossar **Tutormodus**.

## 3. Datei-Vertrags-Struktur zwischen Pipeline und Player

Das konkrete Schema der Datei-Grenze aus ADR 0005: Wie liegen Themenkatalog, Lehrblöcke, Quizfragen, Belege und der Retrieval-Index als Dateien vor, und was gehört in die SQLite-DB (Fortschritt/Wiederholungsstand) vs. in statische Dateien (generierter Inhalt)? Bezug: ADR 0005, Glossar **Lernpaket**, **Player**, **Beleg**.
