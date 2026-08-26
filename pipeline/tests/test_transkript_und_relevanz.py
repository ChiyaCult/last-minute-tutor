"""Vorlesungs-Audio → Transkript → Themenkatalog (Issue #22) und
Relevanzsignal aus dem Transkript (Issue #23)."""
from pathlib import Path

import pytest

from lernpaket_pipeline.chunks import chunks_aus_transkript
from lernpaket_pipeline.extraktion.audio import FasterWhisperTranskribierer
from lernpaket_pipeline.pipeline import erzeuge_lernpaket
from lernpaket_pipeline.relevanz import finde_relevanz_marker

from .conftest import FakeTranskribierer


class _FakeWhisperModel:
    """Simuliert fehlende CUDA-Libs: schlägt fehl, außer auf CPU."""

    def __init__(self, modell, device, compute_type):
        self.aufrufe = _FakeWhisperModel.aufrufe
        self.aufrufe.append((device, compute_type))
        if device != "cpu":
            raise RuntimeError(
                "Library libcublas.so.12 is not found or cannot be loaded")

    aufrufe: list = []


def test_asr_faellt_bei_fehlendem_cuda_auf_cpu_zurueck(monkeypatch):
    _FakeWhisperModel.aufrufe = []
    tr = FasterWhisperTranskribierer(device="auto")
    monkeypatch.setattr(tr, "_nutzt_gpu", lambda: True)  # CUDA-Gerät gemeldet …
    modell = tr._lade_modell(_FakeWhisperModel)
    assert isinstance(modell, _FakeWhisperModel)
    # … die Libs fehlen aber: erst der auto-Versuch, dann der CPU-Fallback.
    assert _FakeWhisperModel.aufrufe == [("auto", "auto"), ("cpu", "int8")]


def test_asr_waehlt_auf_cpu_int8_statt_auto():
    """`auto` quantisiert large-v3 auf CPU minutenlang um — int8 lädt in Sekunden."""
    _FakeWhisperModel.aufrufe = []
    tr = FasterWhisperTranskribierer(device="cpu")
    tr._lade_modell(_FakeWhisperModel)
    assert _FakeWhisperModel.aufrufe == [("cpu", "int8")]


def test_asr_ohne_gpu_bleibt_auto_geraet_aber_int8(monkeypatch):
    """Ohne CUDA-Gerät löst device=auto auf CPU auf — dann gilt int8."""
    _FakeWhisperModel.aufrufe = []
    tr = FasterWhisperTranskribierer(device="auto")
    monkeypatch.setattr(tr, "_nutzt_gpu", lambda: False)
    tr._lade_modell(_FakeWhisperModel)
    assert _FakeWhisperModel.aufrufe[0] == ("auto", "int8")


def test_expliziter_compute_type_schlaegt_den_standard():
    _FakeWhisperModel.aufrufe = []
    tr = FasterWhisperTranskribierer(device="cpu", compute_type="float32")
    tr._lade_modell(_FakeWhisperModel)
    assert _FakeWhisperModel.aufrufe == [("cpu", "float32")]


def test_asr_cpu_explizit_ohne_endlos_fallback():
    class _ImmerFehler:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    tr = FasterWhisperTranskribierer(device="cpu")
    with pytest.raises(RuntimeError, match="boom"):
        tr._lade_modell(_ImmerFehler)  # device=cpu → kein Fallback, Fehler durchreichen


def test_asr_device_aus_umgebung(monkeypatch):
    monkeypatch.setenv("LERNPAKET_ASR_DEVICE", "cuda")
    monkeypatch.setenv("LERNPAKET_ASR_COMPUTE", "float16")
    tr = FasterWhisperTranskribierer()
    assert tr.device == "cuda" and tr.compute_type == "float16"


def test_transkript_chunks_tragen_zeitstempel(fake_transkribierer):
    transkript = fake_transkribierer.transkribiere(Path("vorlesung-01.mp4"))
    assert all(s.ende > s.start for s in transkript.segmente)
    chunks = chunks_aus_transkript(transkript)
    assert chunks, "Transkript muss Chunks liefern"
    assert chunks[0].quelle == "vorlesung"
    # Beleg muss die Vorlesung benennen, nicht nur die Minute: bei einem
    # Dutzend Vorlesungen wäre "Min. 0:00" allein nicht nachschlagbar.
    assert chunks[0].position == "vorlesung-01, Min. 0:00"


