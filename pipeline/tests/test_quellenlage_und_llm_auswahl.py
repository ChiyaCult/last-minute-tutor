"""Quellen-Erkennung (Video-Endungen, Groß-/Kleinschreibung, Warn-Materiallücken),
Boilerplate-Themenfilter und LLM-Anbieter-Auswahl."""
import unicodedata

import pytest

from datetime import datetime, timezone

from lernpaket_pipeline.llm import (AnthropicLLM, GeminiLLM,
                                    OllamaLLM, OpenAiKompatibelLLM,
                                    extrahiere_json, hole_llm)
from lernpaket_pipeline.pipeline import (erzeuge_lernpaket, extrahiere_material,
                                         finde_quellen, generiere_lernpaket,
                                         lade_extraktion, schreibe_extraktion)
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


def test_kategorie_ordner_studienbrief_wird_erkannt(tmp_path):
    """Primäres Schema: ein Ordner je Kategorie, Dateinamen beliebig."""
    modul = tmp_path / "modul"
    (modul / "studienbrief").mkdir(parents=True)
    schreibe_pdf(modul / "studienbrief" / "MAT2a_OHNE_Loesungen-1.pdf",
                 STUDIENBRIEF_SEITEN)

    quellen = finde_quellen(modul)
    assert [p.name for p in quellen.studienbriefe] == ["MAT2a_OHNE_Loesungen-1.pdf"]


def test_mehrere_studienbrief_pdfs_werden_alle_erfasst(tmp_path):
    modul = tmp_path / "modul"
    (modul / "studienbrief").mkdir(parents=True)
    schreibe_pdf(modul / "studienbrief" / "teil_a.pdf", STUDIENBRIEF_SEITEN)
    schreibe_pdf(modul / "studienbrief" / "teil_b.pdf", STUDIENBRIEF_SEITEN)

    quellen = finde_quellen(modul)
    assert [p.name for p in quellen.studienbriefe] == ["teil_a.pdf", "teil_b.pdf"]


def test_mehrteiliger_studienbrief_belegt_positionen_mit_dateiname(tmp_path):
    """Ohne Dateinamen zeigten die Belege beider PDFs mehrdeutig auf 'S. 1'."""
    modul = tmp_path / "modul"
    (modul / "studienbrief").mkdir(parents=True)
    schreibe_pdf(modul / "studienbrief" / "teil_a.pdf", STUDIENBRIEF_SEITEN)
    schreibe_pdf(modul / "studienbrief" / "teil_b.pdf", STUDIENBRIEF_SEITEN)

    ext = extrahiere_material(modul)
    positionen = {c.position for c in ext.chunks if c.quelle == "studienbrief"}
    assert any(p.startswith("teil_a, S.") for p in positionen)
    assert any(p.startswith("teil_b, S.") for p in positionen)
    assert len({c.id for c in ext.chunks}) == len(ext.chunks)  # IDs bleiben eindeutig


def test_uebungsordner_mit_umlaut_in_zerlegter_unicode_form(tmp_path):
    """macOS legt 'übungen' als NFD ab — ohne Normalisierung fiel der Ordner weg."""
    modul = tmp_path / "modul"
    nfd_name = unicodedata.normalize("NFD", "übungen")
    assert nfd_name != "übungen"  # sonst prueft der Test die Normalisierung nicht
    (modul / nfd_name).mkdir(parents=True)
    schreibe_pdf(modul / "studienbrief.pdf", STUDIENBRIEF_SEITEN)
    schreibe_pdf(modul / nfd_name / "blatt01.pdf", [["Aufgabe 1"]])

    quellen = finde_quellen(modul)
    assert [p.name for p in quellen.uebungen] == ["blatt01.pdf"]


def test_materialluecke_wenn_vorlesungsvideos_fehlen(modul_dir):
    paket = erzeuge_lernpaket(modul_dir)
    assert any("Keine Vorlesungsvideos" in l.beschreibung
               for l in paket.manifest.materialluecken)


def test_materialluecke_wenn_videos_unausgewertet_bleiben(modul_dir_mit_vorlesung):
    paket = erzeuge_lernpaket(modul_dir_mit_vorlesung)  # ohne ASR/Folien
    passende = [l for l in paket.manifest.materialluecken
                if "nicht ausgewertet" in l.beschreibung]
    assert passende and "'asr'" in passende[0].beschreibung


def test_keine_warnung_wenn_asr_die_videos_auswertet(modul_dir_mit_vorlesung,
                                                     fake_transkribierer):
    paket = erzeuge_lernpaket(modul_dir_mit_vorlesung,
                              transkribierer=fake_transkribierer)
    assert not any("nicht ausgewertet" in l.beschreibung
                   for l in paket.manifest.materialluecken)


# --- Zweischritt: Extraktion persistieren, Generierung getrennt --------------

