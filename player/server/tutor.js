// Tutormodus (Issue #32, ADR 0002/0003): freie Rückfragen und Nachgenerieren,
// geerdet via Retrieval über die Paket-Chunks, mit Belegen. Der Remote-Call
// läuft ausschließlich hier im Backend — der API-Schlüssel (ANTHROPIC_API_KEY)
// bleibt in der Server-Umgebung und erreicht nie das Frontend.
import { erstelleIndex } from './bm25.js';

const MODELL = 'claude-sonnet-5';
const SYSTEM = 'Du bist Tutor für ein Prüfungsmodul. Antworte NUR auf Basis der ' +
  'mitgelieferten Quell-Chunks und zitiere jede tragende Aussage mit [chunk_id]. ' +
  'Wenn die Chunks die Frage nicht beantworten, sage das offen (Materiallücke) ' +
  'statt zu spekulieren. Formeln als LaTeX in $...$. Antworte knapp auf Deutsch.';

export function erstelleAnthropicLlm(apiKey = process.env.ANTHROPIC_API_KEY) {
  if (!apiKey) return null;
  return async function llmCall(system, prompt, maxTokens = 1500) {
    const antwort = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: MODELL, max_tokens: maxTokens, system,
        messages: [{ role: 'user', content: prompt }],
      }),
    });
    if (!antwort.ok) throw new Error(`LLM-Fehler ${antwort.status}: ${await antwort.text()}`);
    const daten = await antwort.json();
    return daten.content.map((block) => block.text ?? '').join('');
  };
}

function chunkKontext(treffer) {
  return treffer.map(({ chunk }) =>
    `[${chunk.id} | ${chunk.quelle} ${chunk.position}]\n${chunk.text}`).join('\n\n');
}

function zitierteBelege(text, treffer, alleChunks) {
  const proId = new Map(alleChunks.map((chunk) => [chunk.id, chunk]));
  const belege = [];
  for (const [, id] of text.matchAll(/\[(c-\d+)\]/g)) {
    const chunk = proId.get(id);
    if (chunk && !belege.some((b) => b.chunk_id === chunk.id)) {
      belege.push({ quelle: chunk.quelle, position: chunk.position, chunk_id: chunk.id });
    }
  }
  if (belege.length === 0) {
    // Keine expliziten Zitate: die Retrieval-Grundlage selbst ist der Beleg.
    for (const { chunk } of treffer.slice(0, 3)) {
      belege.push({ quelle: chunk.quelle, position: chunk.position, chunk_id: chunk.id });
    }
  }
  return belege;
}

export function erstelleTutor({ paket, llmCall }) {
  const index = erstelleIndex(paket.chunks);

  async function frage(text) {
    if (!llmCall) {
      return { fehler: 'Tutormodus benötigt ANTHROPIC_API_KEY in der Server-Umgebung.' };
    }
    const treffer = index.suche(text, 6);
    if (treffer.length === 0) {
      return {
        antwort_markdown: 'Dazu findet sich nichts in den Modulmaterialien ' +
          '(Materiallücke). Bitte im Original nachschlagen.',
        belege: [], materialluecke: true,
      };
    }
    const prompt = `Quell-Chunks aus den Modulmaterialien:\n\n${chunkKontext(treffer)}\n\n` +
      `Frage des Lernenden: ${text}`;
    const antwort = await llmCall(SYSTEM, prompt);
    return {
      antwort_markdown: antwort,
      belege: zitierteBelege(antwort, treffer, paket.chunks),
      materialluecke: /materiallücke/i.test(antwort),
    };
  }

  // Nachgenerieren: zusätzlicher Lehrblock zu einem Thema, geerdet in den Chunks.
  async function nachgeneriere(themaId, wunsch) {
    if (!llmCall) {
      return { fehler: 'Tutormodus benötigt ANTHROPIC_API_KEY in der Server-Umgebung.' };
    }
    const thema = paket.themen.find((t) => t.id === themaId);
    if (!thema) return { fehler: `Unbekanntes Thema ${themaId}` };
    const treffer = index.suche(`${thema.titel} ${wunsch ?? ''}`, 8);
    const prompt = `Quell-Chunks:\n\n${chunkKontext(treffer)}\n\n` +
      `Erzeuge einen zusätzlichen Lehrblock (Markdown) zum Thema "${thema.titel}"` +
      (wunsch ? ` mit Fokus auf: ${wunsch}.` : '.') +
      ' Nur belegbarer Inhalt, tragende Aussagen mit [chunk_id] zitieren.';
    const inhalt = await llmCall(SYSTEM, prompt, 2500);
    return {
      lehrblock: {
        id: `lb-${themaId}-nach-${Date.now()}`,
        thema_id: themaId,
        tiefe: 'vertiefung',
        inhalt_markdown: inhalt,
        belege: zitierteBelege(inhalt, treffer, paket.chunks),
        nachgeneriert: true,
      },
    };
  }

  return { frage, nachgeneriere };
}
