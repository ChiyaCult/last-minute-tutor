# Wiederverwendbare Pipeline statt Einmal-Skript

Das Tool wird für ein Fernstudium mit 20+ kommenden Modulen gebaut, nicht für eine einzelne Klausur. Es ist daher als wiederverwendbare Pipeline angelegt, die pro Modul beliebige Materiallagen verarbeitet. Garantiert vorhanden und damit voraussetzbar sind nur **Studienbrief (PDF) und Vorlesungen (MP4)** (Pflichtquellen); Altklausuren und Extra-Übungs-PDFs (Optionalquellen) sind modulabhängig, weshalb die Pipeline auch ohne sie ein brauchbares Lernpaket liefern muss (graceful degradation), nur mit höherer Unsicherheit beim Relevanzsignal.

## Considered Options

Verworfen: Einmaliges Wegwerf-Skript für eine bekannte Klausur. Wäre schneller zu bauen, amortisiert sich bei 20+ Modulen aber nicht und würde Format/Material hartkodieren.
