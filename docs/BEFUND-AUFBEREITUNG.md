# Befund: Die Aufbereitung skaliert nicht über Module hinweg

Aufgenommen nach mehreren vollständigen Pipeline-Läufen (September 2026). Dieses
Dokument hält die **Beobachtungen** fest; die daraus folgenden Entscheidungen stehen
in ADR 0009–0011. Es ist kein Backlog — was gebaut wird, steht in den Issues 14–20.

## Der Auslöser

Ein Thema bekommt bis zu ~200 Chunks zugeordnet. Das ist keine Menge, die sich einem
Reasoning-Modell als Prompt übergeben lässt, und es ist unklar, ob die Chunks
inhaltlich dupliziert oder überhaupt einschlägig sind. Dazu kommt: Die Ausgangsdatenlage
unterscheidet sich je Modul so stark, dass sich keine strukturellen Gemeinsamkeiten
finden — nicht einmal ein Studienbrief liegt immer vor.

## Befund 1: Die Dokumentstruktur ist das Rückgrat, obwohl sie es nicht sein darf

`baue_themenkatalog()` (`pipeline/lernpaket_pipeline/themen.py:411`) leitet den
Themenkatalog aus den **Überschriften des Studienbriefs** ab. `gewichte_themen()`
schiebt die echten Relevanzsignale erst hinterher als Gewicht nach.

Das widerspricht dem eigenen Glossar. `CONTEXT.md`, Eintrag **Relevanzsignal**:

> […] Ausdrücklich NICHT der Studienbrief selbst, der die unsortierte Obermenge aller
> Inhalte ist.

Die Implementierung macht genau das Gegenteil, weil Überschriften der bequemste
verfügbare Anker waren. Alles Weitere folgt daraus.

## Befund 2: Die Heuristik-Last wächst pro Modul, nicht pro Feature

Sichtbare Folgen von Befund 1 im Code — jede Konstante ist an konkreten Modulen
geeicht und muss beim nächsten andersartigen Modul nachjustiert werden:

| Stelle | Zweck | Eichung |
| --- | --- | --- |
| `themen.py:32` `MAX_THEMEN_ANTEIL = 0.75` | erkennt, dass die Gliederung keine war | Mathe 2a 38,9 % / KonzMod 56,7 % / REST 98 % |
| `themen.py:36` `MIN_CHUNKS_FUER_WAECHTER` | Wächter bei kleinen Dokumenten abschalten | 20 |
| `themen.py:176` `_themen_aus_seitenbloecken` | Fallback, wenn keine Gliederung erkennbar | `ZIEL_THEMEN_FALLBACK = 30` |
| `themen.py:321` `_themen_aus_foliensatz` | kompletter Zweitpfad für Foliensätze | `ZIEL_FOLIEN_JE_THEMA = 15` |
| `themen.py:217` `MIN_NOMEN_ANTEIL` / `MAX_STREUUNG` | Fachbegriff vs. Redefüllsel im Transkript | 0,8 / 0,05 |
| `relevanz.py:148` `_wortnah` / `:165` `_titel_naehe` | Aufgabe ↔ Thema zuordnen | Handregeln |

Bei 20+ kommenden Modulen ist das die eigentliche Wartungslast.

## Befund 3: Ein Zuordnungs-Bug erzeugt einen Großteil der 200 Chunks

`ordne_chunks_zu()` (`themen.py:551`), letzte Schleife:

```python
for chunk in andere:
    chunk_woerter = {w.lower() for w in _WORT_RE.findall(chunk.text)}
    for thema in themen:
        titel_woerter = {w.lower() for w in _WORT_RE.findall(thema.titel)}
        if titel_woerter and titel_woerter & chunk_woerter:
            zuordnung[thema.id].append(chunk)
```

Drei Defekte auf vier Zeilen:

1. **Ein einziges gemeinsames Wort genügt** — kein Mindest-Überlappungsanteil.
2. **Der Chunk landet bei *jedem* passenden Thema**, nicht beim besten. Er wird also
   mehrfach gezählt und verbreitert mehrere Themen gleichzeitig.
3. **`STOPPWOERTER` wird hier nicht angewendet**, obwohl importiert und an drei anderen
   Stellen benutzt (`themen.py:487`, `verifikation.py:26`). `_WORT_RE` ist
   `[a-zA-ZäöüÄÖÜß]{4,}` — „eines", „diese", „unter", „werden" matchen alle. Ein Titel
   wie „Die Bedeutung eines Modells" fängt damit praktisch das halbe Transkript ein.

Ein Modul hat ~12 Vorlesungen à 90 Minuten; bei 60-Sekunden-Fenstern
(`chunks.py:TRANSKRIPT_FENSTER_SEKUNDEN`) sind das rund 1.000 Vorlesungs-Chunks, aus
denen sich diese Schleife bedient. Behebbar in Issue 15, unabhängig vom Redesign.

## Befund 4: Das Modell sieht nur einen Bruchteil des Themenmaterials

`waehle_prompt_chunks()` (`generierung.py:260`) schneidet auf `MAX_PROMPT_CHUNKS = 30`.
Bei 200 zugeordneten Chunks sieht das Reasoning-Modell ~15 % — ausgewählt per
Wortüberlappung, Klausurvokabular-Nähe und Marker-Treffer (`_chunk_score`). Die Auswahl
ist besser als das frühere Vorne-Abschneiden, aber sie ist blind gegenüber der Frage,
ob die verworfenen 85 % Dubletten oder das Kernkonzept sind.

