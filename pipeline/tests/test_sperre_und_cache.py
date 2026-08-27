"""Modulsperre gegen parallele Läufe und Datei-Cache des Dokument-Parsers.

Beides zielt auf den semesterbegleitenden Ablauf: nach und nach kommen
Vorlesungen dazu, der Studienbrief bleibt derselbe.
"""
import json
import re
from pathlib import Path

import pytest

from lernpaket_pipeline.extraktion.pdf import Seite
from lernpaket_pipeline.pipeline import (EXTRAKTIONS_ORDNER, ModulBelegt,
                                         _normalisiere_seiten, modulsperre)


class _FakeSeitenParser:
    """Erfüllt das SeitenParser-Protokoll und zählt seine Aufrufe."""

    def __init__(self, seiten=None):
        self.seiten = seiten or {1: "# Aus dem Parser"}
        self.aufrufe = 0

    def pdf_nach_seiten(self, pfad):
        self.aufrufe += 1
        return dict(self.seiten)

    def nach_markdown(self, text):
        return text


def test_zweiter_lauf_wird_abgewiesen(tmp_path: Path):
    with modulsperre(tmp_path):
        with pytest.raises(ModulBelegt, match="wird bereits aufbereitet"):
            with modulsperre(tmp_path):
                pass


def test_sperre_wird_nach_dem_lauf_freigegeben(tmp_path: Path):
    with modulsperre(tmp_path):
        pass
    with modulsperre(tmp_path):  # muss wieder gehen
        pass
    assert not (tmp_path / EXTRAKTIONS_ORDNER / ".lock").exists()


def test_sperre_wird_auch_nach_fehler_freigegeben(tmp_path: Path):
    with pytest.raises(ValueError):
        with modulsperre(tmp_path):
            raise ValueError("boom")
    assert not (tmp_path / EXTRAKTIONS_ORDNER / ".lock").exists()


def test_verwaiste_sperre_wird_uebernommen(tmp_path: Path):
    """Nach einem Absturz darf eine tote PID das Modul nicht dauerhaft blockieren."""
    sperre = tmp_path / EXTRAKTIONS_ORDNER / ".lock"
    sperre.parent.mkdir(parents=True)
    # PID 2**22 existiert nicht (über dem üblichen pid_max).
    sperre.write_text(json.dumps({"pid": 2 ** 22, "seit": "2026-01-01T00:00:00"}))
    with modulsperre(tmp_path):
        assert json.loads(sperre.read_text())["pid"] != 2 ** 22
    assert not sperre.exists()


def test_unlesbare_sperre_blockiert_nicht(tmp_path: Path):
    sperre = tmp_path / EXTRAKTIONS_ORDNER / ".lock"
    sperre.parent.mkdir(parents=True)
    sperre.write_text("kein json")
    with modulsperre(tmp_path):
        pass


def _pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "studienbrief.pdf"
    pdf.write_bytes(b"%PDF-1.4 nur als Platzhalter")
    return pdf


def test_parser_ergebnis_kommt_beim_zweiten_mal_aus_dem_cache(tmp_path: Path):
    """Der Studienbrief darf nicht bei jedem Lauf neu geparst werden."""
    pdf = _pdf(tmp_path)
    cache = tmp_path / "dokumente"
    parser = _FakeSeitenParser({1: "# Kapitel 1", 2: "$$x^2$$"})
    seiten = [Seite(nummer=1, text="roh 1"), Seite(nummer=2, text="roh 2")]

    erste = _normalisiere_seiten(seiten, parser, pdf=pdf, cache_dir=cache)
    zweite = _normalisiere_seiten(seiten, parser, pdf=pdf, cache_dir=cache)

    assert parser.aufrufe == 1, "zweiter Lauf muss aus dem Cache kommen"
    assert [s.text for s in erste] == [s.text for s in zweite]
    assert erste[1].text == "$$x^2$$"


