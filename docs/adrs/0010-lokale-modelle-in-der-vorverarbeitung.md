# Grenze zwischen Vorverarbeitung und Reasoning: extraktiv lokal, formulierend remote

> **Status: Vorschlag.** Präzisiert den Geltungsbereich von ADR 0002 und erweitert die
> Werkzeugklasse aus ADR 0004. Voraussetzung für die Aussagen-Schicht in ADR 0009.

**Die Regel in einem Satz:** Ein Modell, das **auswählt, etikettiert und zuordnet**,
gehört zur Vorverarbeitung und darf lokal laufen. Ein Modell, das **formuliert, erklärt
oder behauptet**, ist Reasoning und läuft remote (ADR 0002).

## Warum die Grenze überhaupt neu gezogen werden muss

ADR 0002 formuliert absolut: „Sämtliche LLM-Nutzung läuft über ein remote
bereitgestelltes Spitzenmodell; ein lokales Modell wird nirgends eingesetzt."

Das stimmt so nicht mehr. `llm.py` führt `ollama` als vollwertigen vierten Anbieter
(`ANBIETER`-Tupel, `OLLAMA_CTX`, native `/api/chat`-Route mit abgeschaltetem Thinking),
und `vergleichslauf.py` vergleicht zwei lokale Modelle auf identischen Prompts. Der Code
ist an ADR 0002 vorbeigelaufen, ohne dass der Widerspruch notiert wurde.

ADR 0004 erlaubt lokale Verarbeitung bereits, aber über eine **Aufzählung** statt über
ein Kriterium: „OCR, ASR, Scene-Detection und ggf. Embeddings". Eine Aufzählung
beantwortet nicht, ob ein kleines Sprachmodell zur Aussagen-Extraktion dazugehört. Dieses
ADR ersetzt die Aufzählung durch ein prüfbares Kriterium.

## Das Kriterium

| | Vorverarbeitung (lokal erlaubt) | Reasoning (remote, ADR 0002) |
| --- | --- | --- |
| **Ausgabe** | Spannen, Labels, IDs, Zahlen, Gruppen | Fließtext, Erklärungen, Fragen |
| **Rückführbarkeit** | jede Ausgabe auf eine Quellstelle zurückführbar | neue Formulierung |
| **Fehlerbild** | falsche Auswahl → Lücke, fällt auf | falsche Behauptung → lautloser Schaden |
| **Beispiele** | OCR, ASR, Szenenerkennung, Embeddings, Aussagen-Extraktion, Clustering, Reranking, Duplikaterkennung | Lehrblöcke, Quizfragen, Erklärungen, Themen-Titel, Tutorantworten |

Das Fehlerbild ist der eigentliche Grund für die Linie. Wählt ein lokales Modell einen
Satz nicht aus, fehlt Material — sichtbar, und die Belegkette bleibt heil. Formuliert ein
schwaches Modell dagegen eine falsche Definition, sieht das Ergebnis aus wie ein
vollwertiger Lehrblock. Das ist derselbe Grund, aus dem die Pipeline bei ausgefallenem
Anbieter mit Exit-Code 3 abbricht, statt heimlich auf die Heuristik zurückzufallen.

**Themen-Titel liegen bewusst auf der Reasoning-Seite**, obwohl sie kurz sind: Ein Titel
ist eine Behauptung darüber, wovon ein Cluster handelt, und er steuert die Zuordnung von
Altklausuraufgaben. `benenne_themen()` bleibt daher remote.

## Absicherung der lokalen Stufe

Weil ein 4B-Modell gelegentlich doch formuliert, wird die Grenze nicht nur im Prompt
behauptet, sondern maschinell geprüft:

1. **Schema-validiertes JSON**; was das Schema verletzt, wird verworfen, nicht repariert.
2. **Rückführbarkeitsprüfung:** Der Feldwert `aussage` muss sich mit hoher
   Wortüberlappung im Quellchunk wiederfinden. Was diesen Test nicht besteht, wird
   verworfen — der Chunk bleibt dann unverdichtet und geht roh weiter, statt eine
   erfundene Aussage zu erzeugen.
3. **Kein Ersatzweg:** Fällt das lokale Modell komplett aus, läuft die Pipeline ohne
   Aussagen-Schicht weiter (Chunks direkt, heutiges Verhalten) und vermerkt das im
   Manifest. Kein stiller Qualitätsabfall ohne Spur.

## Considered Options

**Bei ADR 0002 bleiben und die Aussagen-Extraktion remote fahren:** qualitativ sauberer,
aber tausende Aufrufe je Modul bei 20+ Modulen — es hebt genau die Kostenannahme auf, mit
der sich ADR 0002 begründet.

**Regelbasiert statt Modell** (Satzlängen, Positionsheuristiken, Schlüsselwortlisten):
genau der Ansatz, dessen Wartungslast `docs/BEFUND-AUFBEREITUNG.md` als Befund 2
dokumentiert. Nicht noch eine Schicht davon.

**ADR 0002 ersatzlos streichen:** verliert das Wertvolle daran — die Zusicherung, dass
der Nutzer im Moment der Verständnislücke nicht mit einem schwächeren Modell abgespeist
wird.

## Consequences

ADR 0002 gilt unverändert für alles, was im Lernpaket als Inhalt landet, und für den
Tutormodus. Sein Absolutheitsanspruch („nirgends") wird auf „in keinem formulierenden
Pfad" eingeschränkt.

Der bereits vorhandene `ollama`-Anbieter in `llm.py` ist damit nachträglich legitimiert —
allerdings mit einer Unterscheidung, die der Code heute nicht kennt: als
*Vorverarbeitungs*-Modell für die Aussagen-Schicht, nicht als Ersatz für das
Reasoning-Modell. Beides gleichzeitig zu konfigurieren muss möglich sein (getrennte
Umgebungsvariablen), und das Manifest hält fest, welches Modell welche Stufe gefahren
hat — sonst ist später nicht mehr feststellbar, unter welchen Bedingungen ein Paket
entstanden ist.

Die Offline-Fähigkeit des Kerns verbessert sich: Die Aufbereitung braucht für die
Verdichtung keine Netzverbindung mehr, nur noch für die Generierung.
