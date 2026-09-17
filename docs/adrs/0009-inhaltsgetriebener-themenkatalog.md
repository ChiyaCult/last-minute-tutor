# Inhaltsgetriebener Themenkatalog statt Strukturheuristik

> **Status: Vorschlag.** Begründet in `docs/BEFUND-AUFBEREITUNG.md`, umgesetzt über die
> Issues 14–19. Ersetzt bei Annahme den Themen-Teil von ADR 0008 und korrigiert die
> Einträge **Relevanzsignal** und **Pflichtquellen** in `CONTEXT.md`.

Der Themenkatalog entsteht künftig aus dem **Inhalt** der Materialien, nicht aus der
**Gliederung** des Studienbriefs. Zwischen Chunks und Generierung wird eine
Verdichtungsschicht eingezogen, die vier Aufgaben löst, die heute keine Stelle löst:
irrelevantes Material aussortieren, Duplikate verschmelzen, Themen bilden und den
Generierungs-Prompt auf eine sinnvolle Größe bringen.

## Warum die heutige Form nicht trägt

`baue_themenkatalog()` liest die Überschriften des Studienbriefs. Das setzt voraus, dass
(a) ein Studienbrief existiert, (b) er eine maschinell erkennbare Gliederung hat und
(c) diese Gliederung der Klausurrelevanz entspricht. Über die bisher gelaufenen Module
trifft keine der drei Annahmen verlässlich zu, und jede Abweichung kostet eine weitere
geeichte Konstante (Befund 2). Zugleich verlangt `CONTEXT.md` ausdrücklich, dass der
Studienbrief *nicht* relevanzführend ist — die Implementierung hat das umgedreht.

## Die neue Kette

```
Extraktion → Chunks → Aussagen → Verschmelzung → Cluster → Themen → Lehrblöcke
              (bleibt)   neu        neu          neu      (neu befüllt)
```

### 1. Chunk → Aussagen (extraktiv, lokales Modell)

Je Chunk ein Aufruf eines kleinen lokalen Modells, das den Chunk auf strukturierte
Datensätze reduziert:

```json
{ "chunk_id": "c-0417",
  "art": "definition|satz|verfahren|beispiel|aufgabe|organisatorisch",
  "aussage": "<aus dem Chunk übernommener Kernsatz>",
  "begriffe": ["Normalform", "funktionale Abhängigkeit"],
  "substanziell": true }
```

Das Modell **wählt aus und etikettiert, es formuliert nicht** — die Grenze zieht
ADR 0010. Damit beantwortet diese Stufe zum ersten Mal die Frage „ist dieser Chunk
überhaupt einschlägig?": `art == "organisatorisch"` oder `substanziell == false` fällt
raus (Inhaltsverzeichnisse, Übungslösungsköpfe, Begrüßungsgeplapper im Transkript).

### 2. Verschmelzung — Redundanz ist das Relevanzsignal

Aussagen oberhalb einer Ähnlichkeitsschwelle werden **nicht gelöscht, sondern zu einer
Aussage mit mehreren Belegen zusammengezogen**:

```json
{ "id": "a-0087", "aussage": "…", "belege": [
    { "quelle": "studienbrief", "position": "S. 84",              "chunk_id": "c-0417" },
    { "quelle": "folie",        "position": "VL03, Folie 12",     "chunk_id": "c-0912" },
    { "quelle": "vorlesung",    "position": "VL03, Min. 21:40",   "chunk_id": "c-1104" },
    { "quelle": "altklausur",   "position": "ws2018, S. 2",       "chunk_id": "c-1533" } ] }
```

Das ist der tragende Gedanke dieses ADR: **Mehrfachnennung über Quellgrenzen hinweg ist
genau das Relevanzsignal aus `CONTEXT.md`** — Studienbrief plus Folie plus mündliche
Betonung plus Altklausur. Es fällt aus der Belegliste ab, ohne eine einzige neue
Heuristik. Die vorhandenen `RELEVANZ_MARKER` bleiben als Zusatzsignal, tragen aber nicht
mehr allein.

### 3. Cluster → Themen

Aussagen werden eingebettet und geclustert (ADR 0011), die Clusterzahl aufs Zielband
15–40 eingeregelt, dann benennt **ein** gebündelter LLM-Aufruf die Cluster. Die Funktion
dafür existiert bereits: `benenne_themen()` (`themen.py:612`), heute nur im
Foliensatz-Pfad.

Überschriften sind, wo vorhanden, ein **Prior** — Aussagen unter derselben Überschrift
bekommen einen Ähnlichkeitsbonus — nicht mehr das Rückgrat. Ein Modul ohne Studienbrief
durchläuft denselben Code mit weniger Quellen. **Ein Pfad statt drei.**

### 4. Generierung aus dem Themen-Dossier

