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

## 4. Aufbereitung: Strukturheuristik durch inhaltsgetriebene Themenbildung ersetzen

Nach mehreren vollständigen Läufen (September 2026) steht fest, dass die Themenbildung
über die Gliederung des Studienbriefs nicht über Module hinweg trägt — Befunde in
`docs/BEFUND-AUFBEREITUNG.md`. Die vorgeschlagene Antwort steht in **ADR 0009**
(Verdichtungsschicht, Redundanz als Relevanzsignal, Themen per Clustering), **ADR 0010**
(Grenze extraktiv-lokal vs. formulierend-remote) und **ADR 0011** (Embeddings als
Rechenmittel, vorberechnete Kanten im Paket). Alle drei stehen auf *Vorschlag*.

**Zu entscheiden:** ob die drei ADRs angenommen werden, und ob Stufe 3 (Aussagen-Schicht,
Issue 17) nötig ist oder Dedup allein reicht. Beides hängt an den Messwerten aus
Issue 14 — vorher ist die Frage nicht beantwortbar.
