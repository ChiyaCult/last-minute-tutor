"""Der Datei-Vertrag: Datenmodell des Lernpakets und Schreiben/Lesen der Dateien.

Schema: docs/DATEI-VERTRAG.md. Jedes generierte Artefakt trägt verpflichtend
Belege (ADR 0003) — das Feld ist hier nicht optional, sein Inhalt darf leer sein.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

from . import SCHEMA_VERSION


@dataclass
class Beleg:
    quelle: str  # studienbrief | vorlesung | altklausur | uebung | folie
    position: str = ""
    chunk_id: str = ""


@dataclass
class Materialluecke:
    thema_id: str
    beschreibung: str
    art: str  # schweigen | widerspruch


@dataclass
class Chunk:
    id: str
    quelle: str
    position: str
    text: str


@dataclass
class Thema:
    id: str
    titel: str
    beschreibung: str = ""
    relevanz: float = 0.3
    relevanzsignale: List[str] = field(default_factory=lambda: ["abdeckung"])
    belege: List[Beleg] = field(default_factory=list)


@dataclass
class Lehrblock:
    id: str
    thema_id: str
    tiefe: str  # auffrischung | vertiefung
    inhalt_markdown: str
    belege: List[Beleg] = field(default_factory=list)


@dataclass
class Verifikation:
    status: str = "ungeprueft"  # bestaetigt | abweichung | ungeprueft
    hinweis: str = ""


@dataclass
class Frage:
    id: str
    thema_id: str
    format: str  # mc | rechnen | freitext | beweis
    frage_markdown: str
    antwort: str
    diagnose: bool = False
    optionen: Optional[List[str]] = None
    erklaerung_markdown: str = ""
    belege: List[Beleg] = field(default_factory=list)
    verifikation: Verifikation = field(default_factory=Verifikation)


@dataclass
class Zielformat:
    vorschlag: str  # mc | rechnen | freitext | beweis
    begruendung: str = ""


@dataclass
class Quelle:
    art: str  # studienbrief | vorlesung | altklausur | uebung
    datei: str


@dataclass
class Manifest:
    modul_id: str
    titel: str
    erzeugt_am: str
    quellen: List[Quelle] = field(default_factory=list)
    optionalquellen_vorhanden: bool = False
    relevanz_unsicherheit: str = "hoch"  # niedrig | hoch
    zielformat: Zielformat = field(default_factory=lambda: Zielformat("freitext"))
    materialluecken: List[Materialluecke] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION


@dataclass
class Lernpaket:
    manifest: Manifest
    themen: List[Thema] = field(default_factory=list)
    lehrbloecke: List[Lehrblock] = field(default_factory=list)
    fragen: List[Frage] = field(default_factory=list)
    chunks: List[Chunk] = field(default_factory=list)


def _dump(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def schreibe_lernpaket(paket: Lernpaket, ziel: Path) -> Path:
    """Schreibt das Lernpaket-Verzeichnis gemäß Datei-Vertrag und gibt es zurück."""
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "manifest.json").write_text(_dump(asdict(paket.manifest)), encoding="utf-8")
    (ziel / "themen.json").write_text(
        _dump({"themen": [asdict(t) for t in paket.themen]}), encoding="utf-8"
    )
    (ziel / "lehrbloecke.json").write_text(
        _dump({"lehrbloecke": [asdict(l) for l in paket.lehrbloecke]}), encoding="utf-8"
    )
    (ziel / "quiz.json").write_text(
        _dump({"fragen": [asdict(f) for f in paket.fragen]}), encoding="utf-8"
    )
    with (ziel / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in paket.chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False, sort_keys=True) + "\n")
    return ziel


def _beleg_von(d: dict) -> Beleg:
    return Beleg(quelle=d.get("quelle", ""), position=d.get("position", "") or "",
                 chunk_id=d.get("chunk_id", "") or "")


def lade_lernpaket(pfad: Path) -> Lernpaket:
    """Liest ein Lernpaket-Verzeichnis zurück (für Tests und Validierung)."""
    pfad = Path(pfad)
    m = json.loads((pfad / "manifest.json").read_text(encoding="utf-8"))
    if m.get("schema_version", 0) > SCHEMA_VERSION:
        raise ValueError(
            f"Unbekannte schema_version {m['schema_version']} (unterstützt: {SCHEMA_VERSION})"
        )
    manifest = Manifest(
        modul_id=m["modul_id"], titel=m["titel"], erzeugt_am=m["erzeugt_am"],
        quellen=[Quelle(**q) for q in m.get("quellen", [])],
        optionalquellen_vorhanden=m.get("optionalquellen_vorhanden", False),
        relevanz_unsicherheit=m.get("relevanz_unsicherheit", "hoch"),
        zielformat=Zielformat(**m.get("zielformat", {"vorschlag": "freitext"})),
        materialluecken=[Materialluecke(**x) for x in m.get("materialluecken", [])],
        schema_version=m.get("schema_version", SCHEMA_VERSION),
    )
    themen = [
        Thema(id=t["id"], titel=t["titel"], beschreibung=t.get("beschreibung", ""),
              relevanz=t.get("relevanz", 0.3),
              relevanzsignale=t.get("relevanzsignale", ["abdeckung"]),
              belege=[_beleg_von(b) for b in t.get("belege", [])])
        for t in json.loads((pfad / "themen.json").read_text(encoding="utf-8"))["themen"]
    ]
    lehrbloecke = [
        Lehrblock(id=l["id"], thema_id=l["thema_id"], tiefe=l["tiefe"],
                  inhalt_markdown=l["inhalt_markdown"],
                  belege=[_beleg_von(b) for b in l.get("belege", [])])
        for l in json.loads((pfad / "lehrbloecke.json").read_text(encoding="utf-8"))["lehrbloecke"]
    ]
    fragen = [
        Frage(id=f["id"], thema_id=f["thema_id"], format=f["format"],
              frage_markdown=f["frage_markdown"], antwort=f["antwort"],
              diagnose=f.get("diagnose", False), optionen=f.get("optionen"),
              erklaerung_markdown=f.get("erklaerung_markdown", ""),
              belege=[_beleg_von(b) for b in f.get("belege", [])],
              verifikation=Verifikation(**f.get("verifikation", {})))
        for f in json.loads((pfad / "quiz.json").read_text(encoding="utf-8"))["fragen"]
    ]
    chunks = []
    chunks_datei = pfad / "chunks.jsonl"
    if chunks_datei.exists():
        for zeile in chunks_datei.read_text(encoding="utf-8").splitlines():
            if zeile.strip():
                chunks.append(Chunk(**json.loads(zeile)))
    return Lernpaket(manifest=manifest, themen=themen, lehrbloecke=lehrbloecke,
                     fragen=fragen, chunks=chunks)


def pruefe_vertrag(paket: Lernpaket) -> List[str]:
    """Prüft die Vertrags-Invarianten; gibt Verstöße als Meldungen zurück.

    Zentral: jedes Artefakt trägt ein Beleg-Feld (Liste vorhanden; Inhalt darf
    im Durchstich leer sein) und referenzierte IDs existieren.
    """
    fehler: List[str] = []
    themen_ids = {t.id for t in paket.themen}
    chunk_ids = {c.id for c in paket.chunks}
    for lb in paket.lehrbloecke:
        if lb.thema_id not in themen_ids:
            fehler.append(f"Lehrblock {lb.id}: unbekanntes Thema {lb.thema_id}")
        if lb.tiefe not in ("auffrischung", "vertiefung"):
            fehler.append(f"Lehrblock {lb.id}: ungültige Tiefe {lb.tiefe}")
    for fr in paket.fragen:
        if fr.thema_id not in themen_ids:
            fehler.append(f"Frage {fr.id}: unbekanntes Thema {fr.thema_id}")
        if fr.format not in ("mc", "rechnen", "freitext", "beweis"):
            fehler.append(f"Frage {fr.id}: ungültiges Format {fr.format}")
        if fr.format == "mc" and not fr.optionen:
            fehler.append(f"Frage {fr.id}: MC ohne Optionen")
        if fr.belege is None:
            fehler.append(f"Frage {fr.id}: Beleg-Feld fehlt")
    for sammlung, art in ((paket.themen, "Thema"), (paket.lehrbloecke, "Lehrblock"),
                          (paket.fragen, "Frage")):
        for artefakt in sammlung:
            for beleg in artefakt.belege:
                if beleg.chunk_id and beleg.chunk_id not in chunk_ids:
                    fehler.append(
                        f"{art} {artefakt.id}: Beleg zeigt auf unbekannten Chunk {beleg.chunk_id}"
                    )
    return fehler
