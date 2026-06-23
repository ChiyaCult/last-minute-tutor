# PRD: Klausur-Lernpaket-Generator

> Synthetisiert aus der Designsession. Vokabular gemäß `CONTEXT.md`, Entscheidungen gemäß ADR 0001–0005. Offene Bauentscheidungen siehe `docs/OFFENE-PUNKTE.md`.

## Problem Statement

Ich mache ein Fernstudium mit 20+ kommenden Modulen. Ich besuche Vorlesungen nur sporadisch, lerne das Semester über nicht aktiv mit und habe den Stoff bis zur Klausur ohnehin wieder vergessen. Kurz vor den Prüfungen — typisch ein Fenster von 3 Tagen bis 2 Wochen, nur wenige Stunden am Tag, und fast immer 2–3 Klausuren am selben Tag — muss ich mir das Klausurrelevante effizient aneignen. Die Materialien sind dafür ungeeignet aufbereitet: Der Studienbrief hat ~400 Seiten ohne Gewichtung, was wichtig ist, und die wirklich relevanten Hinweise stecken verstreut in Altklausuren, Übungen und mündlichen Betonungen in stundenlangen Vorlesungsvideos, die ich nicht alle anhören will. Ich habe ein starkes Software-Grundwissen (12 Jahre Praxis), auf dem aufgebaut werden kann, will aber nicht erneut Grundlagen durchkauen.

## Solution

Ein wiederverwendbares Werkzeug, das pro Modul einmalig und offline aus den Materialien ein **Lernpaket** erzeugt (**Aufbereitung**) und es mir über eine lokale, interaktive Oberfläche (**Player**) in der **Lernphase** adaptiv beibringt und abfragt.

Die Aufbereitung leitet aus den **Relevanzsignalen** (Altklausuren, Übungen, mündliche Betonungen in den Vorlesungen) einen vollständigen **Themenkatalog** ab und erzeugt pro **Thema** Lehrblöcke und zum erkannten **Zielformat** passende Quizfragen — jede Aussage mit einem **Beleg** auf die Quelle, fehleranfällige Stellen zusätzlich verifiziert, Lücken im Material als **Materiallücke** markiert statt erfunden.

Im Player startet ein **Diagnosequiz**, das misst, was ich schon kann; nur für echte Lücken wird Lehrtiefe freigeschaltet. Ein **Wiederholungsplan** verteilt die Themen über die verfügbaren Tage. Ein optionaler **Tutormodus** beantwortet freie Rückfragen und generiert bei Bedarf zusätzlichen Inhalt — geerdet in den Modulmaterialien. Die 2–3 gleichzeitig anstehenden Module werden unabhängig voneinander aufbereitet und abgefragt.

## User Stories

