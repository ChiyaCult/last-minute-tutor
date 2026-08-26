# Dokumentarten der Pflichtquellen: Prosa-Studienbrief vs. Foliensatz

Die Pflichtquelle "Studienbrief" liegt nicht in jedem Modul als Prosa vor. Das Modul
REST (Rechnerstrukturen) liefert statt eines ~400-seitigen Hefts **16 PowerPoint-
Foliensätze** mit 435 Folien. Die Aufbereitung erkennt die **Dokumentart je Datei**
und verzweigt nur dort, wo sich die Verarbeitung tatsächlich unterscheidet.

## Erkennung

Zwei Merkmale zusammen, beide aus dem PDF selbst:

| | Seitenformat | Median Zeichen/Seite |
| --- | --- | --- |
| REST (Foliensatz) | 720×540, **quer** | 308 |
| Mathe 2a / 2b / KonzMod (Prosa) | 595×842, hoch | 1692 / 1896 / 2058 |

Querformat **und** unter `MAX_FOLIEN_ZEICHEN` Zeichen je Seite → Foliensatz, sonst
Prosa. Einzeln taugt keines der beiden Merkmale (A4-Handouts und Querformat-Prosa
gibt es), zusammen trennen sie um Faktor 5. Die erkannte Art steht im Manifest
(`quellen[].dokumentart`) und ist per `--dokumentart` überschreibbar — Erkennen-dann-
Bestätigen wie beim **Zielformat**.

Die Entscheidung fällt **je Datei**, nicht je Modul: Ein Modul darf einen Prosa-
Studienbrief *und* ein Folien-Beiheft mitbringen. Ein modulweites Flag könnte diesen
Fall nicht abbilden, und er kostet in der Umsetzung nichts extra, weil `finde_quellen`
ohnehin eine Liste je Kategorie liefert.

## Was sich je Art unterscheidet

| Stelle | Prosa | Foliensatz |
| --- | --- | --- |
| Themen-Kandidaten | nummerierte Überschriften | Kapitel der Titelfolie + gebündelte Folien-Kopfzeilen |
| Abbildungen | Seiten mit `Abb. X.Y:`-Unterschrift | jede Folie |
| Formelerfassung | Marker empfohlen | Marker **erforderlich** (s. u.) |

Alles andere bleibt geteilt: Quellenfindung, ASR, Optionalquellen, Zielformat,
Chunking, Generierung, Verifikation, Datei-Vertrag, Player.

## Marker ist bei Foliensätzen konstitutiv, nicht optional

ADR 0004 führt Marker als eine von drei austauschbaren Optionen. Für Foliensätze gilt
das nicht mehr: Folien setzen die Negation als **Überstrich**, und der existiert in der
PDF-Textebene schlicht nicht. Gemessen an `REST_4.2_Bool_Algebra`, Folie 6:

```
Textebene (pypdf):  (a ∙ b)   =  a + b        ← mathematisch falsch
                    ____ _ _
Marker:             $$\overline{(a + b)} = \overline{a} \cdot \overline{b}$$
```

Ohne Marker wären die Kapitel zur Schaltalgebra nicht bloß dünn, sondern **falsch** —
und zwar unauffällig falsch. Deshalb bricht die Aufbereitung bei erkanntem Foliensatz
ohne verfügbaren Dokument-Parser mit klarer Meldung ab, statt wie sonst degradiert
weiterzulaufen. Ein Lernpaket, dessen Formeln lautlos falsch sind, ist schlechter als
keines: Es kostet Lernzeit und schadet in der Klausur.

## Marker ist nicht hinreichend — Reststriche werden markiert

Auf denselben 9 Folien rekonstruiert Marker 21 Überstriche korrekt, verliert aber 8.
Er scheitert dort, wo ein einzelner Strich über einem einzelnen Buchstaben in einer
locker gesetzten Regeltabelle steht (`R8a a + a = 1 \_`, korrekt wäre `a + ā = 1`).
Solche Reste sind an dem verwaisten `\_` **erkennbar** und werden als **Materiallücke**
vermerkt (ADR 0003: markieren statt erfinden), statt still weitergereicht zu werden.

## Consequences

Die Themen-Granularität skaliert bei Foliensätzen über Folienzahl statt über
Überschriften-Ebenen: aufeinanderfolgende Abschnitte eines Kapitels werden gebündelt,
bis `ZIEL_FOLIEN_JE_THEMA` erreicht ist. Für REST ergibt das 33 Themen — die naiven
Ebenen liefern 16 (Kapitel, zu grob) bzw. 240 (Abschnitte, zu fein).

Die Folien-Kopfzeile trägt den Themen-Titel nur als **Rückfallebene**; benannt wird im
Generierungsschritt vom LLM, das die Chunks der Gruppe ohnehin sieht — in **einem
gebündelten Aufruf** für alle Themen, weil das billiger ist als einer je Thema und das
Modell die Titel so gegeneinander abgrenzen kann. Vorschläge werden am selben Maßstab
geprüft wie Kopfzeilen; was ihn nicht besteht, wird verworfen, und ein gescheiterter
Aufruf lässt die bisherigen Titel stehen. Kopfzeilen allein liefern sonst Titel wie
"| $k$ | $PI$ |" oder "8. Schritt:" (gemessen am REST-Lauf: 10 von 37 Titeln unbrauchbar,
nach Härtung der Kopfzeilen-Erkennung noch 2).

Der Prosa-Pfad bleibt unverändert; die bestehenden Tests sind sein Regressionsschutz,
ergänzt um goldene Themenzahlen für Mathe 2b (28) und Konzeptionelle Modellierung (14).
