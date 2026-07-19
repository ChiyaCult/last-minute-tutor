"""Quellen-Erkennung (Video-Endungen, Groß-/Kleinschreibung, Warn-Materiallücken),
Boilerplate-Themenfilter und LLM-Anbieter-Auswahl."""
import pytest

from lernpaket_pipeline.llm import (AnthropicLLM, GeminiLLM,
                                    OpenAiKompatibelLLM, hole_llm)
from lernpaket_pipeline.pipeline import erzeuge_lernpaket, finde_quellen
from lernpaket_pipeline.themen import ist_boilerplate_titel

from .conftest import STUDIENBRIEF_SEITEN
from .pdf_helfer import schreibe_pdf

ALLE_LLM_VARIABLEN = (
    "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GITHUB_TOKEN",
    "COPILOT_API_KEY", "LERNPAKET_LLM", "LERNPAKET_LLM_MODELL",
    "LERNPAKET_OLLAMA_URL", "LERNPAKET_OLLAMA_MODELL", "LERNPAKET_COPILOT_URL",
)


@pytest.fixture
def saubere_umgebung(monkeypatch):
    for variable in ALLE_LLM_VARIABLEN:
        monkeypatch.delenv(variable, raising=False)
    return monkeypatch


# --- Quellen-Erkennung -------------------------------------------------------

def test_videos_aller_endungen_auch_in_gross_geschriebenem_ordner(tmp_path):
    modul = tmp_path / "modul"
    (modul / "Vorlesungen").mkdir(parents=True)
    schreibe_pdf(modul / "brief.pdf", STUDIENBRIEF_SEITEN)
    (modul / "Vorlesungen" / "v1.mkv").write_bytes(b"x")
    (modul / "Vorlesungen" / "v2.MP4").write_bytes(b"x")
    (modul / "v3.webm").write_bytes(b"x")
    (modul / "notizen.txt").write_text("kein Video")

    quellen = finde_quellen(modul)
    assert {p.name for p in quellen.vorlesungen} == {"v1.mkv", "v2.MP4", "v3.webm"}


def test_altklausuren_ordner_mit_grossbuchstaben(tmp_path):
    modul = tmp_path / "modul"
    (modul / "Altklausuren").mkdir(parents=True)
    schreibe_pdf(modul / "studienbrief.pdf", STUDIENBRIEF_SEITEN)
    schreibe_pdf(modul / "Altklausuren" / "ws2019.pdf", [["Aufgabe 1"]])

    quellen = finde_quellen(modul)
    assert [p.name for p in quellen.altklausuren] == ["ws2019.pdf"]


def test_materialluecke_wenn_vorlesungsvideos_fehlen(modul_dir):
    paket = erzeuge_lernpaket(modul_dir)
    assert any("Keine Vorlesungsvideos" in l.beschreibung
               for l in paket.manifest.materialluecken)


def test_materialluecke_wenn_videos_unausgewertet_bleiben(modul_dir_mit_vorlesung):
    paket = erzeuge_lernpaket(modul_dir_mit_vorlesung)  # ohne ASR/Folien
    passende = [l for l in paket.manifest.materialluecken
                if "nicht ausgewertet" in l.beschreibung]
    assert passende and "--mit-asr" in passende[0].beschreibung


def test_keine_warnung_wenn_asr_die_videos_auswertet(modul_dir_mit_vorlesung,
                                                     fake_transkribierer):
    paket = erzeuge_lernpaket(modul_dir_mit_vorlesung,
                              transkribierer=fake_transkribierer)
    assert not any("nicht ausgewertet" in l.beschreibung
                   for l in paket.manifest.materialluecken)


# --- Diagramm-Verlust --------------------------------------------------------

def test_materialluecke_fuer_seiten_mit_diagrammen(modul_dir, monkeypatch):
    monkeypatch.setattr("lernpaket_pipeline.pipeline.seiten_mit_bildern",
                        lambda pfad: [2, 3])
    paket = erzeuge_lernpaket(modul_dir)
    passende = [l for l in paket.manifest.materialluecken
                if "Abbildungen/Diagramme" in l.beschreibung]
    assert passende and "S. 2" in passende[0].beschreibung


def test_keine_diagramm_luecke_ohne_eingebettete_bilder(modul_dir):
    paket = erzeuge_lernpaket(modul_dir)  # Fixture-PDF enthält keine Bilder
    assert not any("Abbildungen/Diagramme" in l.beschreibung
                   for l in paket.manifest.materialluecken)


def test_materialluecke_fuer_unreparierbar_verklebten_text(modul_dir):
    """Bleibt Text auch nach der Zweitextraktion verklebt, wird das gemeldet."""
    seiten = [list(s) for s in STUDIENBRIEF_SEITEN] + [[
        "DieserAbsatzenthältkeineLeerzeichenzwischendeneinzelnenWörtern",
        "unddieZweitextraktionfindetebenfallskeineGlyphenabstände,weil",
        "dasPDFwirklichkeineLückenimTextstromhat.DeshalbmussdiePipeline",
        "dieSeitealsMateriallückemeldenstattdenInhaltstillzuverwenden.",
        "AuchdieseZeileistkomplettohneLeerzeichengeschriebenworden.",
    ]]
    schreibe_pdf(modul_dir / "studienbrief.pdf", seiten)

    paket = erzeuge_lernpaket(modul_dir)
    passende = [l for l in paket.manifest.materialluecken
                if "verklebtem Text" in l.beschreibung]
    assert passende and "S. 5" in passende[0].beschreibung