**Die Quoten verschärfen das:** `PROMPT_QUOTEN` (`generierung.py:226`) reserviert feste
Plätze je Quelle (12 Studienbrief / 8 Folie / 6 Vorlesung / 2+2 optional). Das war nötig,
weil der Studienbrief sonst den Prompt monopolisierte — behandelt aber eine
Symptomursache (fehlende Dedup) mit einer festen Quote.

## Befund 5: Redundanz wird als Problem behandelt, nicht als Signal

Derselbe Inhalt liegt regelmäßig vierfach vor: im Studienbrief, auf der Folie, im
Transkript und in der Altklausur. Heute konkurrieren diese vier Chunks um dieselben 30
Prompt-Plätze. Dabei ist mehrfache Nennung über **Quellgrenzen hinweg** genau das
Relevanzsignal, das `CONTEXT.md` beschreibt — was im Studienbrief steht, auf der Folie
wiederholt, mündlich betont und in der Altklausur geprüft wurde, ist das
Klausurrelevante. Die Pipeline wirft diese Information heute weg.

## Befund 6: Drei Stellen, an denen Doku und Code auseinanderlaufen

Unabhängig vom Redesign zu bereinigen, weil sie beim Lesen in die Irre führen:

1. **`CONTEXT.md` → Relevanzsignal** sagt „nicht der Studienbrief", der Code baut den
   Katalog aus dem Studienbrief (Befund 1).
2. **`CONTEXT.md` → Pflichtquellen** sagt „Studienbrief (PDF, ~400 Seiten) und
   Vorlesungen (MP4) […] Die Pipeline darf ihr Vorhandensein voraussetzen." Das trifft
   nach den Läufen nicht zu. `finde_quellen` bricht ohne PDF ab (`README.md`:
   „Fehlt jedes PDF → Abbruch").
3. **ADR 0002** sagt „ein lokales Modell wird nirgends eingesetzt", `llm.py` führt seit
   Längerem `ollama` als vollwertigen vierten Anbieter (`ANBIETER`-Tupel,
   `OLLAMA_CTX`, native `/api/chat`-Route). ADR 0010 zieht die Grenze neu.

## Was zuerst gemessen gehört

Alle Zahlen oben außer den Konstanten sind Beobachtung oder Schätzung. Vor dem Umbau
sollte ein Diagnoseschritt über ein bereits gelaufenes Modul (Issue #45) belegen:

- Chunks je Thema: Median, 90. Perzentil, Maximum
- Anteil der Chunks, die je einen Generierungs-Prompt erreichen
- Duplikatrate innerhalb eines Themas und über Quellgrenzen hinweg
- Anteil organisatorischer/nicht-substanzieller Chunks (Inhaltsverzeichnis,
  Übungslösungsköpfe, Begrüßung im Transkript)
- Verteilung der Themenzahl je Modul gegen das Zielband 15–40

Ohne diese Zahlen ist nicht entscheidbar, ob Dedup allein reicht (Issue #47) oder die
Aussagen-Schicht (Issue #48) nötig ist.

**Werkzeug (Issue #45, erledigt):** `lernpaket diagnose <lernpaket-verzeichnis>` rechnet
alle fünf Kennzahlen oben aus einem bereits generierten Lernpaket nach — deterministisch,
ohne LLM (`pipeline/lernpaket_pipeline/diagnose.py`). Ausgabe ist JSON (`--ausgabe
datei.json`, sonst stdout) plus eine Textzusammenfassung auf stderr. Getestet an einem
synthetischen Mini-Modul mit von Hand nachgerechneten Sollwerten
(`pipeline/tests/test_diagnose.py`).

**Reale Zahlen stehen noch aus.** Dieser Agent-Lauf hatte keinen Zugriff auf ein bereits
gelaufenes Modul (`input/`-Verzeichnis mit Extraktion + Lernpaket) — weder im Repo (dort
bewusst nicht versioniert, siehe `.gitignore`) noch in der Remote-Ausführungsumgebung
dieser Session. Um die Tabelle unten zu füllen und damit das Abbruchkriterium aus Issue
#44 zu prüfen, einmal lokal ausführen und die Ausgabe hier eintragen (oder an diese
Konversation zurückgeben):

```
uv run lernpaket diagnose pfad/zum/lernpaket --ausgabe kennzahlen.json
```

| Kennzahl | Wert |
| --- | --- |
| Modul | *(noch nicht gemessen)* |
| Themen (Zielband 15–40) | — |
| Chunks je Thema: Median / P90 / Max | — |
| Mehrfachzuordnungsfaktor | — |
| Anteil im Generierungs-Prompt | — |
| Dublettenrate (gesamt / quellübergreifend) | — |
| Anteil nicht-substanzieller Chunks | — |

## Was **nicht** in Frage steht

Der Kern des Entwurfs trägt und bleibt: Offline-Aufbereitung → statisches Lernpaket →
adaptiver Player; Belegpflicht (ADR 0003), Verifikationsdurchlauf, Materiallücken statt
Halluzination; der Datei-Vertrag als Grenze (ADR 0005); `chunks.jsonl` als gemeinsame
Wahrheit. Ersetzt wird die Mitte — die Strukturheuristik zwischen Extraktion und
Generierung — nicht das Projekt.
