// Datei-Grenze: Player lädt Lernpakete und weist Unbekanntes sauber ab (Issue #21, #33).
import { describe, it, expect } from 'vitest';
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { ladeLernpaket, ladeAlleLernpakete } from '../server/lernpakete.js';

const FIXTURES = join(import.meta.dirname, 'fixtures', 'lernpakete');

describe('Lernpakete laden', () => {
  it('lädt ein Fixture-Paket vollständig', () => {
    const paket = ladeLernpaket(join(FIXTURES, 'beispielmodul'));
    expect(paket.manifest.modul_id).toBe('beispielmodul');
    expect(paket.themen).toHaveLength(3);
    expect(paket.fragen.length).toBeGreaterThan(3);
    expect(paket.chunks[0].id).toBe('c-0001');
  });

  it('scannt das Verzeichnis und findet alle Module (Modulauswahl)', () => {
    const pakete = ladeAlleLernpakete(FIXTURES);
    expect([...pakete.keys()].sort()).toEqual(['beispielmodul', 'zweitmodul']);
  });

  it('lehnt unbekannte schema_version mit klarer Meldung ab', () => {
    const dir = mkdtempSync(join(tmpdir(), 'lp-'));
    mkdirSync(join(dir, 'kaputt'));
    writeFileSync(join(dir, 'kaputt', 'manifest.json'), JSON.stringify({
      schema_version: 99, modul_id: 'kaputt', titel: 'Kaputt', erzeugt_am: '',
    }));
    expect(() => ladeLernpaket(join(dir, 'kaputt'))).toThrow(/schema_version/);
    // Beim Scan wird das kaputte Paket übersprungen statt alles zu reißen:
    expect(ladeAlleLernpakete(dir).size).toBe(0);
  });
});
