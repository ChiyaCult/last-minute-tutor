# Issue-Entwürfe: Aufbereitung 14–21

> **Zwischenablage-Datei.** Diese Issues konnten nicht automatisch angelegt werden (die
> GitHub-App hat für dieses Repo nur Lesezugriff — `403 Resource not accessible by
> integration`). Die Texte folgen der Konvention der bestehenden Issues #21–#33
> (`N · Titel`, Label `ready-for-agent`). **Nach dem Anlegen bitte diese Datei löschen**
> und die `#`-Nummern im Epic nachtragen.

---

## 14 · Aufbereitung: inhaltsgetriebene Themenbildung statt Strukturheuristik

**Typ:** Epic

**Befund:** `docs/BEFUND-AUFBEREITUNG.md`
**ADRs (Status: Vorschlag):** 0009 · 0010 · 0011

**Was los ist:** Nach mehreren vollständigen Läufen trägt die Themenbildung über die
Gliederung des Studienbriefs nicht mehr. Bis zu ~200 Chunks je Thema, unklare Relevanz,
unerkannte Dubletten zwischen Studienbrief/Folie/Transkript/Altklausur — und je neuem
Modul eine weitere geeichte Konstante. `CONTEXT.md` verlangt ausdrücklich, dass der
Studienbrief *nicht* relevanzführend ist; `baue_themenkatalog()` (`themen.py:411`) macht
genau das Gegenteil.

**Zielbild (ADR 0009):**

```
Extraktion → Chunks → Aussagen → Verschmelzung → Cluster → Themen → Lehrblöcke
              (bleibt)   neu        neu          neu      (neu befüllt)
```

Tragender Gedanke: **Mehrfachnennung über Quellgrenzen hinweg ist das Relevanzsignal.**
Dubletten werden nicht gelöscht, sondern zu einer Aussage mit mehreren Belegen
verschmolzen.

**Was nicht angetastet wird:** Belegpflicht (ADR 0003), Verifikationsdurchlauf,
Materiallücken, Datei-Vertrag als Grenze (ADR 0005), `chunks.jsonl` als gemeinsame
Wahrheit. Ersetzt wird die Mitte, nicht das Projekt.

**Reihenfolge — jede Stufe einzeln testbar und einzeln abbrechbar:**

- [ ] 15 · Diagnose: Chunk-Kennzahlen messen *(zuerst)*
- [ ] 16 · Bug: `ordne_chunks_zu` überzieht die Zuordnung *(unabhängig vom Rest)*
- [ ] 17 · Verschmelzung: Dubletten zu Mehrfachbelegen
- [ ] 18 · Aussagen-Schicht (extraktiv, lokales Modell)
- [ ] 19 · Themen per Clustering; Strukturheuristik abbauen
- [ ] 20 · Vorberechnete Nachbarschaften im Lernpaket
- [ ] 21 · Tutor: BM25 plus LLM-Query-Expansion

**Abbruchkriterium:** Zeigt 15, dass nach 16 und 17 der Median unter ~40 Chunks je Thema
liegt und der Dublettenanteil klein ist, sind 18/19 zurückzustellen — dann war es ein
Zuordnungsproblem, kein Designproblem.

---

## 15 · Diagnose: Chunk-Kennzahlen je Modul messen

**Parent:** 14
**Typ:** AFK

**Was zu bauen:** Ein Unterbefehl bzw. Skript, das über ein bereits gelaufenes Modul
(Extraktionsergebnis + Lernpaket) die Kennzahlen ausgibt, die den Umbau steuern. Ohne
diese Zahlen sind die Stufen 17–19 nicht entscheidbar — alles in
`docs/BEFUND-AUFBEREITUNG.md` außer den Code-Konstanten ist bisher Beobachtung oder
Schätzung.