def test_transkript_erzeugt_neue_themen(modul_dir_mit_vorlesung, fake_transkribierer):
    """Akzeptanz #22: Transkriptinhalt erzeugt/ergänzt Themen im Themenkatalog."""
    paket = erzeuge_lernpaket(modul_dir_mit_vorlesung, transkribierer=fake_transkribierer)
    titel = [t.titel.lower() for t in paket.themen]
    # 'Hashtabellen' kommt nur in der Vorlesung vor und muss als Thema auftauchen.
    assert any("hashtabellen" in t for t in titel)
    hash_thema = next(t for t in paket.themen if "hashtabellen" in t.titel.lower())
    assert any(b.quelle == "vorlesung" for b in hash_thema.belege)


def test_relevanz_marker_werden_gefunden(fake_transkribierer):
    transkript = fake_transkribierer.transkribiere(Path("v.mp4"))
    treffer = finde_relevanz_marker(chunks_aus_transkript(transkript))
    assert any("klausurrelevant" in t.satz.lower() for t in treffer)
    assert all(t.chunk_id and t.position for t in treffer)


def test_marker_priorisiert_markierte_themen(modul_dir_mit_vorlesung, fake_transkribierer):
    """Akzeptanz #23: Transkript mit Markern priorisiert die markierten Themen."""
    paket = erzeuge_lernpaket(modul_dir_mit_vorlesung, transkribierer=fake_transkribierer)
    landau = next(t for t in paket.themen if "landau" in t.titel.lower())
    mergesort = next(t for t in paket.themen if "mergesort" in t.titel.lower())
    assert landau.relevanz > mergesort.relevanz
    assert "transkript-marker" in landau.relevanzsignale
    assert any(b.quelle == "vorlesung" for b in landau.belege)


def test_ohne_transkribierer_laeuft_pipeline_trotzdem(modul_dir_mit_vorlesung):
    paket = erzeuge_lernpaket(modul_dir_mit_vorlesung)
    assert paket.themen, "Pipeline muss ohne ASR-Adapter durchlaufen"


def test_modell_wird_nur_einmal_geladen():
    """Pro Video neu laden hieße: Ladezeit + HuggingFace-Abfrage je Vorlesung."""
    _FakeWhisperModel.aufrufe = []
    tr = FasterWhisperTranskribierer(device="cpu")
    erstes = tr._lade_modell(_FakeWhisperModel)
    zweites = tr._lade_modell(_FakeWhisperModel)
    assert erstes is zweites
    assert _FakeWhisperModel.aufrufe == [("cpu", "int8")]


def test_redefuellsel_wird_nicht_zum_thema():
    """Häufigste Transkriptwörter sind Füllsel, keine Themen.

    Wortlaut aus dem REST-Lauf: "Bedeutet" (339x), "Nämlich" (167x) und
    "Punkte" (257x) standen als Themen im Katalog. Erste zwei sind Verben bzw.
    Adverbien (mitten im Satz klein), "Punkte" ist ein Nomen, zieht sich aber
    durch die ganze Vorlesung statt zu einem Thema zu gehören.
    """
    from lernpaket_pipeline.themen import ergaenze_aus_transkript
    from lernpaket_pipeline.vertrag import Chunk, Thema
    chunks = []
    for i in range(50):
        # Füllsel in jedem Chunk, Fachbegriff nur in zweien — dreimal genannt
        # (min_nennungen), aber mit geringer Streuung.
        text = "Das bedeutet hier etwas und nämlich auch Punkte dazu."
        if i < 2:
            text += " Die Hammingdistanz zwischen Codewoertern ist entscheidend."
        if i == 0:
            text += " Denn die Hammingdistanz misst, wie die Hammingdistanz zaehlt."
        chunks.append(Chunk(id=f"c-{i:04d}", quelle="vorlesung",
                            position=f"vl, Min. {i}:00", text=text))
    themen = ergaenze_aus_transkript([Thema(id="t-01", titel="Bestehendes")], chunks)
    neue = [t.titel.lower() for t in themen[1:]]
    assert "bedeutet" not in neue and "nämlich" not in neue, neue
    assert "punkte" not in neue, neue
    assert "hammingdistanz" in neue, neue
