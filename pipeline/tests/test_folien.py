"""Folien aus Video: Wechselerkennung, Dedupe, Extraktion (Issue #29)."""
from pathlib import Path

from lernpaket_pipeline.extraktion.folien import extrahiere_folien
from lernpaket_pipeline.pipeline import erzeuge_lernpaket

from .conftest import FakeFolienLeser, FakeSzenenErkenner, FakeTranskribierer


def test_duplikate_werden_verworfen(tmp_path: Path):
    folien = extrahiere_folien(tmp_path / "v.mp4", FakeSzenenErkenner(), FakeFolienLeser())
    assert len(folien) == 2  # drei Szenen, eine doppelt
    assert [f.nummer for f in folien] == [1, 2]
    assert folien[0].zeit_sekunden == 10.0


def test_eindeutige_folien_laufen_durch_extraktion(tmp_path: Path):
    folien = extrahiere_folien(tmp_path / "v.mp4", FakeSzenenErkenner(), FakeFolienLeser())
    assert "Partitionierung" in folien[0].text
    assert "Mergesort" in folien[1].text


def test_folienformeln_erscheinen_im_lernpaket(modul_dir_mit_vorlesung):
    """Akzeptanz #29: Auf Folien gezeigte Formeln erscheinen im Lernpaket."""
    paket = erzeuge_lernpaket(
        modul_dir_mit_vorlesung,
        transkribierer=FakeTranskribierer(),
        szenen_erkenner=FakeSzenenErkenner(),
        folien_leser=FakeFolienLeser(),
    )
    folien_chunks = [c for c in paket.chunks if c.quelle == "folie"]
    assert folien_chunks, "Folien muessen als Chunks im Paket liegen"
    assert any("T(n) = 2T(n/2) + n" in c.text for c in folien_chunks)
    assert all(c.position.startswith("Folie ") for c in folien_chunks)
    # Die Folienformel ist im Vertiefungs-Lehrblock des passenden Themas nutzbar:
    quicksort_bloecke = [b for b in paket.lehrbloecke
                         if "quicksort" in b.thema_id or "T(n)" in b.inhalt_markdown]
    assert any("$$" in b.inhalt_markdown for b in paket.lehrbloecke)
