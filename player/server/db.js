// Fortschritts-Persistenz in SQLite (ADR 0005, Issue #27). Eine DB für alle
// Module; jede Zeile trägt modul_id — Fortschritt bleibt je Modul getrennt
// (Issue #33). Generierter Inhalt liegt NIE hier, nur Lernstand.
import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

// Stärke-Fortschreibung: exponentiell gleitender Mittelwert. Träge genug,
// dass eine Glückantwort kein Thema "beherrscht" macht, schnell genug für
// ein 3-Tage-Fenster.
const GEWICHT_NEU = 0.4;
export const BEHERRSCHT_AB = 0.7;

export function oeffneDb(pfad) {
  if (pfad !== ':memory:') mkdirSync(dirname(pfad), { recursive: true });
  const db = new DatabaseSync(pfad);
  db.exec(`
    CREATE TABLE IF NOT EXISTS antworten (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      modul_id TEXT NOT NULL,
      frage_id TEXT NOT NULL,
      thema_id TEXT NOT NULL,
      korrekt INTEGER NOT NULL,
      ist_diagnose INTEGER NOT NULL DEFAULT 0,
      beantwortet_am TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS themen_stand (
      modul_id TEXT NOT NULL,
      thema_id TEXT NOT NULL,
      staerke REAL NOT NULL,
      versuche INTEGER NOT NULL DEFAULT 0,
      zuletzt TEXT,
      PRIMARY KEY (modul_id, thema_id)
    );
    CREATE TABLE IF NOT EXISTS einstellungen (
      modul_id TEXT NOT NULL,
      schluessel TEXT NOT NULL,
      wert TEXT NOT NULL,
      PRIMARY KEY (modul_id, schluessel)
    );
  `);
  return db;
}

export function speichereAntwort(db, { modulId, frageId, themaId, korrekt, istDiagnose = false, zeit = new Date() }) {
  db.prepare(
    `INSERT INTO antworten (modul_id, frage_id, thema_id, korrekt, ist_diagnose, beantwortet_am)
     VALUES (?, ?, ?, ?, ?, ?)`
  ).run(modulId, frageId, themaId, korrekt ? 1 : 0, istDiagnose ? 1 : 0, zeit.toISOString());

  const bisher = db.prepare(
    'SELECT staerke, versuche FROM themen_stand WHERE modul_id = ? AND thema_id = ?'
  ).get(modulId, themaId);
  const wert = korrekt ? 1 : 0;
  const staerke = bisher
    ? bisher.staerke * (1 - GEWICHT_NEU) + wert * GEWICHT_NEU
    : wert;
  db.prepare(
    `INSERT INTO themen_stand (modul_id, thema_id, staerke, versuche, zuletzt)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT (modul_id, thema_id) DO UPDATE SET
       staerke = excluded.staerke, versuche = excluded.versuche, zuletzt = excluded.zuletzt`
  ).run(modulId, themaId, staerke, (bisher?.versuche ?? 0) + 1, zeit.toISOString());
  return staerke;
}

export function holeThemenStand(db, modulId) {
  const stand = new Map();
  for (const zeile of db.prepare(
    'SELECT thema_id, staerke, versuche, zuletzt FROM themen_stand WHERE modul_id = ?'
  ).all(modulId)) {
    stand.set(zeile.thema_id, zeile);
  }
  return stand;
}

export function holeDiagnoseAntworten(db, modulId) {
  return db.prepare(
    `SELECT frage_id, thema_id, korrekt FROM antworten
     WHERE modul_id = ? AND ist_diagnose = 1 ORDER BY id`
  ).all(modulId);
}

export function setzeEinstellung(db, modulId, schluessel, wert) {
  db.prepare(
    `INSERT INTO einstellungen (modul_id, schluessel, wert) VALUES (?, ?, ?)
     ON CONFLICT (modul_id, schluessel) DO UPDATE SET wert = excluded.wert`
  ).run(modulId, schluessel, String(wert));
}

export function holeEinstellung(db, modulId, schluessel) {
  return db.prepare(
    'SELECT wert FROM einstellungen WHERE modul_id = ? AND schluessel = ?'
  ).get(modulId, schluessel)?.wert ?? null;
}
