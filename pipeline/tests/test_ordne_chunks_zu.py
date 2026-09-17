"""ordne_chunks_zu: Stoppwortfilter, Mindestquote, Argmax statt Streuung (Issue #46)."""
from lernpaket_pipeline.themen import ordne_chunks_zu
from lernpaket_pipeline.vertrag import Beleg, Chunk, Thema


def test_allerweltswort_im_titel_faengt_nicht_alle_themen():
    """Regressionstest für Befund 3: "eines" steckt in beiden Titeln, ist aber
    ein Stoppwort — ein Chunk, der nur dieses eine Wort teilt, darf bei keinem
    der beiden Themen landen (vorher: bei beiden)."""
    themen = [
        Thema(id="t-01", titel="Die Bedeutung eines Modells"),
        Thema(id="t-02", titel="Die Interpretation eines Graphen"),
    ]
    chunk = Chunk(id="c-01", quelle="vorlesung", position="VL01, Min. 1:00",
                  text="Dies ist eines der einfachsten Beispiele überhaupt.")
    zuordnung = ordne_chunks_zu(themen, [chunk])
    assert zuordnung["t-01"] == []
    assert zuordnung["t-02"] == []


def test_bestes_thema_gewinnt_statt_alle_passenden():
    """Ein Chunk, der nur "Normalform" nennt, passt zu t-01 vollständig (1/1)
    und zu t-02 nur zur Hälfte (1/2) — er geht ausschließlich an t-01."""
    themen = [
        Thema(id="t-01", titel="Normalform"),
        Thema(id="t-02", titel="Normalform Grundlagen"),
    ]
    chunk = Chunk(id="c-01", quelle="folie", position="F. 1",
                  text="Diese Folie behandelt die Normalform im Detail.")
    zuordnung = ordne_chunks_zu(themen, [chunk])
    assert zuordnung["t-01"] == [chunk]
    assert zuordnung["t-02"] == []


def test_mehrfachzuordnung_nur_oberhalb_der_hoeheren_schwelle():
    """Drei Themen mit steigender Titellänge, ein Chunk erwähnt nur "Hashing":

    - t-01 ("Hashing", 1 Wort): 1/1 = 1.0 → bestes Thema, wird zugeordnet.
    - t-02 (3 von 4 Wörtern treffen): 0.75 → über der Mehrfachschwelle, auch
      wenn nicht das beste Thema — wird zusätzlich zugeordnet.
    - t-03 (nur 1 von 3 Wörtern trifft): 0.33 → unter der Mindestquote, fällt
      komplett raus.
    """
    themen = [
        Thema(id="t-01", titel="Hashing"),
        Thema(id="t-02", titel="Hashing Kollisionsbehandlung Verfahren Grundlagen"),
        Thema(id="t-03", titel="Hashing Anwendungsfall Beispielszenario"),
    ]
    chunk = Chunk(id="c-01", quelle="vorlesung", position="VL02, Min. 3:00",
                  text="Beim Hashing braucht jedes Verfahren eine "
                       "Kollisionsbehandlung, sonst scheitert die Zuordnung.")
    zuordnung = ordne_chunks_zu(themen, [chunk])
    assert zuordnung["t-01"] == [chunk]
    assert zuordnung["t-02"] == [chunk]
    assert zuordnung["t-03"] == []


def test_studienbrief_zuordnung_unveraendert():
    """Die sequenzielle Studienbrief-Zuordnung ist von der Wortüberlappung
    unberührt — nur die "andere"-Schleife (Vorlesung/Folie) hat sich geändert."""
    themen = [
        Thema(id="t-01", titel="Erstes Thema",
              belege=[Beleg(quelle="studienbrief", position="S. 1", chunk_id="c-01")]),
        Thema(id="t-02", titel="Zweites Thema",
              belege=[Beleg(quelle="studienbrief", position="S. 2", chunk_id="c-02")]),
    ]
    chunks = [
        Chunk(id="c-01", quelle="studienbrief", position="S. 1", text="Beliebiger Inhalt."),
        Chunk(id="c-02", quelle="studienbrief", position="S. 2", text="Weiterer Inhalt."),
    ]
    zuordnung = ordne_chunks_zu(themen, chunks)
    assert zuordnung["t-01"] == [chunks[0]]
    assert zuordnung["t-02"] == [chunks[1]]
