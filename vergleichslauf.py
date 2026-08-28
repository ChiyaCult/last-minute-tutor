#!/usr/bin/env python
"""A/B-Vergleich auf identischen Themen-Prompts.

Variiert wahlweise das Modell oder den System-Prompt.

    caffeinate -i ./pipeline/.venv/bin/python vergleichslauf.py

Spielt die Prompts eines abgeschlossenen Laufs wörtlich gegen ein zweites
Modell ab und stellt die Ergebnisse gegenüber.

Warum aus dem Cache und nicht neu gebaut: `ordne_chunks_zu` läuft in der
Pipeline VOR `benenne_themen` und ordnet Folien- und Vorlesungs-Chunks über
Titelwörter zu. Baut man die Zuordnung später aus dem fertigen Paket nach,
stehen dort die umbenannten Titel — die Auswahl fiele anders aus und die
Modelle sähen nicht mehr dasselbe Material. Der Antwort-Cache hält die Prompts
wortgleich fest, also ist er die verlässlichere Quelle.

Umgebung:
    VERGLEICHSMODELL   Modell B (Standard: gleich BASISMODELL)
    BASISMODELL        Modell A, dessen Cache gelesen wird (Standard: qwen3:14b)
    SYSTEM_B           "v2" für den geschärften System-Prompt (Standard: "v1")
    ANZAHL_THEMEN      wie viele Prompts (Standard: 8)

Genau eine Größe verändern, sonst ist das Ergebnis nicht zuzuordnen: entweder
VERGLEICHSMODELL oder SYSTEM_B.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent
sys.path.insert(0, str(WURZEL / "pipeline"))

from lernpaket_pipeline.generierung import _SYSTEM_PROMPT  # noqa: E402
from lernpaket_pipeline.llm import (GecachterLLM, extrahiere_json,  # noqa: E402
                                   hole_llm)

MODUL = "rest"
CACHE = WURZEL / "input" / MODUL / "extraktion" / "generierung"
BERICHT = WURZEL / "lernpakete-neu" / "vergleich.md"
ROHDATEN = WURZEL / "lernpakete-neu" / "vergleich.json"

BASISMODELL = os.environ.get("BASISMODELL", "qwen3:14b")
VERGLEICHSMODELL = os.environ.get("VERGLEICHSMODELL", BASISMODELL)
ANZAHL = int(os.environ.get("ANZAHL_THEMEN", "8"))

# Geschärfte Fassung. Angesetzt genau an der Schwäche, die der Modellvergleich
# gezeigt hat: Distraktoren wie "Sie minimiert NUR die Anzahl der Gatter" oder
# "Sie IGNORIERT die Boolesche Algebra" lassen sich ausschließen, ohne den Stoff
# zu kennen. Das größere Modell baute an derselben Stelle plausible Alternativen
# aus dem Themenfeld. Die Frage ist, ob eine Anweisung dasselbe billiger holt.
_SYSTEM_V2 = _SYSTEM_PROMPT + (
    " Für MC-Fragen gilt zusätzlich: Alle Optionen müssen fachlich plausible "
    "Alternativen aus demselben Themenfeld sein, etwa gleich lang und gleich "
    "konkret. Keine Option darf sich allein an Wörtern wie 'nur', 'niemals', "
    "'immer', 'alle' oder 'ignoriert' als falsch erkennen lassen, und keine darf "
    "erkennbar aus einer anderen Kategorie stammen als die übrigen. Die falschen "
    "Optionen sollen typische Verwechslungen abbilden, die jemand mit halbem "
    "Verständnis des Stoffes tatsächlich machen würde. Gib als 'antwort' den "
    "Buchstaben der richtigen Option an (A, B, C, ...)."
)
SYSTEM_B = _SYSTEM_V2 if os.environ.get("SYSTEM_B") == "v2" else _SYSTEM_PROMPT
SYSTEM_ETIKETT = "v2 (geschärft)" if os.environ.get("SYSTEM_B") == "v2" else "v1"


def lies_cache(modell: str) -> list[dict]:
    """Generierungs-Prompts des Basislaufs, kleinste zuerst.

    Die Themenbenennung liegt im selben Verzeichnis und beginnt mit "Themen:";
    Generierungs-Prompts beginnen mit "Thema:". Kleinste zuerst, damit früh
    Ergebnisse dastehen und ein Abbruch wenig kostet.
    """
    eintraege = []
    for datei in sorted(CACHE.glob("*.json")):
        try:
            d = json.loads(datei.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("modell") != modell or not d.get("prompt", "").startswith("Thema:"):
            continue
        d["titel"] = d["prompt"].split("\n", 1)[0][len("Thema:"):].strip()
        d["datei"] = datei.name
        eintraege.append(d)
    eintraege.sort(key=lambda d: len(d["prompt"]))
    return eintraege


def chunk_ids(prompt: str) -> set[str]:
    """Die im Prompt gezeigten Chunk-IDs — Format "[c-1 | studienbrief S. 3]"."""
    ids = set()
    for stueck in prompt.split("[")[1:]:
        kopf = stueck.split("]", 1)[0]
        if " | " in kopf:
            ids.add(kopf.split(" | ", 1)[0].strip())
    return ids


def auswerten(antwort: str, gueltig: set[str]) -> dict:
    """Kennzahlen einer Modellantwort — Vertragstreue, nicht Geschmack."""
    try:
        d = extrahiere_json(antwort)
    except Exception as fehler:
        return {"lesbar": False, "fehler": str(fehler)[:120], "lehrbloecke": [],
                "fragen": [], "materialluecken": []}
    lb = d.get("lehrbloecke") or []
    fr = d.get("fragen") or []
    alle = [c for a in lb + fr for c in (a.get("chunk_ids") or [])]
    return {
        "lesbar": True,
        "lehrbloecke": lb,
        "fragen": fr,
        "materialluecken": d.get("materialluecken") or [],
        "belege_gesamt": len(alle),
        "belege_gueltig": sum(1 for c in alle if c in gueltig),
        "mc": [f for f in fr if f.get("format") == "mc"],
    }


# Wörter, an denen sich eine Option ausschließen lässt, ohne den Stoff zu kennen.
AUSSCHLUSSWOERTER = ("nur", "niemals", "immer", "ausschließlich", "ignoriert",
                     "keine", "alle", "nie", "stets")


def distraktor_kennzahlen(mc: list) -> dict:
    """Zwei messbare Näherungen für "billige" MC-Fragen.

    Kein Ersatz fürs Lesen, aber sie machen den Eindruck überprüfbar:
    Signalwörter verraten die falsche Option, und eine auffällig längste Option
    ist die klassische Verräterin für die richtige.
    """
    mit_signal = laengste_richtig = auswertbar = 0
    for f in mc:
        optionen = [str(o) for o in (f.get("optionen") or [])]
        if len(optionen) < 2:
            continue
        auswertbar += 1
        antwort = str(f.get("antwort", "")).strip()
        if any(w in o.lower().split() for o in optionen for w in AUSSCHLUSSWOERTER):
            mit_signal += 1
        # Antwort als Buchstabe oder als Volltext — beides kommt vor.
        if len(antwort) == 1 and antwort.upper().isalpha():
            i = ord(antwort.upper()) - 65
            richtig = optionen[i] if 0 <= i < len(optionen) else None
        else:
            richtig = next((o for o in optionen if o.strip() == antwort), None)
        if richtig is not None and len(richtig) == max(len(o) for o in optionen):
            laengste_richtig += 1
    return {"auswertbar": auswertbar, "mit_signalwort": mit_signal,
            "richtige_ist_laengste": laengste_richtig}


def mc_text(auswertung: dict) -> str:
    if not auswertung.get("lesbar"):
        return f"_Antwort nicht auswertbar: {auswertung.get('fehler')}_"
    if not auswertung["mc"]:
        return "_keine MC-Frage_"
    f = auswertung["mc"][0]
    zeilen = [str(f.get("frage_markdown", "")).strip(), ""]
    for i, o in enumerate(f.get("optionen") or []):
        zeilen.append(f"- {chr(65 + i)}) {o}")
    zeilen.append(f"- **angegebene Antwort:** {f.get('antwort')}")
    return "\n".join(zeilen)


def lb_text(auswertung: dict, grenze: int = 900) -> str:
    if not auswertung.get("lesbar"):
        return f"_Antwort nicht auswertbar: {auswertung.get('fehler')}_"
    if not auswertung["lehrbloecke"]:
        return "_kein Lehrblock_"
    return str(auswertung["lehrbloecke"][0].get("inhalt_markdown", ""))[:grenze]


def schreibe_bericht(zeilen_daten: list[dict]) -> None:
    def summe(seite: str, feld: str) -> int:
        return sum(z[seite].get(feld, 0) or 0 for z in zeilen_daten if z[seite]["lesbar"])

    lesbar_a = sum(1 for z in zeilen_daten if z["a"]["lesbar"])
    lesbar_b = sum(1 for z in zeilen_daten if z["b"]["lesbar"])
    n = len(zeilen_daten)
    ba, bb = summe("a", "belege_gesamt"), summe("b", "belege_gesamt")
    ga, gb = summe("a", "belege_gueltig"), summe("b", "belege_gueltig")
    sek = [z["sekunden"] for z in zeilen_daten]
    ka = distraktor_kennzahlen([f for z in zeilen_daten if z["a"]["lesbar"] for f in z["a"]["mc"]])
    kb = distraktor_kennzahlen([f for z in zeilen_daten if z["b"]["lesbar"] for f in z["b"]["mc"]])

    z = [
        f"# Modellvergleich — Modul `{MODUL}`", "",
        f"**A:** `{BASISMODELL}`, System-Prompt v1", "",
        f"**B:** `{VERGLEICHSMODELL}`, System-Prompt {SYSTEM_ETIKETT}", "",
        "Identische Prompts aus dem Antwort-Cache des A-Laufs, wortgleich gegen B "
        "abgespielt. Gleiche Chunks, gleicher System-Prompt.", "",
        "## Zahlen", "",
        "| | A | B |", "|---|---|---|",
        f"| Themen | {n} | {n} |",
        f"| Antwort auswertbar | {lesbar_a}/{n} | {lesbar_b}/{n} |",
        f"| Lehrblöcke | {summe('a','lehrbloecke') if False else sum(len(z['a']['lehrbloecke']) for z in zeilen_daten)} "
        f"| {sum(len(z['b']['lehrbloecke']) for z in zeilen_daten)} |",
        f"| Fragen | {sum(len(z['a']['fragen']) for z in zeilen_daten)} "
        f"| {sum(len(z['b']['fragen']) for z in zeilen_daten)} |",
        f"| davon MC | {sum(len(z['a']['mc']) for z in zeilen_daten if z['a']['lesbar'])} "
        f"| {sum(len(z['b']['mc']) for z in zeilen_daten if z['b']['lesbar'])} |",
        f"| Belege gültig | {ga}/{ba} | {gb}/{bb} |",
        f"| Materiallücken gemeldet | {sum(len(z['a']['materialluecken']) for z in zeilen_daten if z['a']['lesbar'])} "
        f"| {sum(len(z['b']['materialluecken']) for z in zeilen_daten if z['b']['lesbar'])} |",
        f"| MC mit Ausschluss-Signalwort | {ka['mit_signalwort']}/{ka['auswertbar']} "
        f"| {kb['mit_signalwort']}/{kb['auswertbar']} |",
        f"| MC, wo die richtige Option die längste ist | {ka['richtige_ist_laengste']}/{ka['auswertbar']} "
        f"| {kb['richtige_ist_laengste']}/{kb['auswertbar']} |",
        f"| Sekunden/Thema (B) | ~470 | {sum(sek)/len(sek):.0f} |" if sek else "",
        "",
        "Belege gültig heißt: die chunk_id stand wirklich im Prompt. Alles andere "
        "verwirft der Beleg-Vertrag. Die beiden MC-Zeilen sind Näherungen für "
        "billig lösbare Fragen — weniger ist besser.", "",
        "## Themen im Einzelnen", "",
    ]
    for eintrag in zeilen_daten:
        z += [f"### {eintrag['titel']}", "",
              f"_{eintrag['prompt_token']} Prompt-Token, B brauchte "
              f"{eintrag['sekunden']:.0f}s_", "",
              "#### Lehrblock — A", "", lb_text(eintrag["a"]), "",
              "#### Lehrblock — B", "", lb_text(eintrag["b"]), "",
              "#### MC-Frage — A", "", mc_text(eintrag["a"]), "",
              "#### MC-Frage — B", "", mc_text(eintrag["b"]), "",
              "---", ""]
    BERICHT.parent.mkdir(parents=True, exist_ok=True)
    BERICHT.write_text("\n".join(x for x in z if x is not None), encoding="utf-8")
    ROHDATEN.write_text(json.dumps(zeilen_daten, ensure_ascii=False, indent=1),
                        encoding="utf-8")


def main() -> int:
    os.environ.setdefault("LERNPAKET_OLLAMA_CTX", "20480")
    eintraege = lies_cache(BASISMODELL)
    if not eintraege:
        print(f"Keine Generierungs-Prompts für '{BASISMODELL}' unter {CACHE}.")
        return 1
    auswahl = eintraege[:ANZAHL]
    print(f"Vergleich {BASISMODELL} -> {VERGLEICHSMODELL}")
    print(f"{len(auswahl)} von {len(eintraege)} Prompts, "
          f"Bericht nach jedem Thema in {BERICHT}\n", flush=True)

    # Auch Modell B cachen: ein abgebrochener Vergleich soll beim zweiten
    # Anlauf nur die noch fehlenden Themen kosten. Der Schlüssel enthält das
    # Modell, A und B kommen sich also nicht ins Gehege.
    llm = GecachterLLM(hole_llm("ollama", VERGLEICHSMODELL), CACHE)
    daten = []
    for i, eintrag in enumerate(auswahl, start=1):
        gueltig = chunk_ids(eintrag["prompt"])
        t0 = time.time()
        try:
            antwort_b = llm.frage(SYSTEM_B, eintrag["prompt"])
        except Exception as fehler:
            # Ein Ausfall bei einem Thema darf die bisherigen Ergebnisse nicht
            # mitnehmen — die sind teuer erkauft.
            print(f"[{i}/{len(auswahl)}] {eintrag['titel'][:45]}: FEHLER {fehler}",
                  flush=True)
            continue
        dauer = time.time() - t0
        a, b = auswerten(eintrag["antwort"], gueltig), auswerten(antwort_b, gueltig)
        daten.append({"titel": eintrag["titel"], "sekunden": dauer,
                      "prompt_token": len(eintrag["prompt"]) // 3, "a": a, "b": b})
        print(f"[{i}/{len(auswahl)}] {eintrag['titel'][:45]:<47} {dauer:5.0f}s  "
              f"A: {len(a['fragen'])} Fragen / B: "
              f"{len(b['fragen']) if b['lesbar'] else 'unlesbar'}", flush=True)
        schreibe_bericht(daten)

    print(f"\nFertig. {BERICHT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
