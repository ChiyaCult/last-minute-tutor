// Integration über die HTTP-Naht: kompletter Lernfluss gegen den echten Server
// mit Fixture-Lernpaketen (PRD: höchste Naht = Datei-Grenze + Player-Verhalten).
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { erstelleApp, bewerteAntwort } from '../server/index.js';

const FIXTURES = join(import.meta.dirname, 'fixtures', 'lernpakete');

let server;
let basis;
let datenDir;

function starte(dir) {
  return new Promise((aufloesen) => {
    const s = erstelleApp({
      lernpaketeDir: FIXTURES,
      datenDir: dir,
      llmCall: async () => 'Geerdete Antwort [c-0001].',
    });
    s.listen(0, () => aufloesen(s));
  });
}

async function api(pfad, optionen = {}) {
  const antwort = await fetch(`${basis}/api${pfad}`, {
    headers: { 'content-type': 'application/json' },
    ...optionen,
    body: optionen.body ? JSON.stringify(optionen.body) : undefined,
  });
  return { status: antwort.status, daten: await antwort.json() };
}

beforeAll(async () => {
  datenDir = mkdtempSync(join(tmpdir(), 'lp-daten-'));
  server = await starte(datenDir);
  basis = `http://localhost:${server.address().port}`;
});
afterAll(() => server.close());

describe('Modulauswahl (Issue #33)', () => {
  it('listet beide Fixture-Module unabhängig', async () => {
    const { daten } = await api('/module');
    expect(daten.map((m) => m.modul_id).sort()).toEqual(['beispielmodul', 'zweitmodul']);
  });

  it('404 für unbekanntes Modul', async () => {
    const { status } = await api('/module/gibt-es-nicht');
    expect(status).toBe(404);
  });
});

describe('Diagnose → Lücke → Freischaltung (Issues #21, #26)', () => {
  it('liefert das Diagnosequiz ohne Antworten', async () => {
    const { daten } = await api('/module/beispielmodul/diagnose');
    expect(daten).toHaveLength(3);
    expect(daten[0].antwort).toBeUndefined();
    expect(daten.every((f) => f.belege.length > 0)).toBe(true);
  });

  it('bewertet Antworten serverseitig und erfasst sie', async () => {
    // t-01 falsch, t-02 und t-03 richtig:
    const a1 = await api('/module/beispielmodul/antworten', {
      method: 'POST',
      body: { frage_id: 'q-t-01-mc-1', antwort: 'A', ist_diagnose: true } });
    expect(a1.daten.korrekt).toBe(false);
    expect(a1.daten.richtige_antwort).toBe('B');
    expect(a1.daten.belege[0].position).toBe('S. 12');
    const a2 = await api('/module/beispielmodul/antworten', {
      method: 'POST',
      body: { frage_id: 'q-t-02-mc-1', antwort: 'C', ist_diagnose: true } });
    expect(a2.daten.korrekt).toBe(true);
    await api('/module/beispielmodul/antworten', {
      method: 'POST',
      body: { frage_id: 'q-t-03-mc-1', antwort: 'A', ist_diagnose: true } });
  });

  it('bestimmt die Lücken aus dem Antwortmuster', async () => {
    const { daten } = await api('/module/beispielmodul/diagnose/abschliessen', {
      method: 'POST', body: {} });
    expect(daten.luecken).toEqual(['t-01']);
  });

  it('schaltet Vertiefung nur für die Lücke frei', async () => {
    const luecke = await api('/module/beispielmodul/themen/t-01/lehrbloecke');
    expect(luecke.daten.luecke).toBe(true);
    expect(luecke.daten.lehrbloecke.map((b) => b.tiefe).sort())
      .toEqual(['auffrischung', 'vertiefung']);
    const beherrscht = await api('/module/beispielmodul/themen/t-02/lehrbloecke');
    expect(beherrscht.daten.luecke).toBe(false);
    expect(beherrscht.daten.lehrbloecke.map((b) => b.tiefe)).toEqual(['auffrischung']);
  });
});