FIX_ZEIT = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def test_zweischritt_liefert_dasselbe_paket_wie_komplettlauf(modul_dir_mit_optionalquellen):
    modul = modul_dir_mit_optionalquellen
    komplett = erzeuge_lernpaket(modul, jetzt=FIX_ZEIT)

    extraktion = extrahiere_material(modul, jetzt=FIX_ZEIT)
    schreibe_extraktion(extraktion, modul)
    geladen = lade_extraktion(modul)
    getrennt = generiere_lernpaket(geladen, modul_id=modul.name, titel=modul.name,
                                   jetzt=FIX_ZEIT)

    assert [c.text for c in getrennt.chunks] == [c.text for c in komplett.chunks]
    assert [t.titel for t in getrennt.themen] == [t.titel for t in komplett.themen]
    assert len(getrennt.fragen) == len(komplett.fragen)
    assert getrennt.manifest.optionalquellen_vorhanden is True


def test_generieren_ohne_extraktion_schlaegt_klar_fehl(modul_dir):
    with pytest.raises(FileNotFoundError, match="lernpaket extrahieren"):
        lade_extraktion(modul_dir)


def test_transkript_cache_verhindert_zweite_asr(modul_dir_mit_vorlesung,
                                                fake_transkribierer):
    class ZaehlenderTranskribierer:
        def __init__(self):
            self.aufrufe = 0

        def transkribiere(self, video):
            self.aufrufe += 1
            return fake_transkribierer.transkribiere(video)

    erster = ZaehlenderTranskribierer()
    extrahiere_material(modul_dir_mit_vorlesung, transkribierer=erster)
    assert erster.aufrufe == 1

    zweiter = ZaehlenderTranskribierer()
    nochmal = extrahiere_material(modul_dir_mit_vorlesung, transkribierer=zweiter)
    assert zweiter.aufrufe == 0  # Transkript kam aus dem Cache
    assert any(c.quelle == "vorlesung" for c in nochmal.chunks)


def test_geaenderte_videodatei_umgeht_den_cache(modul_dir_mit_vorlesung,
                                               fake_transkribierer):
    class ZaehlenderTranskribierer:
        def __init__(self):
            self.aufrufe = 0

        def transkribiere(self, video):
            self.aufrufe += 1
            return fake_transkribierer.transkribiere(video)

    extrahiere_material(modul_dir_mit_vorlesung,
                        transkribierer=ZaehlenderTranskribierer())
    (modul_dir_mit_vorlesung / "vorlesung-01.mp4").write_bytes(b"neuer laengerer inhalt")
    zweiter = ZaehlenderTranskribierer()
    extrahiere_material(modul_dir_mit_vorlesung, transkribierer=zweiter)
    assert zweiter.aufrufe == 1  # andere Größe → neu transkribiert


# --- Diagramm-Verlust --------------------------------------------------------

def test_materialluecke_fuer_rasterbild_ohne_unterschrift(modul_dir, monkeypatch):
    """Rasterbild-Seiten ohne Bildunterschrift werden als unerfasst gemeldet."""
    monkeypatch.setattr("lernpaket_pipeline.pipeline.seiten_mit_bildern",
                        lambda pfad: [2, 3])
    paket = erzeuge_lernpaket(modul_dir)
    passende = [l for l in paket.manifest.materialluecken
                if "Rasterbild ohne Bildunterschrift" in l.beschreibung]
    assert passende and "S. 2" in passende[0].beschreibung