**Akzeptanzkriterien:**
- [ ] Chunks je Thema: Median, 90. Perzentil, Maximum, Verteilung je Quelle.
- [ ] Anteil der Chunks, die je einen Generierungs-Prompt erreichen (gegen
      `MAX_PROMPT_CHUNKS`/`PROMPT_QUOTEN`).
- [ ] Dublettenrate innerhalb eines Themas und über Quellgrenzen hinweg (zunächst
      lexikalisch, Jaccard/MinHash — ohne neue Abhängigkeit).
- [ ] Anteil nicht-substanzieller Chunks (Inhaltsverzeichnis, Übungslösungsköpfe,
      Begrüßung im Transkript), stichprobenhaft klassifiziert.
- [ ] Themenzahl je Modul gegen das Zielband 15–40.
- [ ] Ausgabe maschinenlesbar (JSON) und als kurze Textzusammenfassung; läuft ohne
      LLM-Anbindung.
- [ ] Test: Kennzahlen auf einem synthetischen Mini-Modul mit bekannten Sollwerten.

---

## 16 · Bug: `ordne_chunks_zu` überzieht die Zuordnung

**Parent:** 14
**Typ:** AFK

**Was zu bauen:** Die Zuordnung von Nicht-Studienbrief-Chunks in `ordne_chunks_zu()`
(`themen.py:551`) reparieren. Erzeugt einen Großteil der ~200 Chunks je Thema und ist
unabhängig vom übrigen Redesign behebbar (Befund 3).

Drei Defekte auf vier Zeilen:
1. Ein einziges gemeinsames Wort genügt — kein Mindest-Überlappungsanteil.
2. Der Chunk landet bei *jedem* passenden Thema statt beim besten.
3. `STOPPWOERTER` wird nicht angewendet, obwohl importiert und anderswo benutzt
   (`themen.py:487`, `verifikation.py:26`). `_WORT_RE` ist `[a-zA-ZäöüÄÖÜß]{4,}` —
   „eines", „diese", „unter", „werden" matchen alle.

**Akzeptanzkriterien:**
- [ ] Stoppwörter werden beim Titel- und Chunk-Vergleich gefiltert.
- [ ] Mindest-Überlappungsanteil statt nicht-leerer Schnittmenge.
- [ ] Jeder Chunk geht an das **beste** Thema (argmax), nicht an alle; Mehrfachzuordnung
      nur oberhalb einer zweiten, höheren Schwelle.
- [ ] Kennzahlen aus 15 vorher/nachher im Commit dokumentiert.
- [ ] Test: Ein Chunk mit einem Allerweltswort im Titel landet nicht bei allen Themen.
- [ ] Die goldenen Modultests (Mathe 2b 28, KonzMod 14, REST 33) bleiben grün.

---

## 17 · Verschmelzung: Dubletten zu Mehrfachbelegen statt Konkurrenz um Promptplätze

**Parent:** 14
**Typ:** AFK
**Blocked by:** 15

**Was zu bauen:** Inhaltsgleiche Chunks/Aussagen über Quellgrenzen hinweg erkennen und
zu **einem** Eintrag mit mehreren Belegen zusammenziehen (ADR 0009, Stufe 2). Braucht
Embeddings, aber kein LLM — vermutlich der größte Gewinn pro Aufwand.

Heute konkurrieren derselbe Inhalt aus Studienbrief, Folie, Transkript und Altklausur um
dieselben 30 Promptplätze. Nach der Verschmelzung ist die Belegvielfalt einer Aussage
selbst das Relevanzsignal.

**Akzeptanzkriterien:**
- [ ] Lokales multilinguales Embedding-Modell angebunden (ADR 0011: e5/bge-m3 über
      Ollama `/api/embed` oder `sentence-transformers`), als optionales Extra wie `asr`/`folien`.