describe('Zielformat bestätigen/korrigieren (Issue #24)', () => {
  it('übernimmt eine Korrektur und filtert das Übungsquiz danach', async () => {
    await api('/module/beispielmodul/zielformat', {
      method: 'POST', body: { format: 'rechnen' } });
    const { daten } = await api('/module/beispielmodul');
    expect(daten.zielformat.bestaetigt).toBe('rechnen');
    const quiz = await api('/module/beispielmodul/themen/t-01/quiz');
    expect(quiz.daten.every((f) => f.format === 'rechnen')).toBe(true);
  });

  it('weist ungültige Formate ab', async () => {
    const { status } = await api('/module/beispielmodul/zielformat', {
      method: 'POST', body: { format: 'tanzen' } });
    expect(status).toBe(400);
  });
});

describe('Wiederholungsplan über die API (Issue #27)', () => {
  it('verlangt erst ein Klausurdatum, plant dann fensteradaptiv', async () => {
    const ohne = await api('/module/beispielmodul/plan?heute=2026-07-16');
    expect(ohne.daten.fehlt_klausurdatum).toBe(true);
    await api('/module/beispielmodul/klausurdatum', {
      method: 'POST', body: { datum: '2026-07-19' } });
    const { daten } = await api('/module/beispielmodul/plan?heute=2026-07-16');
    expect(daten.modus).toBe('triage');
    // t-01 ist die schwache Lücke und steht vorn:
    expect(daten.tage_liste[0].themen[0]).toBe('t-01');
  });
});

describe('Tutormodus über die API (Issue #32)', () => {
  it('antwortet geerdet mit Belegen; der Schlüssel bleibt im Backend', async () => {
    const { daten } = await api('/module/beispielmodul/tutor', {
      method: 'POST', body: { frage: 'Wie funktioniert Quicksort?' } });
    expect(daten.antwort_markdown).toContain('Geerdete Antwort');
    expect(daten.belege[0].chunk_id).toBe('c-0001');
    expect(JSON.stringify(daten)).not.toMatch(/api[-_]?key/i);
  });

  it('nachgenerierter Lehrblock erscheint unter dem Thema', async () => {
    await api('/module/beispielmodul/tutor/nachgenerieren', {
      method: 'POST', body: { thema_id: 't-01', wunsch: 'Pivot' } });
    const { daten } = await api('/module/beispielmodul/themen/t-01/lehrbloecke');
    expect(daten.lehrbloecke.some((b) => b.nachgeneriert)).toBe(true);
  });
});

describe('Fortschritt getrennt je Modul + Persistenz über Neustart (Issues #27, #33)', () => {
  it('zweitmodul bleibt von beispielmodul-Antworten unberührt', async () => {
    const { daten } = await api('/module/zweitmodul');
    expect(daten.themen[0].versuche).toBe(0);
    expect(daten.diagnose_fertig).toBe(false);
  });

  it('überlebt einen Server-Neustart (simulierte neue Session)', async () => {
    server.close();
    server = await starte(datenDir);
    basis = `http://localhost:${server.address().port}`;
    const { daten } = await api('/module/beispielmodul');
    expect(daten.diagnose_fertig).toBe(true);
    expect(daten.zielformat.bestaetigt).toBe('rechnen');
    const t01 = daten.themen.find((t) => t.id === 't-01');
    expect(t01.versuche).toBeGreaterThan(0);
    expect(t01.luecke).toBe(true);
  });
});

describe('Antwort-Bewertung', () => {
  it('rechnen normalisiert Komma/Punkt', () => {
    const frage = { format: 'rechnen', antwort: '3.14' };
    expect(bewerteAntwort(frage, { antwort: '3,14' })).toBe(true);
    expect(bewerteAntwort(frage, { antwort: '3,15' })).toBe(false);
  });

  it('freitext/beweis nutzen die Selbstbewertung', () => {
    const frage = { format: 'beweis', antwort: 'Musterlösung' };
    expect(bewerteAntwort(frage, { selbst_korrekt: true })).toBe(true);
    expect(bewerteAntwort(frage, { selbst_korrekt: false })).toBe(false);
  });
});
