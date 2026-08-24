"""Themenkatalog-Aufbau und Zielformat-Erkennung (Issues #21, #24)."""
from lernpaket_pipeline.pipeline import erzeuge_lernpaket
from lernpaket_pipeline.themen import (MAX_THEMEN_ANTEIL, ZIEL_MAX, ZIEL_MIN,
                                       baue_themenkatalog, ordne_chunks_zu)
from lernpaket_pipeline.vertrag import Chunk
from lernpaket_pipeline.zielformat import erkenne_zielformat


def test_themen_aus_ueberschriften(modul_dir):
    paket = erzeuge_lernpaket(modul_dir)
    titel = [t.titel for t in paket.themen]
    assert any("Komplexitaet" in t for t in titel)
    assert any("Quicksort" in t for t in titel)
    for thema in paket.themen:
        assert thema.belege, "Jedes Thema traegt Belege"


def test_zielformat_aus_altklausur(modul_dir_mit_optionalquellen):
    """Altklausur ist das stärkste Relevanzsignal; MC-Indikatoren → Vorschlag mc."""
    paket = erzeuge_lernpaket(modul_dir_mit_optionalquellen)
    assert paket.manifest.zielformat.vorschlag == "mc"
    assert "altklausur" in paket.manifest.zielformat.begruendung


def test_zielformat_default_ohne_signale(modul_dir):
    paket = erzeuge_lernpaket(modul_dir)
    assert paket.manifest.zielformat.vorschlag == "freitext"


def test_zielformat_rangfolge_der_quellen():
    """Altklausur schlägt Übung schlägt Vorlesung."""
    chunks = [
        Chunk(id="c-0001", quelle="vorlesung", position="Min. 1:00",
              text="Berechnen Sie die Laufzeit. Berechnen Sie den Speicher."),
        Chunk(id="c-0002", quelle="altklausur", position="S. 1",
              text="Beweisen Sie das Master-Theorem. Zeigen Sie, dass die Schranke gilt."),
    ]
    assert erkenne_zielformat(chunks).vorschlag == "beweis"
    assert erkenne_zielformat([chunks[0]]).vorschlag == "rechnen"


def test_ueberschrift_trotz_fettung_des_dokument_parsers():
    """Marker setzt Abschnittsüberschriften als "## **2.5.1 Polynome**".

    Ohne tolerierte Auszeichnung blieb die gesamte Kapitelstruktur unsichtbar
    und der Katalog fiel auf Fließtext-Fragmente zurück (Wortlaut aus dem
    Studienbrief Mathe 2a).
    """
    # Gleiche Gliederungsebene, damit die Granularitäts-Wahl nichts wegfasst.
    chunks = [Chunk(id="c-0", quelle="studienbrief", position="S. 1", text=(
        "## **1.4 Der Gauß-Algorithmus**\n\nText dazu.\n"
        "## **2.5 Elementare Funktionen**\n\nMehr Text.\n"))]
    titel = [t.titel for t in baue_themenkatalog(chunks)]
    assert "Der Gauß-Algorithmus" in titel
    assert "Elementare Funktionen" in titel
    assert not any("*" in t for t in titel), "Fettung darf nicht im Titel landen"


def test_scheinstruktur_faellt_auf_seitenbloecke_zurueck():
    """Ein einzelnes Thema darf nicht den ganzen Studienbrief schlucken.

    Wortlaut aus REST: Folien tragen keine nummerierten Überschriften, aber die
    Assembler-Beispielfolie liefert Zeilen wie "LOAD ACC, 255", die die
    Überschriften-Erkennung für eine Gliederung hält. Ungebremst entstanden so
    8 Schein-Themen, von denen eines 98 % aller Chunks besaß — der
    Seitenblock-Fallback ist dann ehrlicher als die Scheinstruktur.
    """
    chunks = [Chunk(id="c-0000", quelle="studienbrief", position="S. 1",
                    text="Kapitel 1 - Inhalt der Vorlesung")]
    chunks.append(Chunk(id="c-0001", quelle="studienbrief", position="S. 2", text=(
        "LOAD ACC, 255\nINPUT ACC, 6\nJUMP NC, 4\nOUTPUT ACC, 7\nDATA: 250\n")))
    # Der weitaus größte Teil des Dokuments folgt erst danach.
    chunks += [Chunk(id=f"c-{i:04d}", quelle="studienbrief", position=f"S. {i}",
                     text="Fließtext ohne jede Gliederung. " * 20)
               for i in range(2, 60)]
    themen = baue_themenkatalog(chunks)
    anteile = [len(v) for v in ordne_chunks_zu(themen, chunks).values()]
    assert max(anteile) / len(chunks) <= MAX_THEMEN_ANTEIL, (
        "kein Thema darf den Studienbrief schlucken")
    assert len(themen) >= ZIEL_MIN, "Fallback muss ein volles Zielband liefern"


