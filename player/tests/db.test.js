// Fortschritts-Persistenz über simulierte Sessions (Issue #27, Akzeptanzkriterium).
import { describe, it, expect } from 'vitest';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  oeffneDb, speichereAntwort, holeThemenStand, holeDiagnoseAntworten,
  setzeEinstellung, holeEinstellung,
} from '../server/db.js';

describe('SQLite-Fortschritt', () => {
  it('persistiert über simulierte Sessions (DB schließen und neu öffnen)', () => {
    const pfad = join(mkdtempSync(join(tmpdir(), 'lp-db-')), 'fortschritt.db');

    // Session 1: Diagnose beantworten, Einstellung setzen.
    let db = oeffneDb(pfad);
    speichereAntwort(db, { modulId: 'm1', frageId: 'q1', themaId: 't-01', korrekt: false, istDiagnose: true });
    speichereAntwort(db, { modulId: 'm1', frageId: 'q2', themaId: 't-02', korrekt: true, istDiagnose: true });
    setzeEinstellung(db, 'm1', 'zielformat', 'mc');
    db.close();

    // Session 2: alles ist noch da.
    db = oeffneDb(pfad);
    const stand = holeThemenStand(db, 'm1');
    expect(stand.get('t-01').staerke).toBe(0);
    expect(stand.get('t-02').staerke).toBe(1);
    expect(holeDiagnoseAntworten(db, 'm1')).toHaveLength(2);
    expect(holeEinstellung(db, 'm1', 'zielformat')).toBe('mc');

    // Session 2 weiter: Üben verbessert die Stärke träge.
    const s1 = speichereAntwort(db, { modulId: 'm1', frageId: 'q1', themaId: 't-01', korrekt: true });
    expect(s1).toBeGreaterThan(0);
    expect(s1).toBeLessThan(1); // eine richtige Antwort macht kein beherrschtes Thema
    db.close();
  });

  it('hält Fortschritt je Modul getrennt (Issue #33)', () => {
    const db = oeffneDb(':memory:');
    speichereAntwort(db, { modulId: 'modul-a', frageId: 'q1', themaId: 't-01', korrekt: true });
    speichereAntwort(db, { modulId: 'modul-b', frageId: 'q1', themaId: 't-01', korrekt: false });
    expect(holeThemenStand(db, 'modul-a').get('t-01').staerke).toBe(1);
    expect(holeThemenStand(db, 'modul-b').get('t-01').staerke).toBe(0);
    setzeEinstellung(db, 'modul-a', 'zielformat', 'mc');
    expect(holeEinstellung(db, 'modul-b', 'zielformat')).toBeNull();
  });
});
