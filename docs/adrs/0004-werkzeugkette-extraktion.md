# Werkzeugkette der Materialextraktion

Die Aufbereitung extrahiert aus den Pflichtquellen normalisierten Inhalt, bevor das Reasoning-LLM ihn weiterverarbeitet. Die dauerhafte Entscheidung ist die **geschichtete Form** der Extraktion; die konkreten Werkzeuge sind der aktuelle Stand (Mitte 2026) und bewusst austauschbar.

## PDF (Studienbrief)

Ein fertiges Dokument-Parser-Pipeline-Tool als Rückgrat, das Textebenen-Auslesung, OCR-Fallback für reine Scans, Formel→LaTeX und Tabellen in einem Durchlauf nach Markdown leistet:

- **Marker** als Default (Swiss-Army, Surya-OCR, Formel-/Tabellenerkennung, GPU/CPU/Apple).
- **MinerU** als Alternative bei sehr formel-/wissenschaftslastigen Modulen (stärkere Layout-/Formelmodelle).
- **Mathpix** als kommerzielle High-Accuracy-Option, falls die Open-Source-Qualität bei kritischen Formeln nicht reicht.

Ein Erkennungsschritt am Anfang entscheidet Textebene-vorhanden vs. Scan; im Scan-Fall läuft die ganze Seite durch OCR.

## Video (Vorlesung)

- **Audio → Transkript:** Whisper large-v3 (deutschsprachig, MIT), betrieben über faster-whisper/WhisperX (VAD senkt Whispers bekannte Halluzination auf Stille, liefert Wort-Zeitstempel). Voxtral Transcribe 2 als genauere Alternative für die abgedeckten Sprachen.
- **Folien → Standbilder:** PySceneDetect (AdaptiveDetector) erkennt Folienwechsel, Duplikate werden entfernt; jede einzigartige Folie läuft durch dieselbe PDF-Extraktion, um Formeln/Diagramme zu lesen, die das Audio nicht enthält.

## Geltungsbereich von ADR 0002

ADR 0002 (remote-only) betrifft ausschließlich das **Reasoning-/Generierungs-LLM**. Die Vorverarbeitung hier — OCR, ASR, Scene-Detection und ggf. Embeddings — ist eine andere Werkzeugklasse, läuft einmalig und darf lokal ausgeführt werden; das ist kein Widerspruch zu ADR 0002.

## Consequences

Das Reasoning-LLM sieht nie Roh-PDF oder Roh-Audio, sondern normalisiertes Markdown plus Transkript samt Quellpositionen (Seite/Minute). Diese Positionen sind die Grundlage der **Belege** aus ADR 0003.
