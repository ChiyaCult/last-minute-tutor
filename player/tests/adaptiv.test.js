// Adaptive Lehrtiefe: Diagnose → Lücke → Freischaltung (Issue #26).
import { describe, it, expect } from 'vitest';
import {
  bestimmeLuecken, freigeschalteteTiefen, filtereLehrbloecke, diagnoseFragen,
} from '../server/adaptiv.js';
import { ladeLernpaket } from '../server/lernpakete.js';
import { join } from 'node:path';

const paket = ladeLernpaket(join(import.meta.dirname, 'fixtures', 'lernpakete', 'beispielmodul'));

describe('Freischalt-Entscheidung je Antwortmuster (Akzeptanz #26)', () => {
  it('falsch beantwortet → Lücke; richtig → beherrscht', () => {
    const luecken = bestimmeLuecken(paket.themen, [
      { thema_id: 't-01', korrekt: 0 },
      { thema_id: 't-02', korrekt: 1 },
      { thema_id: 't-03', korrekt: 1 },
    ]);
    expect(luecken.has('t-01')).toBe(true);
    expect(luecken.has('t-02')).toBe(false);
    expect(luecken.has('t-03')).toBe(false);
  });

  it('ohne Diagnose-Antwort gilt ein Thema als Lücke (nicht raten)', () => {
    const luecken = bestimmeLuecken(paket.themen, [{ thema_id: 't-01', korrekt: 1 }]);
    expect(luecken.has('t-01')).toBe(false);
    expect(luecken.has('t-02')).toBe(true);
  });

  it('mehrere Antworten pro Thema werden gemittelt', () => {
    const luecken = bestimmeLuecken(paket.themen, [
      { thema_id: 't-01', korrekt: 1 }, { thema_id: 't-01', korrekt: 0 },
    ]);
    expect(luecken.has('t-01')).toBe(true); // 50 % < Beherrschungs-Schwelle
  });
});

describe('Lehrtiefen-Freischaltung', () => {
  const luecken = new Set(['t-01']);

  it('nur Lücken bekommen Vertiefung', () => {
    expect(freigeschalteteTiefen('t-01', luecken)).toEqual(['auffrischung', 'vertiefung']);
    expect(freigeschalteteTiefen('t-02', luecken)).toEqual(['auffrischung']);
  });

  it('filtert Lehrblöcke entsprechend', () => {
    const fuerLuecke = filtereLehrbloecke(paket.lehrbloecke, 't-01', luecken);
    expect(fuerLuecke.map((b) => b.tiefe).sort()).toEqual(['auffrischung', 'vertiefung']);
    const beherrscht = filtereLehrbloecke(paket.lehrbloecke, 't-02', luecken);
    expect(beherrscht.map((b) => b.tiefe)).toEqual(['auffrischung']);
  });
});

describe('Diagnosequiz-Auswahl', () => {
  it('nimmt nur Diagnose-Fragen und blendet Verifikations-Abweichungen aus', () => {
    const fragen = diagnoseFragen(paket.fragen);
    expect(fragen.every((f) => f.diagnose)).toBe(true);
    expect(fragen.some((f) => f.verifikation.status === 'abweichung')).toBe(false);
    expect(fragen).toHaveLength(3);
  });
});
