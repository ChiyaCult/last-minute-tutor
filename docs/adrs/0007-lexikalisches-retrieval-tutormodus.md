# Lexikalisches Retrieval (BM25) über die Aufbereitungs-Chunks im Tutormodus

Löst offenen Punkt Nr. 2. Der Tutormodus erdet seine Antworten per **BM25** über
die Chunks aus `chunks.jsonl` — dieselben Chunks, die die Generierung gesehen hat,
1:1 wiederverwendet. Kein Embedding-Modell, kein Vektor-Index.

## Begründung

- Die Chunks tragen bereits Quellpositionen (Seite/Minute/Folie); jeder
  Retrieval-Treffer ist damit automatisch ein **Beleg** (ADR 0003).
- Der Korpus ist winzig (ein Modul, wenige hundert Chunks) und die Anfragen sind
  terminologienah (der Nutzer fragt mit dem Kurs-Vokabular, das er gerade liest).
  Genau dort ist lexikalisches Retrieval stark; der Mehrwert semantischer
  Embeddings ist klein, die Kosten (Modell-Download, Index-Bau in der Pipeline,
  sqlite-vec/FAISS-Abhängigkeit) nicht.
- BM25 läuft im Node-Backend in ~50 Zeilen ohne Abhängigkeit — offline, kostenlos,
  deterministisch testbar (passt zur Kern-Anforderung "offline nutzbar").

## Considered Options

Verworfen (vorerst): **sqlite-vec/FAISS/LanceDB mit lokalen Embeddings**. Bleibt
der benannte Aufrüstpfad, falls BM25 bei einem Modul sichtbar danebengreift: Die
Naht ist `erstelleIndex(chunks)` in `player/server/bm25.js`; ein Embedding-Index
kann sie füllen, ohne den Tutor zu ändern. Die Chunk-Wiederverwendung (1:1 aus der
Aufbereitung) gilt unabhängig von der Index-Technik.

## Consequences

`chunks.jsonl` ist Teil des Datei-Vertrags (docs/DATEI-VERTRAG.md) und die
gemeinsame Wahrheit für Generierung, Verifikation und Tutormodus-Erdung.
