// Lädt Lernpakete von der Datei-Grenze (docs/DATEI-VERTRAG.md). Nur lesen —
// Fortschritt gehört in die SQLite-DB, nie ins statische Paket.
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

export const SCHEMA_VERSION = 1;

function lies(pfad) {
  return JSON.parse(readFileSync(pfad, 'utf-8'));
}

export function ladeLernpaket(verzeichnis) {
  const manifest = lies(join(verzeichnis, 'manifest.json'));
  if ((manifest.schema_version ?? 0) > SCHEMA_VERSION) {
    throw new Error(
      `Lernpaket ${manifest.modul_id}: unbekannte schema_version ` +
      `${manifest.schema_version} (Player unterstützt bis ${SCHEMA_VERSION}).`);
  }
  const themen = lies(join(verzeichnis, 'themen.json')).themen;
  const lehrbloecke = lies(join(verzeichnis, 'lehrbloecke.json')).lehrbloecke;
  const fragen = lies(join(verzeichnis, 'quiz.json')).fragen;
  const chunks = [];
  const chunksPfad = join(verzeichnis, 'chunks.jsonl');
  if (existsSync(chunksPfad)) {
    for (const zeile of readFileSync(chunksPfad, 'utf-8').split('\n')) {
      if (zeile.trim()) chunks.push(JSON.parse(zeile));
    }
  }
  return { manifest, themen, lehrbloecke, fragen, chunks };
}

// Scannt das Lernpakete-Verzeichnis; jedes Unterverzeichnis mit gültigem
// manifest.json ist ein unabhängig lernbares Modul (Issue #33).
export function ladeAlleLernpakete(basisVerzeichnis) {
  const pakete = new Map();
  if (!existsSync(basisVerzeichnis)) return pakete;
  for (const eintrag of readdirSync(basisVerzeichnis, { withFileTypes: true })) {
    if (!eintrag.isDirectory()) continue;
    const verzeichnis = join(basisVerzeichnis, eintrag.name);
    if (!existsSync(join(verzeichnis, 'manifest.json'))) continue;
    try {
      const paket = ladeLernpaket(verzeichnis);
      pakete.set(paket.manifest.modul_id, paket);
    } catch (fehler) {
      console.error(`Lernpaket in ${verzeichnis} übersprungen: ${fehler.message}`);
    }
  }
  return pakete;
}
