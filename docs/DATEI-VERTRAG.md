# Datei-Vertrag: Lernpaket zwischen Pipeline und Player

Löst offenen Punkt Nr. 3 (siehe `OFFENE-PUNKTE.md`). Die Pipeline schreibt pro Modul ein
Lernpaket-Verzeichnis; der Player liest es nur. Fortschritt/Wiederholungsstand liegen NIE im
Lernpaket, sondern in der Player-eigenen SQLite-DB (`player/daten/fortschritt.db`).

## Verzeichnis-Layout

```
lernpakete/
  <modul-id>/                 # z. B. "algorithmen-und-datenstrukturen"
    manifest.json
    themen.json
    lehrbloecke.json
    quiz.json
    chunks.jsonl              # Retrieval-Grundlage für Tutormodus (eine JSON-Zeile pro Chunk)
```

Der Player scannt `lernpakete/` und bietet jedes Unterverzeichnis mit gültigem `manifest.json`
als Modul an (Mehr-Modul-Unabhängigkeit, Issue #33).

## Gemeinsame Typen

**Beleg** (ADR 0003 — Pflichtfeld an jedem Artefakt, Inhalt darf im Durchstich leer sein):

```json
{ "quelle": "studienbrief" | "vorlesung" | "altklausur" | "uebung" | "folie",
  "position": "S. 42" | "Min. 13:05" | "Folie 7",
  "chunk_id": "c-0042" }
```

`chunk_id` verweist auf `chunks.jsonl` und macht den Beleg maschinell nachprüfbar; `position`
ist die menschenlesbare Form. Felder außer `quelle` dürfen leer sein (`""`/`null`).

**Materiallücke** (markiert statt erfunden, ADR 0003):

```json
{ "thema_id": "t-03", "beschreibung": "Material widerspricht sich bei ...", "art": "schweigen" | "widerspruch" }
```

## manifest.json

```json
{
  "schema_version": 1,
  "modul_id": "beispielmodul",
  "titel": "Beispielmodul",
  "erzeugt_am": "2026-07-16T12:00:00Z",
  "quellen": [ { "art": "studienbrief", "datei": "studienbrief.pdf" } ],
  "optionalquellen_vorhanden": false,
  "relevanz_unsicherheit": "niedrig" | "hoch",
  "zielformat": { "vorschlag": "mc" | "rechnen" | "freitext" | "beweis", "begruendung": "..." },
  "materialluecken": [ Materiallücke ]
}
```

`relevanz_unsicherheit` ist `hoch`, wenn keine Optionalquellen vorlagen (Issue #31).
Das Zielformat ist nur ein *Vorschlag*; die Bestätigung/Korrektur des Nutzers lebt im Player
(Fortschritts-DB), nicht im statischen Paket (Issue #24).

## themen.json — der Themenkatalog

```json
{ "themen": [ {
    "id": "t-01",
    "titel": "Sortierverfahren",
    "beschreibung": "…",
    "relevanz": 0.0–1.0,
    "relevanzsignale": [ "transkript-marker" | "altklausur" | "uebung" | "abdeckung" ],
    "belege": [ Beleg ]
} ] }
```

`relevanz` gewichtet den Wiederholungsplan und die Quiz-Reihenfolge. `abdeckung` heißt: Thema
stammt nur aus der Studienbrief-Obermenge (kein echtes Relevanzsignal, aber Abdeckungspflicht).

## lehrbloecke.json

```json
{ "lehrbloecke": [ {
    "id": "lb-t-01-1",
    "thema_id": "t-01",
    "tiefe": "auffrischung" | "vertiefung",
    "inhalt_markdown": "… mit $LaTeX$-Formeln, Tabellen, ```code```-Blöcken …",
    "belege": [ Beleg ]
} ] }
```

`auffrischung` sieht jeder; `vertiefung` schaltet der Player nur für diagnostizierte Lücken frei
(Issue #26). Formeln stehen als `$...$`/`$$...$$` im Markdown und werden im Player mit KaTeX
gerendert (Issue #28).

## quiz.json

```json
{ "fragen": [ {
    "id": "q-t-01-mc-1",
    "thema_id": "t-01",
    "format": "mc" | "rechnen" | "freitext" | "beweis",
    "diagnose": true,
    "frage_markdown": "…",
    "optionen": ["A", "B", "C", "D"],
    "antwort": "B" | "42" | "Musterlösung …",
    "erklaerung_markdown": "…",
    "belege": [ Beleg ],
    "verifikation": { "status": "bestaetigt" | "abweichung" | "ungeprueft", "hinweis": "" }
} ] }
```

`optionen` nur bei `format: "mc"`. `diagnose: true` markiert die Teilmenge fürs Diagnosequiz.
`verifikation` ist das Ergebnis des zweiten Durchlaufs (Issue #25); der Player blendet
`abweichung`-Fragen aus und zeigt den Hinweis als Materiallücke.

## chunks.jsonl

Eine JSON-Zeile pro Chunk — dieselben Chunks, die die Generierung gesehen hat, 1:1
wiederverwendet für das Tutormodus-Retrieval (offener Punkt Nr. 2, ADR 0007):

```json
{ "id": "c-0042", "quelle": "studienbrief", "position": "S. 42", "text": "…" }
```

## Stabilität

`schema_version` wird bei inkompatiblen Änderungen erhöht; der Player lehnt unbekannte
Major-Versionen mit klarer Meldung ab. Zusätzliche Felder sind jederzeit erlaubt (Player
ignoriert Unbekanntes).