- [ ] Ähnlichkeitsschwelle am Material geeicht und als benannte Konstante begründet.
- [ ] Verschmolzene Einträge tragen **alle** Quell-`chunk_id`s; kein Beleg geht verloren.
- [ ] Belegvielfalt (Anzahl **verschiedener** Quellarten) fließt in die Relevanz ein.
- [ ] Modell, Dimension, Normalisierung und Präfix stehen im Manifest (ADR 0011:
      Embeddings sind schweigend inkompatibel).
- [ ] Ohne das Extra läuft die Pipeline unverändert weiter (graceful degradation).
- [ ] Test: vier formulierungsverschiedene Chunks derselben Aussage werden zu einem
      Eintrag mit vier Belegen.

---

## 18 · Aussagen-Schicht: Chunk → Aussagen, extraktiv, lokales Modell

**Parent:** 14
**Typ:** AFK
**Blocked by:** 15, 17

**Was zu bauen:** Je Chunk ein Aufruf eines kleinen lokalen Modells, das den Chunk auf
strukturierte Datensätze reduziert (ADR 0009 Stufe 1, Grenze nach ADR 0010). Beantwortet
zum ersten Mal „ist dieser Chunk überhaupt einschlägig?".

```json
{ "chunk_id": "c-0417",
  "art": "definition|satz|verfahren|beispiel|aufgabe|organisatorisch",
  "aussage": "<aus dem Chunk übernommener Kernsatz>",
  "begriffe": ["Normalform", "funktionale Abhängigkeit"],
  "substanziell": true }
```

**Akzeptanzkriterien:**
- [ ] Getrennte Konfiguration für Vorverarbeitungs- und Reasoning-Modell (ADR 0010);
      beides gleichzeitig konfigurierbar.
- [ ] Schema-validiertes JSON; was das Schema verletzt, wird verworfen, nicht repariert.
- [ ] **Rückführbarkeitsprüfung:** `aussage` muss sich mit hoher Wortüberlappung im
      Quellchunk wiederfinden. Was durchfällt, wird verworfen — der Chunk geht dann roh
      weiter, statt eine erfundene Aussage zu erzeugen.
- [ ] Ergebnis in `aussagen.jsonl`; `chunks.jsonl` bleibt unverändert.
- [ ] Gecacht wie die übrigen LLM-Aufrufe (`GecachterLLM`) — ein abgebrochener Lauf
      kostet beim zweiten Anlauf nur die fehlenden Chunks.
- [ ] Fällt das lokale Modell aus, läuft die Pipeline ohne Aussagen-Schicht weiter und
      vermerkt das im Manifest. Kein stiller Qualitätsabfall ohne Spur.
- [ ] Test: ein organisatorischer Chunk (Inhaltsverzeichnis) wird als
      `substanziell: false` aussortiert.
- [ ] Test: eine erfundene Aussage fällt durch die Rückführbarkeitsprüfung.

---

## 19 · Themen per Clustering; Strukturheuristik abbauen

**Parent:** 14
**Typ:** AFK
**Blocked by:** 17, 18

**Was zu bauen:** Der Themenkatalog entsteht aus Clustern der verschmolzenen Aussagen
statt aus Überschriften (ADR 0009 Stufe 3+4). Überschriften werden zum **Prior**
degradiert. Damit fällt die Verzweigung Prosa/Folien/kein-Studienbrief weg — ein Pfad
statt drei.

**Akzeptanzkriterien:**
- [ ] Clustering mit aufs Zielband 15–40 eingeregelter Clusterzahl.
- [ ] Benennung durch **einen** gebündelten Remote-Aufruf (`benenne_themen()`
      wiederverwendet, künftig für alle Dokumentarten — Titel bleiben Reasoning, ADR 0010).
- [ ] Überschriften, wo vorhanden, als Ähnlichkeitsbonus, nicht als Rückgrat.
- [ ] Ein Modul **ohne** Studienbrief läuft durch denselben Pfad; `finde_quellen` bricht
      nicht mehr ab, sondern vermerkt die fehlende Quellart als Materiallücke.