def test_keine_bild_luecke_ohne_eingebettete_bilder(modul_dir):
    paket = erzeuge_lernpaket(modul_dir)  # Fixture-PDF enthält keine Bilder
    assert not any("Rasterbild" in l.beschreibung
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
    "Russia 17,6%",
    "Tabelle 4: Approximation mithilfe des Vorwärts-Differenzenquotienten",
    "Abb. 1.5: Dirichlet-Funktion",
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
    assert isinstance(llm, OllamaLLM)
    # Native Route, nicht /v1: nur die wertet options.num_ctx aus.
    assert not llm.basis_url.endswith("/v1")
    assert llm.modell == "llama3.1"


def test_modell_override_aus_umgebung(saubere_umgebung):
    saubere_umgebung.setenv("ANTHROPIC_API_KEY", "sk-test")
    saubere_umgebung.setenv("LERNPAKET_LLM_MODELL", "claude-opus-4-8")
    assert hole_llm().modell == "claude-opus-4-8"


def test_argumente_schlagen_umgebung(saubere_umgebung):
    saubere_umgebung.setenv("ANTHROPIC_API_KEY", "sk-test")
    saubere_umgebung.setenv("LERNPAKET_LLM", "anthropic")
    llm = hole_llm("ollama", "qwen3")
    assert isinstance(llm, OllamaLLM)
    assert llm.modell == "qwen3"


def test_unbekannter_anbieter_schlaegt_laut_fehl(saubere_umgebung):
    with pytest.raises(RuntimeError, match="Unbekannter LLM-Anbieter"):
        hole_llm("gpt5")


# --- Ollama: Kontextfenster und Denkblöcke -------------------------------


def _ollama_anfrage(monkeypatch, **umgebung):
    """Fängt den Anfragekörper ab, den OllamaLLM absetzen würde."""
    gesehen = {}

    def falsches_post(url, daten, headers, versuche=6, zeitlimit=300):
        gesehen["url"] = url
        gesehen["daten"] = daten
        gesehen["zeitlimit"] = zeitlimit
        return {"message": {"content": "{}"}}

    monkeypatch.setattr("lernpaket_pipeline.llm._post_json", falsches_post)
    for name, wert in umgebung.items():
        monkeypatch.setenv(name, wert)
    OllamaLLM("http://localhost:11434", "qwen3.8").frage("sys", "prompt", max_tokens=2048)
    return gesehen


def test_ollama_setzt_kontextfenster(saubere_umgebung):
    """Ohne num_ctx kürzt Ollama den Prompt stumm auf 4096 Token."""
    gesehen = _ollama_anfrage(saubere_umgebung)
    assert gesehen["url"].endswith("/api/chat")
    assert gesehen["daten"]["options"]["num_ctx"] == 32768
    assert gesehen["daten"]["options"]["num_predict"] == 2048


def test_ollama_kontextfenster_ueber_umgebung(saubere_umgebung):
    gesehen = _ollama_anfrage(saubere_umgebung, LERNPAKET_OLLAMA_CTX="8192")
    assert gesehen["daten"]["options"]["num_ctx"] == 8192


def test_ollama_kontextfenster_ignoriert_unsinn(saubere_umgebung):
    gesehen = _ollama_anfrage(saubere_umgebung, LERNPAKET_OLLAMA_CTX="viel")
    assert gesehen["daten"]["options"]["num_ctx"] == 32768


def test_ollama_denkt_standardmaessig_nicht(saubere_umgebung):
    assert _ollama_anfrage(saubere_umgebung)["daten"]["think"] is False
    gesehen = _ollama_anfrage(saubere_umgebung, LERNPAKET_OLLAMA_THINK="1")
    assert gesehen["daten"]["think"] is True


def test_json_nach_denkblock_wird_gefunden():
    """Der Gedankengang enthält oft verworfene JSON-Entwürfe."""
    roh = ('<think>Vielleicht {"lehrbloecke": []}? Nein, doch anders.</think>\n'
           '{"lehrbloecke": [{"tiefe": "auffrischung"}]}')
    assert extrahiere_json(roh)["lehrbloecke"][0]["tiefe"] == "auffrischung"


def test_abgeschnittener_denkblock_gilt_als_unauswertbar():
    """Token-Budget mitten im Denken alle: lieber Materiallücke als Denktext."""
    with pytest.raises(ValueError):
        extrahiere_json('<think>Also, der Chunk {c-1} sagt folgendes')


def test_ollama_bekommt_grosszuegiges_zeitlimit(saubere_umgebung):
    """Ein 27B auf einem M3 braucht für ein Thema mehrere Minuten. Mit dem
    Remote-Zeitlimit von 300 s liefe jeder lokale Lauf in einen TimeoutError —
    der gilt als vorübergehend und bricht den ganzen Lauf ab."""
    assert _ollama_anfrage(saubere_umgebung)["zeitlimit"] == 3600


def test_ollama_zeitlimit_ueber_umgebung(saubere_umgebung):
    gesehen = _ollama_anfrage(saubere_umgebung, LERNPAKET_OLLAMA_TIMEOUT="900")
    assert gesehen["zeitlimit"] == 900


def test_latex_backslashes_zerlegen_das_json_nicht():
    """Der System-Prompt verlangt LaTeX; "\\overline" ist kein JSON-Escape."""
    roh = r'{"lehrbloecke": [{"inhalt_markdown": "Es gilt $\overline{Q} = \frac{a}{b}$"}]}'
    d = extrahiere_json(roh)
    assert "overline" in d["lehrbloecke"][0]["inhalt_markdown"]


def test_gueltige_escapes_bleiben_erhalten():
    d = extrahiere_json(r'{"a": "Zeile1\nZeile2", "b": "Er sagte \"hallo\"", "c": "ä"}')
    assert d["a"] == "Zeile1\nZeile2" and d["b"] == 'Er sagte "hallo"' and d["c"] == "ä"


def test_gemischtes_latex_und_echte_escapes():
    d = extrahiere_json(r'{"t": "Formel $\alpha$\nund \"Zitat\""}')
    assert "alpha" in d["t"] and "\n" in d["t"] and '"Zitat"' in d["t"]
