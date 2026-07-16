// Wiederholungsplan: Triage bei 3 Tagen, echtes Spacing bei 2 Wochen (Issue #27, ADR 0006).
import { describe, it, expect } from 'vitest';
import { baueWiederholungsplan, tageBis } from '../server/plan.js';

const themen = [
  { id: 't-schwach', titel: 'Schwach', relevanz: 0.9 },
  { id: 't-mittel', titel: 'Mittel', relevanz: 0.5 },
  { id: 't-stark', titel: 'Stark', relevanz: 0.3 },
];
const stand = new Map([
  ['t-schwach', { staerke: 0.1 }],
  ['t-mittel', { staerke: 0.5 }],
  ['t-stark', { staerke: 0.95 }],
]);

describe('fensteradaptives Kippen (Akzeptanz #27)', () => {
  it('3 Tage → Triage: jeden Tag alles, Schwächstes zuerst', () => {
    const plan = baueWiederholungsplan({
      themen, stand, heute: '2026-07-16', klausurDatum: '2026-07-19' });
    expect(plan.modus).toBe('triage');
    expect(plan.tage_liste).toHaveLength(3);
    for (const tag of plan.tage_liste) {
      expect(tag.themen[0]).toBe('t-schwach');
      expect(new Set(tag.themen)).toEqual(new Set(['t-schwach', 't-mittel', 't-stark']));
    }
  });

  it('2 Wochen → echtes Spacing mit wachsenden Abständen', () => {
    const plan = baueWiederholungsplan({
      themen, stand, heute: '2026-07-16', klausurDatum: '2026-07-30' });
    expect(plan.modus).toBe('spacing');
    expect(plan.tage_liste).toHaveLength(14);
    const tageVon = (id) => plan.tage_liste.filter((t) => t.themen.includes(id)).map((t) => t.tag);
    // Schwaches Thema kommt gezielt mehrfach zurück …
    expect(tageVon('t-schwach').length).toBeGreaterThanOrEqual(4);
    // … mit wachsenden Abständen (Spacing, kein tägliches Cramming):
    const abstaende = tageVon('t-schwach').slice(1).map((t, i) => t - tageVon('t-schwach')[i]);
    expect(Math.max(...abstaende)).toBeGreaterThan(Math.min(...abstaende));
    // Starkes Thema wird nur aufgefrischt:
    expect(tageVon('t-stark').length).toBeLessThanOrEqual(3);
    // Alles kommt am Vortag der Klausur zurück:
    const vortag = plan.tage_liste.at(-1);
    expect(new Set(vortag.themen)).toEqual(new Set(['t-schwach', 't-mittel', 't-stark']));
  });

  it('unbekannter Stand zählt als schwach', () => {
    const plan = baueWiederholungsplan({
      themen, stand: new Map(), heute: '2026-07-16', klausurDatum: '2026-07-30' });
    const schwachTage = plan.tage_liste.filter((t) => t.themen.includes('t-stark'));
    expect(schwachTage.length).toBeGreaterThanOrEqual(4);
  });
});

describe('tageBis', () => {
  it('zählt Kalendertage und klemmt auf mindestens 1', () => {
    expect(tageBis('2026-07-16', '2026-07-19')).toBe(3);
    expect(tageBis('2026-07-16', '2026-07-16')).toBe(1);
    expect(tageBis('2026-07-16', '2026-07-01')).toBe(1);
  });
});