- [ ] Generierungs-Prompt aus dem Themen-Dossier (verschmolzene Aussagen nach
      Belegvielfalt) statt aus 30 Roh-Chunks; Abdeckung messbar gegen 15.
- [ ] **Entfernt:** `MAX_THEMEN_ANTEIL`, `MIN_CHUNKS_FUER_WAECHTER`,
      `_themen_aus_seitenbloecken`, `_themen_aus_foliensatz`, `ZIEL_FOLIEN_JE_THEMA`,
      `MIN_NOMEN_ANTEIL`/`MAX_STREUUNG`, die Zuordnungsschleife in `ordne_chunks_zu`,
      voraussichtlich `PROMPT_QUOTEN`.
- [ ] `CONTEXT.md` **Pflichtquellen**/**Optionalquellen** korrigiert (ADR 0009); ADR 0008
      auf Extraktion eingeschränkt — „Marker bei Foliensätzen konstitutiv" bleibt.
- [ ] Goldene Themenzahlen der bekannten Module bleiben im Zielband; Abweichungen
      begründet statt stillschweigend angepasst.

---

## 20 · Vorberechnete Nachbarschaften im Lernpaket

**Parent:** 14
**Typ:** AFK
**Blocked by:** 17

**Was zu bauen:** Die Kanten, deren Anfrage zur Build-Zeit feststeht, in der Pipeline
rechnen und fertig ausliefern (ADR 0011) — **keine** Vektoren ins Paket, damit der Player
seine einzige Laufzeit-Abhängigkeit (`katex`) behält.

| Kante | Nutzen im Player |
| --- | --- |
| Thema ↔ Thema | verwechselbare Themen verzahnen (ADR 0006; Interleaving aus `BACKLOG.md`) |
| Frage → Lehrblock | nach falscher Diagnosefrage „genau das steht hier" |
| Lehrblock → weitere Belegstellen | „dazu sagt die Vorlesung bei Min. 21:40 noch das hier" |
| Thema → Altklausuraufgabe | ersetzt `_titel_naehe()`/`_wortnah()` (`relevanz.py:148`) |

**Akzeptanzkriterien:**
- [ ] `nachbarn.json` im Datei-Vertrag ergänzt, additiv (`schema_version` bleibt 1).
- [ ] Thema→Altklausuraufgabe ersetzt die Wortnähe-Handregeln in `relevanz.py`.
- [ ] Der Player bleibt ohne neue Laufzeit-Abhängigkeit; fehlt die Datei, verhält er sich
      wie heute.
- [ ] Test: „Structured Query Language" und „Die Datenbanksprache SQL" werden als
      benachbart erkannt.

---

## 21 · Tutor: BM25 plus LLM-Query-Expansion

**Parent:** 14
**Typ:** AFK

**Was zu bauen:** Ein vorgeschalteter LLM-Aufruf schreibt die Nutzerfrage in
Kursvokabular um, *dann* läuft BM25 (ADR 0011). Fängt den Fall, in dem Lexik versagt —
der Nutzer kennt den gesuchten Fachbegriff nicht — ohne ein Byte Modell im Player.
Beispiel: „was war nochmal das mit den Tabellen, die man nicht weiter zerlegen kann" →
„Normalisierung, erste Normalform, atomare Attributwerte". Naht unverändert:
`erstelleIndex(chunks)` in `player/server/bm25.js`.

**Akzeptanzkriterien:**
- [ ] Expansion vor der BM25-Suche; die ursprüngliche Frage bleibt Teil der Anfrage.
- [ ] Schlägt der Aufruf fehl, läuft die Suche unverändert mit der Rohfrage
      (kein harter Fehler im Tutormodus).
- [ ] Ein zusätzlicher Aufruf je Frage, nicht je Treffer.
- [ ] Test: eine umschreibende Frage ohne Fachbegriff findet den richtigen Chunk,
      der mit Rohfrage nicht gefunden wird.
