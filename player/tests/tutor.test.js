// Tutormodus: geerdetes Q&A mit Belegen + Nachgenerieren (Issue #32).
import { describe, it, expect } from 'vitest';
import { join } from 'node:path';

import { erstelleTutor } from '../server/tutor.js';
import { erstelleIndex } from '../server/bm25.js';
import { ladeLernpaket } from '../server/lernpakete.js';

const paket = ladeLernpaket(join(import.meta.dirname, 'fixtures', 'lernpakete', 'beispielmodul'));

describe('BM25-Retrieval', () => {
  it('findet den inhaltlich passenden Chunk zuerst', () => {
    const index = erstelleIndex(paket.chunks);
    const treffer = index.suche('Wie funktioniert das Mischen bei Mergesort?');
    expect(treffer[0].chunk.id).toBe('c-0002');
  });
});

describe('Tutormodus', () => {
  it('erdet die Antwort in den Chunks und liefert Belege aus Zitaten', async () => {
    const gesehen = [];
    const tutor = erstelleTutor({
      paket,
      llmCall: async (system, prompt) => {
        gesehen.push({ system, prompt });
        return 'Quicksort arbeitet rekursiv [c-0001] und das Pivot teilt die Liste [c-0004].';
      },
    });
    const antwort = await tutor.frage('Wie funktioniert Quicksort?');
    // Der Prompt enthält die Retrieval-Chunks (Erdung), nicht nur die Frage:
    expect(gesehen[0].prompt).toContain('Quicksort ist ein rekursives Sortierverfahren');
    expect(gesehen[0].system).toMatch(/Materiallücke/i);
    expect(antwort.belege.map((b) => b.chunk_id)).toEqual(['c-0001', 'c-0004']);
    expect(antwort.belege[0].position).toBe('S. 12');
  });

  it('faellt ohne Zitate auf die Top-Retrieval-Chunks als Belege zurück', async () => {
    const tutor = erstelleTutor({ paket, llmCall: async () => 'Antwort ohne Zitate.' });
    const antwort = await tutor.frage('Quicksort?');
    expect(antwort.belege.length).toBeGreaterThan(0);
    expect(antwort.belege[0].chunk_id).toMatch(/^c-/);
  });

  it('nachgenerieren liefert einen belegten Vertiefungs-Lehrblock', async () => {
    const tutor = erstelleTutor({
      paket,
      llmCall: async () => 'Vertiefung: Das Mischen ist linear [c-0002].',
    });
    const { lehrblock } = await tutor.nachgeneriere('t-02', 'Mischschritt');
    expect(lehrblock.thema_id).toBe('t-02');
    expect(lehrblock.tiefe).toBe('vertiefung');
    expect(lehrblock.nachgeneriert).toBe(true);
    expect(lehrblock.belege[0].chunk_id).toBe('c-0002');
  });

  it('meldet ohne API-Schlüssel einen klaren Fehler statt zu raten', async () => {
    const tutor = erstelleTutor({ paket, llmCall: null });
    const antwort = await tutor.frage('Egal');
    expect(antwort.fehler).toMatch(/ANTHROPIC_API_KEY/);
  });
});