def test_echte_gliederung_wird_nicht_vom_waechter_verworfen():
    """Gegenprobe: eine belastbare Gliederung überlebt den Wächter.

    Konzeptionelle Modellierung liegt mit 56,7 % Chunk-Anteil im größten Thema
    dicht unter der Schwelle — ohne diese Grenze fiele ein gesundes Modul auf
    Seitenblöcke zurück und verlöre seine echten Kapiteltitel.
    """
    chunks = []
    for kapitel in range(1, 6):
        chunks.append(Chunk(id=f"c-{kapitel * 10:04d}", quelle="studienbrief",
                            position=f"S. {kapitel * 10}",
                            text=f"## **{kapitel}.1 Echtes Kapitel {kapitel}**\n\nInhalt."))
        chunks += [Chunk(id=f"c-{kapitel * 10 + i:04d}", quelle="studienbrief",
                         position=f"S. {kapitel * 10 + i}", text="Fließtext. " * 30)
                   for i in range(1, 6)]
    titel = [t.titel for t in baue_themenkatalog(chunks)]
    assert any("Echtes Kapitel 1" in t for t in titel)
    assert any("Echtes Kapitel 5" in t for t in titel)


def test_mehrfach_vergebene_titel_werden_qualifiziert():
    """Jedes Kapitel hat eine "Einführung" — sonst stünden sie ununterscheidbar da."""
    chunks = [Chunk(id="c-0", quelle="studienbrief", position="S. 1", text=(
        "## **1.2 Einführung**\n\nErstes.\n"
        "## **2.2 Einführung**\n\nZweites.\n"
        "## **3.4 Kurvendiskussion**\n\nDrittes.\n"))]
    titel = [t.titel for t in baue_themenkatalog(chunks)]
    assert "1.2 Einführung" in titel and "2.2 Einführung" in titel
    # Eindeutige Titel bleiben unangetastet.
    assert "Kurvendiskussion" in titel
    assert len(titel) == len(set(titel)), "Titel müssen unterscheidbar sein"


def _folie(nummer, dokument, zeilen):
    return Chunk(id=f"c-{dokument}-{nummer:03d}", quelle="studienbrief",
                 position=f"{dokument}, S. {nummer}", text="\n".join(zeilen))


def test_folien_themen_aus_kapitel_und_kopfzeilen():
    """Foliensätze gliedern sich über Titelfolie + Kopfzeilenwechsel (ADR 0008)."""
    chunks = [_folie(1, "REST_4.2_Bool", ["Rechnerstrukturen", "Boolesche Algebra",
                                          "Kapitel 4.2", "Prof. Dr. Teich", "REST"])]
    chunks += [_folie(n, "REST_4.2_Bool", ["Schaltalgebraische Regeln", "REST",
                                           f"R{n}a a + 0 = a"]) for n in range(2, 20)]
    chunks += [_folie(n, "REST_4.2_Bool", ["De Morgansche Regeln", "REST",
                                           f"Beispiel {n}"]) for n in range(20, 38)]
    themen = baue_themenkatalog(chunks, folien_dokumente={"REST_4.2_Bool"})
    titel = [t.titel for t in themen]
    assert any("Schaltalgebraische Regeln" in t for t in titel)
    assert any("De Morgansche Regeln" in t for t in titel)
    # Der wiederkehrende Modulname ist Rauschen, kein Thementitel.
    assert not any(t.strip() == "REST" for t in titel)
    assert all(t.belege for t in themen)


def test_folien_granularitaet_bleibt_im_zielband():
    """37 Folien mit 37 Kopfzeilen dürfen keine 37 Themen werden."""
    chunks = [_folie(n, "Deck", [f"Abschnitt {n}", f"Inhalt {n}"]) for n in range(1, 38)]
    themen = baue_themenkatalog(chunks, folien_dokumente={"Deck"})
    assert len(themen) <= ZIEL_MAX
    assert len(themen) < 37, "Abschnitte müssen zu Themen gebündelt werden"


def test_prosa_bleibt_unberuehrt_ohne_folien_angabe():
    """Ohne folien_dokumente läuft exakt der bisherige Überschriften-Pfad."""
    chunks = [Chunk(id="c-0", quelle="studienbrief", position="S. 1", text=(
        "## **1.4 Der Gauß-Algorithmus**\n\nText.\n"
        "## **2.5 Elementare Funktionen**\n\nMehr Text.\n"))]
    assert [t.titel for t in baue_themenkatalog(chunks)] == \
           [t.titel for t in baue_themenkatalog(chunks, folien_dokumente=set())]


def test_folien_titel_ohne_markdown_auszeichnung():
    """Der Dokument-Parser setzt Folien-Kopfzeilen als "## Titel".

    Wortlaut aus einem Marker-Lauf über REST_2.1: Ohne Abräumen stand
    "## Nachricht und Signal" als Thementitel im Player.
    """
    chunks = [_folie(1, "D", ["Rechnerstrukturen", "Kapitel 2.1"])]
    chunks += [_folie(n, "D", ["## Nachricht und Signal", f"Inhalt {n}"])
               for n in range(2, 20)]
    titel = [t.titel for t in baue_themenkatalog(chunks, folien_dokumente={"D"})]
    assert any("Nachricht und Signal" in t for t in titel)
    assert not any("#" in t for t in titel), titel