Der Prompt enthält die verschmolzenen, nach Belegvielfalt sortierten Aussagen eines
Themas statt 30 Roh-Chunks. 60 Aussagen à ~150 Zeichen sind ~2.500 Token — **weniger**
als die heutigen 30 × 1400 Zeichen, decken aber alle zugeordneten Chunks ab statt ~15 %.

## Was der Belegvertrag dazu sagt

ADR 0003 bleibt vollständig intakt, und das ist die Bedingung, unter der dieser Umbau
überhaupt zulässig ist: Jede Aussage trägt die `chunk_id`s ihrer Quellchunks, jeder
Lehrblock trägt die Belege seiner Aussagen, `chunks.jsonl` bleibt unverändert die
prüfbare Wahrheit, und `verifiziere()` prüft weiterhin gegen Chunk-Text. Die
Verdichtungsschicht ist ein **Auswahl- und Gruppierungsschritt**, keine Umformulierung.

## Considered Options

**Nur den Zuordnungs-Bug beheben** (Befund 3) und die Chunk-Auswahl verbessern. Wird
trotzdem gemacht (Issue 15), weil billig und sofort wirksam — reicht aber nicht: Es
verkleinert die Chunk-Menge, beantwortet aber weder Relevanz noch Dubletten, und der
Themenkatalog hinge weiter an der Gliederung.

**Map-Reduce mit dem Remote-Modell** statt lokal: qualitativ das Beste, aber tausende
Remote-Aufrufe je Modul bei 20+ Modulen. ADR 0002 rechtfertigt sich gerade damit, dass
das Volumen klein bleibt („Cent-Beträge"). Diese Stufe würde das aufheben.

**Größeres Kontextfenster / mehr Chunks in den Prompt:** verschiebt die Grenze, statt sie
aufzulösen, und verschlechtert bei dupliziertem Material die Antwortqualität. Die
Ursache ist nicht Fenstergröße, sondern fehlende Verdichtung.

**Themen manuell je Modul pflegen:** widerspricht ADR 0001 (wiederverwendbare Pipeline)
und der Kernanforderung, dass das Tool alle Inhalte selbst aus den Rohmaterialien zieht.

## Consequences

**Was verschwindet.** Nach Stufe 4 entfallen `MAX_THEMEN_ANTEIL`,
`MIN_CHUNKS_FUER_WAECHTER`, `_themen_aus_seitenbloecken`, `_themen_aus_foliensatz`,
`ZIEL_FOLIEN_JE_THEMA`, `MIN_NOMEN_ANTEIL`/`MAX_STREUUNG`, die Zuordnungsschleife in
`ordne_chunks_zu` und voraussichtlich `PROMPT_QUOTEN`. Das ist der eigentliche Ertrag:
weniger geeichte Konstanten, die pro neuem Modul nachjustiert werden müssen.

**Was ADR 0008 davon behält.** Die Dokumentart-Erkennung bleibt für die *Extraktion*
relevant und wichtig — insbesondere „Marker ist bei Foliensätzen konstitutiv", denn ohne
gerenderte Seite entstehen lautlos falsche Formeln. Nur die **Themenbildung** je
Dokumentart entfällt; die Tabelle „Was sich je Art unterscheidet" schrumpft auf
Abbildungen und Formelerfassung.

**Was `CONTEXT.md` ändern muss.** Der Eintrag **Pflichtquellen** („Die Pipeline darf ihr
Vorhandensein voraussetzen") ist nach den Läufen falsch und wird zu: *Jede Quellart ist
optional; die Quellart beeinflusst Gewichte, nie Codepfade. Die Pipeline braucht
mindestens eine verwertbare Quelle und meldet fehlende Arten als Materiallücke.*
Entsprechend verliert **Optionalquellen** seine Sonderrolle.

**Was der Datei-Vertrag bekommt.** `aussagen.jsonl` tritt neben `chunks.jsonl`; letzteres
bleibt unverändert (Beleg-Anker, BM25-Grundlage nach ADR 0007). Additiv, `schema_version`
bleibt 1 — der Player ignoriert Unbekanntes.

**Was der Player gewinnt.** Verschmolzene Aussagen mit Mehrfachbelegen erlauben im
Lehrblock den Hinweis „dazu sagt die Vorlesung bei Min. 21:40 noch das hier", und der
BM25-Index des Tutormodus trifft über deduplizierte Aussagen besser als über Rohchunks.

**Risiko.** Die Clustergrenzen sind weicher als Kapitelgrenzen; ein Thema kann fachlich
unsauber schneiden, wo eine Kapitelüberschrift eindeutig war. Gegenmaßnahme: die
goldenen Themenzahlen der bekannten Module (Mathe 2b 28, KonzMod 14, REST 33) bleiben als
Regressionstest, und der Überschriften-Prior hält den Prosa-Fall nah an der bisherigen
Gliederung.