# --- Boilerplate-Themenfilter ------------------------------------------------

@pytest.mark.parametrize("titel", [
    "Lernergebnisse",
    "Advance Organizer",
    "Zusammenfassung Seite 183",
    "Übungen",
    "Ergebnismenge..............................148",
    "Advance Organizer . . . . . . . . . . . . . . .",
    "MitHilfederStammfunktion,diejaengzusammen-",
    "Die Obersumme für das Teilintervall beträgt:",
    "Übungsaufgaben",
    "Lösung zu Kontrollaufgabe 1.2 auf",
    "Monotonie des bestimmten Integrals: Gilt f(x) für alle x, dann",
    "Für n= 25beträgt die Streifenbreite",
    "Wenn auf eine Zufallsgröße sehr viele Ursachen wirken",
])
def test_boilerplate_und_artefakte_werden_erkannt(titel):
    assert ist_boilerplate_titel(titel)


@pytest.mark.parametrize("titel", [
    "Normalisierung",
    "Das Entity-Relationship-Modell Seite 21",
    "Integration mittels Substitution",
    "Zusammenfassung der Entwurfsregeln",  # echtes Thema, kein reiner Abschnittsname
])
def test_echte_themen_bleiben_erhalten(titel):
    assert not ist_boilerplate_titel(titel)


def test_katalog_ohne_boilerplate_und_nummern_artefakte(modul_dir):
    """Struktur-Abschnitte und Impressum-Artefakte tauchen nicht als Themen auf."""
    seiten = [list(s) for s in STUDIENBRIEF_SEITEN]
    seiten[0] = ["1.0 Lernergebnisse", "Sie kennen danach alle Begriffe.",
                 "81739 München", "Ein Verlagsort ist kein Thema."] + seiten[0]
    modul = modul_dir
    schreibe_pdf(modul / "studienbrief.pdf", seiten)

    paket = erzeuge_lernpaket(modul)
    titel = [t.titel for t in paket.themen]
    assert not any("Lernergebnisse" in t for t in titel)
    assert not any("München" in t for t in titel)
    assert any("Quicksort" in t for t in titel)


def test_seiten_suffix_wird_aus_titeln_entfernt(modul_dir):
    seiten = [list(s) for s in STUDIENBRIEF_SEITEN]
    seiten[2] = [z.replace("2.1 Quicksort", "2.1 Quicksort Seite 21") for z in seiten[2]]
    schreibe_pdf(modul_dir / "studienbrief.pdf", seiten)

    paket = erzeuge_lernpaket(modul_dir)
    passende = [t.titel for t in paket.themen if "Quicksort" in t.titel]
    assert passende and all("Seite" not in t for t in passende)


# --- LLM-Anbieter-Auswahl ----------------------------------------------------

def test_ohne_schluessel_kein_llm(saubere_umgebung):
    assert hole_llm() is None


def test_auto_erkennung_anthropic(saubere_umgebung):
    saubere_umgebung.setenv("ANTHROPIC_API_KEY", "sk-test")
    llm = hole_llm()
    assert isinstance(llm, AnthropicLLM)
    assert llm.modell == "claude-sonnet-5"


def test_auto_erkennung_gemini(saubere_umgebung):
    saubere_umgebung.setenv("GEMINI_API_KEY", "g-test")
    assert isinstance(hole_llm(), GeminiLLM)


def test_github_token_allein_loest_kein_copilot_aus(saubere_umgebung):
    """gh-CLI-Umgebungen haben oft GITHUB_TOKEN — das ist keine LLM-Absicht."""
    saubere_umgebung.setenv("GITHUB_TOKEN", "gh-test")
    assert hole_llm() is None


def test_copilot_explizit_mit_github_token(saubere_umgebung):
    saubere_umgebung.setenv("LERNPAKET_LLM", "copilot")
    saubere_umgebung.setenv("GITHUB_TOKEN", "gh-test")
    llm = hole_llm()
    assert isinstance(llm, OpenAiKompatibelLLM)
    assert llm.modell == "openai/gpt-4o"
    assert "models.github.ai" in llm.basis_url


def test_copilot_ohne_token_schlaegt_laut_fehl(saubere_umgebung):
    saubere_umgebung.setenv("LERNPAKET_LLM", "copilot")
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        hole_llm()


def test_ollama_explizit_ohne_schluessel(saubere_umgebung):
    saubere_umgebung.setenv("LERNPAKET_LLM", "ollama")
    llm = hole_llm()
    assert isinstance(llm, OpenAiKompatibelLLM)
    assert llm.basis_url.endswith("/v1")
    assert llm.modell == "llama3.1"


def test_modell_override_aus_umgebung(saubere_umgebung):
    saubere_umgebung.setenv("ANTHROPIC_API_KEY", "sk-test")
    saubere_umgebung.setenv("LERNPAKET_LLM_MODELL", "claude-opus-4-8")
    assert hole_llm().modell == "claude-opus-4-8"


def test_argumente_schlagen_umgebung(saubere_umgebung):
    saubere_umgebung.setenv("ANTHROPIC_API_KEY", "sk-test")
    saubere_umgebung.setenv("LERNPAKET_LLM", "anthropic")
    llm = hole_llm("ollama", "qwen3")
    assert isinstance(llm, OpenAiKompatibelLLM)
    assert llm.modell == "qwen3"


def test_unbekannter_anbieter_schlaegt_laut_fehl(saubere_umgebung):
    with pytest.raises(RuntimeError, match="Unbekannter LLM-Anbieter"):
        hole_llm("gpt5")