def test_geaendertes_pdf_umgeht_den_cache(tmp_path: Path):
    pdf = _pdf(tmp_path)
    cache = tmp_path / "dokumente"
    parser = _FakeSeitenParser()
    seiten = [Seite(nummer=1, text="roh")]

    _normalisiere_seiten(seiten, parser, pdf=pdf, cache_dir=cache)
    pdf.write_bytes(b"%PDF-1.4 deutlich laengerer Inhalt als vorher")  # andere Groesse
    _normalisiere_seiten(seiten, parser, pdf=pdf, cache_dir=cache)

    assert parser.aufrufe == 2


def test_anderer_parser_umgeht_den_cache(tmp_path: Path):
    """Nach einem Backend-Wechsel darf nicht der alte Text weiterverwendet werden."""
    pdf = _pdf(tmp_path)
    cache = tmp_path / "dokumente"
    seiten = [Seite(nummer=1, text="roh")]
    _normalisiere_seiten(seiten, _FakeSeitenParser(), pdf=pdf, cache_dir=cache)

    cache_datei = next(cache.glob("*.json"))
    daten = json.loads(cache_datei.read_text(encoding="utf-8"))
    daten["parser"] = "EinAndererParser"
    cache_datei.write_text(json.dumps(daten), encoding="utf-8")

    zweiter = _FakeSeitenParser()
    _normalisiere_seiten(seiten, zweiter, pdf=pdf, cache_dir=cache)
    assert zweiter.aufrufe == 1


def test_cli_meldet_belegtes_modul_ohne_traceback(tmp_path: Path, capsys):
    """Ein zweiter Lauf soll eine Anweisung ausgeben, keinen Stacktrace."""
    from lernpaket_pipeline.cli import main

    modul = tmp_path / "modul"
    modul.mkdir()
    (modul / "studienbrief.pdf").write_bytes(b"%PDF-1.4")
    with modulsperre(modul):
        code = main(["extrahieren", str(modul)])
    assert code == 2
    fehler = capsys.readouterr().err
    assert "wird bereits aufbereitet" in fehler
    assert "Traceback" not in fehler


def test_generierungs_cache_ueberlebt_den_prozess(modul_dir):
    """Der Cache muss auf Platte liegen, nicht im Speicher — ein Abbruch beendet
    den Prozess, und genau dann soll der zweite Anlauf davon zehren."""
    from lernpaket_pipeline.pipeline import (EXTRAKTIONS_ORDNER, GENERIERUNGS_CACHE,
                                             extrahiere_material, generiere_lernpaket)
    from lernpaket_pipeline.generierung import LLMGenerator
    from lernpaket_pipeline.llm import GecachterLLM

    class ZaehlendesLLM:
        modell = "test-modell"

        def __init__(self):
            self.aufrufe = 0

        def frage(self, system, prompt, max_tokens=4096):
            self.aufrufe += 1
            # Erste Chunk-ID aus dem Prompt ("[c-1 | studienbrief S. 1]"), damit
            # das Ergebnis den Beleg-Vertrag erfüllt und nicht leer bleibt.
            chunk_id = re.search(r"\[([^ |]+) \|", prompt).group(1)
            return ('{"lehrbloecke": [{"tiefe": "auffrischung", '
                    '"inhalt_markdown": "Inhalt", "chunk_ids": ["%s"]}], '
                    '"fragen": [], "materialluecken": []}' % chunk_id)

    extraktion = extrahiere_material(modul_dir, mit_diagrammen=False)
    cache = modul_dir / EXTRAKTIONS_ORDNER / GENERIERUNGS_CACHE

    erst = ZaehlendesLLM()
    generiere_lernpaket(extraktion, modul_id="m", titel="M",
                        generator=LLMGenerator(GecachterLLM(erst, cache)))
    assert erst.aufrufe > 0
    assert list(cache.glob("*.json")), "Cache muss Dateien anlegen"

    # Frischer Wrapper wie nach einem Neustart des Prozesses.
    zweit = ZaehlendesLLM()
    gecacht = GecachterLLM(zweit, cache)
    generiere_lernpaket(extraktion, modul_id="m", titel="M",
                        generator=LLMGenerator(gecacht))
    assert zweit.aufrufe == 0, "zweiter Lauf darf nichts mehr kosten"
    assert gecacht.treffer == erst.aufrufe
