// Tutormodus (Issue #32, ADR 0002/0003): freie Rückfragen und Nachgenerieren,
// geerdet via Retrieval über die Paket-Chunks, mit Belegen. Der Remote-Call
// läuft ausschließlich hier im Backend — API-Schlüssel bleiben in der
// Server-Umgebung und erreichen nie das Frontend. Anbieter-Auswahl wie in der
// Pipeline: LERNPAKET_LLM (anthropic|gemini|copilot|ollama) + LERNPAKET_LLM_MODELL,
// ohne explizite Wahl Auto-Erkennung über ANTHROPIC_API_KEY/GEMINI_API_KEY.
import { erstelleIndex } from './bm25.js';

const STANDARD_MODELLE = {
  anthropic: 'claude-sonnet-5',
  // Stabiler Alias; Pro-Modelle haben im Free Tier kein Kontingent (429).
  gemini: 'gemini-flash-latest',
  copilot: 'openai/gpt-4o',
  ollama: 'llama3.1',
};
export const LLM_HINWEIS = 'LLM-Anbindung konfigurieren: ANTHROPIC_API_KEY oder ' +
  'GEMINI_API_KEY setzen, oder explizit LERNPAKET_LLM=copilot (GITHUB_TOKEN) ' +
  'bzw. LERNPAKET_LLM=ollama (lokaler Server).';
const SYSTEM = 'Du bist Tutor für ein Prüfungsmodul. Antworte NUR auf Basis der ' +
  'mitgelieferten Quell-Chunks und zitiere jede tragende Aussage mit [chunk_id]. ' +
  'Wenn die Chunks die Frage nicht beantworten, sage das offen (Materiallücke) ' +
  'statt zu spekulieren. Formeln als LaTeX in $...$. Antworte knapp auf Deutsch.';

async function liesAntwort(antwort) {
  if (!antwort.ok) throw new Error(`LLM-Fehler ${antwort.status}: ${await antwort.text()}`);
  return antwort.json();
}

export function erstelleAnthropicLlm(apiKey = process.env.ANTHROPIC_API_KEY,
                                     modell = STANDARD_MODELLE.anthropic) {
  if (!apiKey) return null;
  return async function llmCall(system, prompt, maxTokens = 1500) {
    const daten = await liesAntwort(await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: modell, max_tokens: maxTokens, system,
        messages: [{ role: 'user', content: prompt }],
      }),
    }));
    return daten.content.map((block) => block.text ?? '').join('');
  };
}

export function erstelleGeminiLlm(apiKey = process.env.GEMINI_API_KEY ?? process.env.GOOGLE_API_KEY,
                                  modell = STANDARD_MODELLE.gemini) {
  if (!apiKey) return null;
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${modell}:generateContent`;
  return async function llmCall(system, prompt, maxTokens = 1500) {
    const daten = await liesAntwort(await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-goog-api-key': apiKey },
      body: JSON.stringify({
        system_instruction: { parts: [{ text: system }] },
        contents: [{ role: 'user', parts: [{ text: prompt }] }],
        generationConfig: { maxOutputTokens: maxTokens },
      }),
    }));
    const teile = daten.candidates?.[0]?.content?.parts ?? [];
    return teile.map((t) => t.text ?? '').join('');
  };
}

// Chat-Completions-Schnittstelle — deckt GitHub Models (Copilot) und Ollama ab.
export function erstelleOpenAiKompatiblesLlm(basisUrl, modell, apiKey = '') {
  const headers = { 'content-type': 'application/json' };
  if (apiKey) headers.authorization = `Bearer ${apiKey}`;
  return async function llmCall(system, prompt, maxTokens = 1500) {
    const daten = await liesAntwort(await fetch(`${basisUrl.replace(/\/$/, '')}/chat/completions`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        model: modell, max_tokens: maxTokens,
        messages: [{ role: 'system', content: system }, { role: 'user', content: prompt }],
      }),
    }));
    return daten.choices?.[0]?.message?.content ?? '';
  };
}

export function erstelleLlm(umgebung = process.env) {
  const anbieter = umgebung.LERNPAKET_LLM?.trim().toLowerCase();
  const modell = umgebung.LERNPAKET_LLM_MODELL;
  if (anbieter === 'anthropic') {
    return erstelleAnthropicLlm(umgebung.ANTHROPIC_API_KEY,
      modell ?? STANDARD_MODELLE.anthropic);
  }
  if (anbieter === 'gemini') {
    return erstelleGeminiLlm(umgebung.GEMINI_API_KEY ?? umgebung.GOOGLE_API_KEY,
      modell ?? STANDARD_MODELLE.gemini);
  }
  if (anbieter === 'copilot') {
    const token = umgebung.GITHUB_TOKEN ?? umgebung.COPILOT_API_KEY;
    if (!token) return null;
    return erstelleOpenAiKompatiblesLlm(
      umgebung.LERNPAKET_COPILOT_URL ?? 'https://models.github.ai/inference',
      modell ?? STANDARD_MODELLE.copilot, token);
  }
  if (anbieter === 'ollama') {
    const basis = (umgebung.LERNPAKET_OLLAMA_URL ?? 'http://localhost:11434')
      .replace(/\/$/, '') + '/v1';
    return erstelleOpenAiKompatiblesLlm(basis,
      modell ?? umgebung.LERNPAKET_OLLAMA_MODELL ?? STANDARD_MODELLE.ollama);
  }
  // Keine explizite Wahl: nur eindeutige Schlüssel auto-erkennen (wie Pipeline).
  return erstelleAnthropicLlm(umgebung.ANTHROPIC_API_KEY, modell ?? STANDARD_MODELLE.anthropic)
    ?? erstelleGeminiLlm(umgebung.GEMINI_API_KEY ?? umgebung.GOOGLE_API_KEY,
      modell ?? STANDARD_MODELLE.gemini);
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
      return { fehler: `Tutormodus benötigt eine LLM-Anbindung in der Server-Umgebung. ${LLM_HINWEIS}` };
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
      return { fehler: `Tutormodus benötigt eine LLM-Anbindung in der Server-Umgebung. ${LLM_HINWEIS}` };
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
