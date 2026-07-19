# Fensteradaptive Eigenlogik statt SM-2/FSRS im Wiederholungsplan

Löst offenen Punkt Nr. 1. Der Wiederholungsplan nutzt eine schlanke, fenstergerechte
Eigenlogik mit zwei Modi statt eines Standard-SRS-Verfahrens:

- **Triage** (≤ 4 Tage bis zur Klausur): Jeden Tag stehen alle Themen an, sortiert
  nach Priorität `0.7 · Schwäche + 0.3 · Relevanz`. Bei 3 Tagen zählt Wiederholung
  von allem mehr als perfekte Verteilung.
- **Spacing** (> 4 Tage): komprimierte, nach Themen-Stärke gestaffelte Intervalle
  (schwach: Tag 0, 1, 3, 6, 10, 15; mittel: 0, 2, 6, 12; beherrscht: nur Auffrischung),
  in das Fenster gestaucht. Jedes Thema kommt am Vortag der Klausur zurück.

Die Themen-Stärke kommt aus einem trägen gleitenden Mittelwert der Antworten
(SQLite, `themen_stand`), nicht aus SRS-Ease-Faktoren.

## Considered Options

Verworfen: **SM-2** und **FSRS**. Beide modellieren Vergessenskurven über Wochen
bis Monate; im 3-Tage-bis-2-Wochen-Fenster degenerieren ihre Intervalle ohnehin zu
"täglich bis alle paar Tage", und FSRS braucht Trainingsdaten, die ein Einzelnutzer
mit 2–3 Klausuren nie liefert. Der eigentliche Mehrwert der Standardverfahren
(Langzeit-Retention) ist hier explizit kein Ziel — nach der Klausur darf vergessen
werden. Die Eigenlogik ist dafür trivial testbar (reine Funktion) und kippt
nachweisbar in Triage.

## Consequences

Der Plan ist eine reine Funktion aus (Themen, Stand, Heute, Klausurdatum) — kein
persistierter Scheduler-Zustand außer der Themen-Stärke. Umgesetzt in
`player/server/plan.js`, Verhalten festgeschrieben in `player/tests/plan.test.js`.
