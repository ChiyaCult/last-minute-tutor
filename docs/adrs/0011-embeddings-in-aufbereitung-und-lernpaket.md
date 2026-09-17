# Embeddings: Rechenmittel der Aufbereitung, vorberechnete Kanten im Lernpaket

> **Status: Vorschlag.** Erweitert ADR 0007 (BM25), ersetzt es nicht. Voraussetzung für
> Verschmelzung und Clustering in ADR 0009.

Drei Entscheidungen:

1. **In der Aufbereitung: ja.** Embeddings tragen Duplikaterkennung, Clustering und
   Aufgaben-Zuordnung. Einmalig, offline, batch.
2. **Als Ersatz für `chunks.jsonl`: nein.** Embeddings sind ein Index, kein Inhalt.
3. **Im Lernpaket: die vorberechneten Nachbarschaften, nicht die Vektoren.**

## Warum „statt Chunks" nicht geht

Die Frage lag nahe, weil der Katalog unhandlich groß ist. Sie löst dieses Problem aber
nicht, und sie bricht drei Zusagen:

- **Der Tutor braucht Text im Prompt.** `player/server/tutor.js` übergibt die
  Retrieval-Treffer als Quell-Chunks („Antworte NUR auf Basis der mitgelieferten
  Quell-Chunks"). Ein Vektor lässt sich nicht in einen Prompt schreiben.
- **ADR 0003 verlangt Nachprüfbarkeit.** `chunk_id` → `chunks.jsonl` ist die Kette, die
  aus einem Beleg etwas maschinell Prüfbares macht. Ohne Text ist `c-0042` ein toter
  Zeiger.
- **`verifiziere()` prüft gegen Chunk-Text.** Ohne Text kein zweiter Durchlauf.

Dazu ein Größenargument, das gegen die Intuition läuft: **Embeddings sind nicht kleiner
als der Text.** Für ~2.000 Chunks je Modul stehen ~2 MB Text gegen ~6 MB Vektoren in
float32 (~1,5 MB bei int8). Wer die Prompt-Größe senken will, braucht die
Verdichtungsschicht aus ADR 0009 — **Embeddings entscheiden, *welcher* Text in den
Prompt geht, nicht *wie wenig* Text nötig ist.**

## Die Asymmetrie, die alles entscheidet

- **Build-Zeit:** Vektor gegen Vektor. Kein Modell zur Laufzeit nötig.
- **Query-Zeit:** Die Nutzerfrage muss mit **demselben Modell** eingebettet werden. Ein
  Vektorindex ohne Query-Encoder ist wertlos.

Der Player hat heute genau eine Laufzeit-Abhängigkeit (`katex`); BM25 ist 40 Zeilen ohne
alles (`player/server/bm25.js`). Ein ONNX-Encoder (`multilingual-e5-small` int8 ≈ 120 MB
plus `transformers.js`) ist gemessen daran keine Kleinigkeit — genau das Kostenargument,
das ADR 0007 bereits geführt hat.

## Was ins Lernpaket geht: das Ergebnis, nicht die Vektoren

Es gibt eine Klasse von Nutzen, deren Anfrage zur Build-Zeit feststeht und die deshalb
**keinen Query-Encoder braucht**. Die Kanten werden in der Pipeline gerechnet und fertig
ausgeliefert:

| Kante | Nutzen im Player |
| --- | --- |
| Thema ↔ Thema | verwechselbare Themen gezielt verzahnen (ADR 0006; Grundlage für das Interleaving aus `BACKLOG.md`) |
| Frage → Lehrblock | nach falscher Diagnosefrage sofort „genau das steht hier", auch ohne Wortgleichheit |
| Lehrblock → weitere Belegstellen | „dazu sagt die Vorlesung bei Min. 21:40 noch das hier" |
| Thema → Altklausuraufgabe | ersetzt `_titel_naehe()`/`_wortnah()` (`relevanz.py:148`) — die Handregel für „Structured Query Language" vs. „Die Datenbanksprache SQL" |

Kosten: wenige KB JSON je Modul, additiv zum Vertrag, Player-Abhängigkeiten unverändert
null.

## Die freie Tutorfrage: BM25 plus Query-Expansion

Statt eines Vektorindex bekommt der Tutormodus einen vorgeschalteten LLM-Aufruf, der die
Frage in Kursvokabular umschreibt („was war nochmal das mit den Tabellen, die man nicht
weiter zerlegen kann" → „Normalisierung, erste Normalform, atomare Attributwerte"), und
*dann* läuft BM25. Das fängt genau den Fall, in dem Lexik versagt — der Nutzer kennt den
gesuchten Fachbegriff nicht — ohne ein Byte Modell im Player. Der Tutormodus ist laut
`CONTEXT.md` ohnehin „der einzige Teil des Tools mit Laufzeitkosten" und hat ein LLM zur
Hand. Die Naht ist unverändert die aus ADR 0007: `erstelleIndex(chunks)`.

## Considered Options

**Vektorindex im Player** (`transformers.js` + quantisiertes Modell): bleibt der benannte
Aufrüstpfad, falls BM25 mit Query-Expansion sichtbar danebengreift — dann aber als
bewusst bezahlter Preis, nicht nebenbei.

**Remote-Embedding-API zur Query-Zeit:** zieht Latenz in jede Tutorfrage und macht den
Tutor netzabhängig, für einen Korpus von wenigen tausend Chunks. Verworfen.

**Ausschließlich BM25, auch in der Aufbereitung:** lexikalische Ähnlichkeit erkennt keine
Dubletten, die dasselbe anders sagen — und das ist der Normalfall zwischen Folie und
gesprochener Vorlesung. Trägt die Verschmelzung aus ADR 0009 nicht.

## Consequences

`chunks.jsonl` bleibt unverändert die Wahrheit; ADR 0007 gilt weiter. Neu im Vertrag sind
`aussagen.jsonl` (ADR 0009) und `nachbarn.json` (die Kanten oben) — additiv,
`schema_version` bleibt 1.

**Falls doch je Vektoren ausgeliefert werden**, dann nur mit Metadaten, weil Embeddings
modellspezifisch und **schweigend inkompatibel** sind — ein Modellwechsel ohne
Index-Neubau liefert keine Fehlermeldung, sondern falsche Nachbarn:

```json
// vektoren.meta.json
{ "modell": "intfloat/multilingual-e5-base", "dimensionen": 768,
  "normalisiert": true, "quantisierung": "int8", "praefix": "passage: ",
  "reihenfolge": "chunks.jsonl, zeilenweise" }
```

Der `praefix` gehört zwingend dazu: E5-Modelle brauchen `query:`/`passage:`, und ohne ihn
sacken die Scores ab — wieder ohne Fehlermeldung. Vektoren gehören in eine eigene
Binärdatei, nicht in `chunks.jsonl`; die Zeilen-JSON-Datei bleibt so greppbar und
diffbar.

**Modellwahl für Deutsch:** multilingual zwingend. `intfloat/multilingual-e5-base` oder
`BAAI/bge-m3`, wahlweise über Ollamas `/api/embed` (bereits verdrahtet) oder
`sentence-transformers`. `nomic-embed-text` scheidet aus (auf Deutsch schwach). Das
gewählte Modell und seine Parameter gehören ins Manifest, aus demselben Grund wie oben.
