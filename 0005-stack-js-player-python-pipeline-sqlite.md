# Stack: JS/Node-Player, Python-Batch-Pipeline, SQLite

Der **Player** (Frontend und sein dünnes Backend) wird in JavaScript/Node gebaut, die **Aufbereitung** als entkoppelte Python-Batch-Pipeline. Beide kommunizieren ausschließlich über eine **Datei-Grenze**: Die Pipeline erzeugt das Lernpaket als Dateien, der Player liest sie.

## Begründung

Die Pipeline *muss* Python sein — Marker/MinerU, Whisper, PySceneDetect, Pix2Text und Embedding-Modelle leben praktisch ausschließlich im Python-ML-Ökosystem (siehe ADR 0004). Der Player zur Laufzeit macht dagegen kein ML, sondern CRUD plus einen Proxy für den Tutormodus; er ist sprachfrei wählbar. Bei zwei technisch gleichwertigen Optionen gibt die **Vertrautheit des einzigen Entwicklers** den Ausschlag (JS), zumal der Player der häufig angefasste Teil ist und das Frontend ohnehin JS (KaTeX, UI). Die Pipeline bleibt eine isolierte, selten berührte Python-Insel.

## Speicher: SQLite statt MongoDB

Lokale Single-User-App, winzige Datenmenge (wenige Module × Dutzende Themen × Fortschritt). SQLite ist eingebettet, ein einzelnes File, kein Daemon — liegt neben dem Lernpaket. MongoDBs Stärken (horizontale Skalierung, verteilte Writes) sind hier irrelevant und brächten nur Betriebsaufwand. Dokument-artige Flexibilität bei Bedarf über SQLites JSON-Spalten. Gilt sprachunabhängig.

## Consequences

Polyglottes Repo (Python-Pipeline-Verzeichnis + JS-App-Verzeichnis) mit einem dateibasierten Vertrag dazwischen. Der API-Schlüssel des Tutormodus lebt nur lokal im Node-Backend und wird nie ins Frontend eingebettet.
