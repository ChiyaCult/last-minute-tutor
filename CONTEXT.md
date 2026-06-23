# Klausur-Lernpaket-Generator

Ein einmalig pro Modul laufendes Offline-Werkzeug, das aus den Materialien eines Moduls ein kompaktes Lernpaket erzeugt, mit dem sich der Nutzer in einem knappen Fenster (3 Tage bis 2 Wochen, wenige Stunden pro Tag) vor den Klausuren vorbereiten kann — meist für 2–3 Klausuren am selben Tag, die unabhängig voneinander aufbereitet werden. Gebaut für ein Fernstudium mit 20+ kommenden Modulen, also als wiederverwendbare Pipeline. Der Nutzer hat starkes Software-Grundwissen (12 Jahre Praxis), lernt das Semester über nicht aktiv mit, hört die Vorlesungen bewusst nicht selbst an und will kurz vor der Prüfung gezielt das Klausurrelevante aufholen. Das Tool muss alle Inhalte selbst aus den Rohmaterialien ziehen — es darf sich nicht auf Mitschriften oder Vorwissen des Nutzers zum Stoff verlassen.

## Language

**Lernpaket**:
Das fertige Ergebnis-Artefakt eines Moduls: verdichtete, klausurfokussierte Lehrblöcke plus format-passende Quizfragen. Der Inhalt wird einmalig vorab erzeugt und ist statisch; konsumiert wird er über einen interaktiven Player, der das Diagnosequiz auswertet und adaptiv Lehrtiefe freischaltet. Der Kern ist kostenfrei und offline nutzbar; ein optionaler Tutormodus erlaubt Live-Rückfragen.
_Avoid_: Zusammenfassung, Skript, Lernunterlagen

**Aufbereitung**:
Die einmalige Offline-Phase, die aus den Rohmaterialien das Lernpaket erzeugt. Darf zeitlich (~1–2 Wochen vor Klausur) gestreckt laufen; Qualität geht vor Geschwindigkeit.
_Avoid_: Vorverarbeitung, Verarbeitung, Preprocessing

**Lernphase**:
Der Zeitraum vor den Klausuren (typisch 3 Tage bis 2 Wochen, nur wenige Stunden pro Tag), in dem der Nutzer mit den fertigen Lernpaketen arbeitet — in der Regel für 2–3 Klausuren, die am selben Tag geschrieben werden. Die Module werden unabhängig voneinander aufbereitet und abgefragt; der Nutzer teilt sein Tagesbudget selbst auf.
_Avoid_: Vorbereitung (mehrdeutig — meint mal Aufbereitung, mal Lernphase)

**Wiederholungsplan**:
Pro Modul (unabhängig) verteilt der Player die Themen über die verfügbaren Tage bis zur Klausur (Spaced Repetition) und holt schwache Themen gezielt mehrfach zurück. Kein modulübergreifender Scheduler — bei 3 Tagen mehr Triage, bei 2 Wochen echtes verteiltes Wiederholen.
_Avoid_: Lernplan (impliziert fälschlich modulübergreifende Orchestrierung), Stundenplan

**Relevanzsignal**:
Hinweise darauf, was klausurrelevant ist — verteilt über Altklausuren, Übungsaufgaben (im Studienbrief oder als Extra-PDF) und vor allem mündliche Betonungen der Professoren in den Vorlesungs-MP4s. Ausdrücklich NICHT der Studienbrief selbst, der die unsortierte Obermenge aller Inhalte ist.
_Avoid_: Wichtigkeit, Gewichtung

**Pflichtquellen**:
Die Materialarten, die in jedem Modul garantiert vorliegen: Studienbrief (PDF, ~400 Seiten) und Vorlesungen (MP4). Die Pipeline darf ihr Vorhandensein voraussetzen.
_Avoid_: Hauptmaterial, Kernmaterial

**Optionalquellen**:
Variable, modulabhängige Materialien: Altklausuren und zusätzliche Übungs-PDFs. Die Pipeline muss auch ohne sie ein brauchbares Lernpaket liefern (graceful degradation), nutzt sie aber als starkes Relevanzsignal, wenn vorhanden.
_Avoid_: Zusatzmaterial, Bonusmaterial

**Zielformat**:
Das Prüfungsformat (z. B. Multiple Choice, Rechenaufgabe, Freitext-Definition, Beweis), auf das das Lernpaket eines Moduls optimiert wird. Pro Modul per Erkennen-dann-Bestätigen festgelegt: Das Tool schlägt aus dem stärksten Relevanzsignal ein Format vor, der Nutzer bestätigt oder korrigiert.
_Avoid_: Prüfungsform, Klausurtyp

**Themenkatalog**:
Die vollständige Liste der klausurrelevanten Themen eines Moduls, abgeleitet aus den Relevanzsignalen. Legt die Abdeckung fest (immer vollständig); die Lehrtiefe pro Thema ist davon getrennt und adaptiv.
_Avoid_: Stoffliste, Themenliste, Lehrplan

**Thema**:
Die atomare inhaltliche Einheit, um die sich Diagnosequiz und adaptive Lehrtiefe drehen — ein abgrenzbares Konzept bzw. Lernziel, grob auf Abschnitts-/Unterkapitelebene (Größenordnung 15–40 pro Modul). Die Granularität skaliert das Tool je nach Stoffmenge automatisch (mittlere Granularität als Default).
_Avoid_: Kapitel, Lerneinheit

**Diagnosequiz**:
Das einleitende Quiz der Lernphase, das misst, welche Themen des Themenkatalogs der Nutzer bereits sicher beherrscht. Doppelfunktion: Es kalibriert die adaptive Lehrtiefe (statt Vorwissen zu raten) und ist selbst schon Übung. Lücken schalten gezielte Lehrinhalte frei.
_Avoid_: Einstufungstest, Eingangstest

**Player**:
Die interaktive Konsum-Oberfläche der Lernphase, die das statische Lernpaket adaptiv ausspielt: Diagnosequiz auswerten, Lehrtiefe freischalten, den Wiederholungsplan fahren, Fortschritt speichern und den Tutormodus anbieten. Läuft lokal.
_Avoid_: App, Viewer, Frontend

**Tutormodus**:
Der optionale Laufzeitmodus während der Lernphase, in dem der Nutzer freie Rückfragen stellt und gezielt zusätzliche Lehrinhalte nachgenerieren lässt, wenn etwas unklar bleibt. Einziger Teil des Tools mit Laufzeitkosten und damit der einzige Ort, an dem sich lokal-vs-remote überhaupt stellt.
_Avoid_: Chatmodus, Frag-mich-Modus

**Beleg**:
Quellverweis (z. B. Studienbrief S. X, Vorlesung Min. Y), den jeder Lehrblock und jede Quizfrage verpflichtend trägt. Macht jede Aussage nachprüfbar; der Generator darf nur Belegbares behaupten.
_Avoid_: Quelle, Referenz, Zitat

**Materiallücke**:
Ein Punkt, an dem die Materialien schweigen oder sich widersprechen. Das Tool markiert ihn ausdrücklich, statt eine Antwort zu erfinden — ein Signal für den Tutormodus oder einen Blick ins Original.
_Avoid_: Unklarheit, Wissenslücke