1. Als Studierender möchte ich pro Modul den Studienbrief (PDF) und die Vorlesungen (MP4) übergeben, damit das Tool ohne weitere Pflichtmaterialien starten kann.
2. Als Studierender möchte ich optional Altklausuren und zusätzliche Übungs-PDFs übergeben, damit das Relevanzsignal stärker wird, wenn ich sie habe.
3. Als Studierender möchte ich, dass das Tool auch ohne Altklausuren/Extra-Übungen ein brauchbares Lernpaket liefert (graceful degradation), damit frühe Module ohne diese Materialien nicht ausfallen.
4. Als Studierender möchte ich, dass ein reiner Scan-Studienbrief ohne Textebene trotzdem verarbeitet wird, damit auch gescannte PDFs funktionieren.
5. Als Studierender möchte ich, dass Formeln, Diagramme, Code und Tabellen aus dem Studienbrief korrekt erfasst werden, damit formellastige Module nicht ausgehöhlt werden.
6. Als Studierender möchte ich, dass die Vorlesungen transkribiert werden, damit ich sie nicht selbst anhören muss.
7. Als Studierender möchte ich, dass mündliche Relevanzhinweise der Professoren ("das ist klausurrelevant") aus dem Transkript extrahiert werden, damit das präziseste Relevanzsignal genutzt wird.
8. Als Studierender möchte ich, dass die auf Vorlesungsfolien gezeigten Formeln/Strukturen aus dem Video erfasst werden, damit Inhalt, der nur visuell auf den Folien steht, nicht verloren geht.
9. Als Studierender möchte ich einen vollständigen Themenkatalog des klausurrelevanten Stoffs, damit die Abdeckung lückenlos ist, auch wenn die Lehrtiefe später adaptiv variiert.
10. Als Studierender möchte ich, dass das Tool das wahrscheinliche Zielformat vorschlägt und ich es bestätige oder korrigiere, damit die Quizfragen zum echten Prüfungsformat passen.
11. Als Studierender möchte ich format-parametrische Quizfragen (MC, Rechenaufgabe, Freitext-Definition, Beweis), damit unterschiedliche Module sinnvoll abgefragt werden.
12. Als Studierender möchte ich, dass jeder Lehrblock und jede Quizfrage einen Beleg auf Studienbriefseite oder Vorlesungsminute trägt, damit ich alles in Sekunden nachprüfen kann.
13. Als Studierender möchte ich, dass Quizantworten und numerische/formelhafte Inhalte zusätzlich gegen die Quelle verifiziert werden, damit ich nichts Falsches lerne.
14. Als Studierender möchte ich, dass das Tool offene/widersprüchliche Stellen als Materiallücke markiert, statt zu erfinden, damit ich weiß, wo ich ins Original oder in den Tutormodus muss.
15. Als Studierender möchte ich die Aufbereitung 1–2 Wochen vor der Prüfung einmalig anstoßen, damit Qualität vor Geschwindigkeit geht und ich später nur noch lerne.
16. Als Studierender möchte ich in der Lernphase ein Diagnosequiz durchlaufen, damit das Tool misst, was ich schon kann, statt es zu raten.
17. Als Studierender möchte ich, dass nur für meine echten Lücken Lehrtiefe freigeschaltet wird, damit ich meine wenigen Stunden nicht mit Bekanntem verschwende.
18. Als Studierender möchte ich, dass sicher beherrschte Themen nur leicht aufgefrischt werden, damit mein Vorwissen respektiert wird.
19. Als Studierender möchte ich, dass der Player meine Themen pro Modul über die verfügbaren Tage verteilt (Spaced Repetition), damit Retention besser ist als durch Cramming.
20. Als Studierender möchte ich, dass der Wiederholungsplan bei nur 3 Tagen in Triage kippt und bei 2 Wochen echtes verteiltes Wiederholen fährt, damit er sich an mein Fenster anpasst.
21. Als Studierender möchte ich, dass schwache Themen gezielt mehrfach zurückkommen, damit sie sich festigen.
22. Als Studierender möchte ich, dass mein Lernfortschritt über mehrere Tage gespeichert wird, damit ich Sessions unterbrechen und fortsetzen kann.
23. Als Studierender möchte ich die 2–3 gleichzeitig anstehenden Module unabhängig aufbereiten und abfragen, damit ich mein Tagesbudget selbst zwischen ihnen aufteilen kann.
24. Als Studierender möchte ich, dass der Kern (Lehre + Quiz) offline und kostenfrei nutzbar ist, damit ich beim Lernen weder Netz noch laufende Kosten brauche.
25. Als Studierender möchte ich im Tutormodus freie Rückfragen stellen, wenn ich etwas nicht verstehe, damit ich nicht hängenbleibe.
26. Als Studierender möchte ich im Tutormodus gezielt zusätzlichen Lehrinhalt nachgenerieren lassen, damit ich ein Thema vertiefen kann, das das Lernpaket nicht abdeckt.
27. Als Studierender möchte ich, dass der Tutormodus in den Modulmaterialien geerdet antwortet (mit Beleg), damit er nicht von der kursspezifischen Notation abdriftet.
28. Als Studierender möchte ich, dass mein API-Schlüssel nur lokal im Player-Backend liegt und nie im Frontend, damit er nicht ausläuft.
29. Als Studierender möchte ich dasselbe Tool über 20+ Module wiederverwenden, damit sich der einmalige Bauaufwand amortisiert.
30. Als Studierender möchte ich formelhafte Lehrinhalte korrekt gerendert sehen (LaTeX), damit mathematische Module verständlich bleiben.
31. Als Studierender möchte ich erkennen, welche Themen ich noch nicht beherrsche, damit ich meinen Lernstand pro Modul einschätzen kann.

## Implementation Decisions

- **Zwei entkoppelte Teilsysteme** (ADR 0005): eine Python-**Aufbereitung**-Batch-Pipeline und ein JavaScript/Node-**Player** (Frontend + dünnes Backend). Kommunikation ausschließlich über eine Datei-Grenze; die Pipeline erzeugt das Lernpaket als Dateien, der Player liest sie. Genaues Dateischema offen (`OFFENE-PUNKTE.md` #3).
- **Wiederverwendbare Pipeline** (ADR 0001): pro Modul parametrisiert; **Pflichtquellen** (Studienbrief-PDF, Vorlesungs-MP4) voraussetzbar, **Optionalquellen** (Altklausuren, Extra-Übungen) optional mit graceful degradation.
- **Extraktion** (ADR 0004): Dokument-Parser-Pipeline-Tool (Marker als Default, MinerU bei formellastig) als Rückgrat für Textebene, OCR-Fallback bei Scans, Formel→LaTeX und Tabellen. Erkennungsschritt Textebene-vs-Scan am Anfang. Vorlesung: Audio-Transkription (Whisper-Familie via faster-whisper/WhisperX) plus Folien-Standbilder via PySceneDetect, die durch dieselbe Extraktion laufen.
- **Reasoning-LLM remote** (ADR 0002): Generierung von Themenkatalog, Lehrblöcken, Quizfragen und der Tutormodus laufen remote mit Spitzenmodell. Vorverarbeitung (OCR, ASR, Scene-Detection, Embeddings) darf lokal laufen — eigene Werkzeugklasse, kein Widerspruch.
- **Treue-Vertrag** (ADR 0003): Jedes generierte Artefakt (Lehrblock, Quizfrage) trägt verpflichtend einen **Beleg**; der Generator darf nur Belegbares behaupten. Zweiter Verifikationsdurchlauf gezielt auf Quizantworten und Numerisches/Formelhaftes. **Materiallücke** wird markiert statt erfunden. Das Reasoning-LLM sieht nur normalisiertes Markdown + Transkript mit Quellpositionen (Seite/Minute), nie Rohmaterial.
- **Themenkatalog**: vollständige Abdeckung; **Thema**-Granularität mittel (~15–40 pro Modul), vom Tool automatisch skaliert. Manuelle Übersteuerung im Backlog.
- **Zielformat**: Erkennen-dann-Bestätigen pro Modul; Quiz-Erzeugung format-parametrisch.
- **Player-Adaptivität**: **Diagnosequiz** kalibriert Lehrtiefe; nur Lücken schalten Lehrblöcke frei. **Wiederholungsplan** pro Modul, fensteradaptiv (Triage bei 3 Tagen, Spacing bei 2 Wochen). SRS-Algorithmus offen (`OFFENE-PUNKTE.md` #1).
- **Tutormodus**: Player-Backend proxyt Remote-Calls (API-Schlüssel nur lokal, nie im Frontend); Antworten geerdet via Retrieval. Embedding-/Index-Setup offen (`OFFENE-PUNKTE.md` #2).
- **Speicher**: SQLite (oder JSON-Datei) für Fortschritt/Wiederholungsstand; generierter Inhalt als statische Dateien. Kein MongoDB.
- **Mehrere Module unabhängig**: kein modulübergreifender Scheduler; der Nutzer teilt das Tagesbudget selbst auf. Optionaler Aufteilungs-/Interleaving-Helfer im Backlog.

## Testing Decisions

- **Was ein guter Test ist**: prüft externes Verhalten an einer Naht, nicht Implementierungsdetails. Bei LLM-Schritten wird nicht exakter Text geprüft, sondern **Invarianten/Verträge** (jedes Artefakt hat einen Beleg; Verifikation markiert Quelle-Inhalt-Abweichungen; Materiallücke statt Erfindung; Themenkatalog deckt erkannte Relevanzsignale ab).
- **Höchste Naht: die Datei-Grenze zwischen Pipeline und Player.** Player gegen fixe Lernpaket-Fixtures testen (deterministisch); Pipeline gegen ihre Ausgabedateien bei fixem Eingabematerial. Das entkoppelt nicht-deterministische Generierung vom deterministischen Player.
- **Player-Verhalten** an Fixtures: Diagnosequiz → korrekte Lücken-/Freischalt-Entscheidung; Wiederholungsplan → erwartete Verteilung bei 3-Tage- vs. 2-Wochen-Fenster; Fortschritt persistiert über simulierte Sessions.
- **Pipeline-Verträge**: Extraktion deterministisch testbar (Scan-Erkennung, Textebene-Fallback, Formel-Erfassung an kleinen Fixtures); Generierung gegen aufgezeichnete/gemockte LLM-Antworten auf Vertragsebene.
- **Prior art**: keiner (Greenfield) — die Nähte werden neu gesetzt, daher so hoch wie möglich an der Datei-Grenze.

## Out of Scope

- Modulübergreifender Scheduler / Tagesbudget-Aufteilung / Interleaving-Helfer (Backlog).
- Manuelle Übersteuerung der Themen-Granularität pro Modul (Backlog).
- Lokales Reasoning-LLM (ADR 0002 ausgeschlossen).
- Export nach Anki o. ä. (verworfen zugunsten des integrierten Pakets).
- Aktives Mitlernen während des Semesters; das Tool adressiert nur die Lernphase kurz vor der Klausur.
- Eigene Mitschriften des Nutzers als Quelle.

## Further Notes

- Die ursprünglichen Sorgen des Nutzers (Kontextfenster bei 400 Seiten; Kosten/lokal-vs-remote) sind durch die Architektur adressiert: Map-Reduce-Extraktion vermeidet große Kontexte; das LLM steckt nur in kalten Pfaden (einmalige Aufbereitung, seltener Tutormodus), daher remote günstig.
- Drei bewusst offene Bauentscheidungen in `docs/OFFENE-PUNKTE.md`: SRS-Algorithmus, Embedding-/Retrieval-Setup, Datei-Vertrags-Schema.
- Publish-Schritt der to-prd-Skill (Issue-Tracker + `ready-for-agent`-Label) steht aus: kein Tracker in der Session angebunden.
