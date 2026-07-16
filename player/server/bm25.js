// Lexikalisches Retrieval (BM25) über die Chunks des Lernpakets — die
// Erdungs-Grundlage des Tutormodus (ADR 0007): kein Modell-Download, offline,
// deterministisch; die Chunks der Aufbereitung werden 1:1 wiederverwendet.
const TOKEN_RE = /[a-zäöüß0-9]{2,}/g;

export function tokenisiere(text) {
  return (text.toLowerCase().match(TOKEN_RE) ?? []);
}

export function erstelleIndex(chunks, { k1 = 1.5, b = 0.75 } = {}) {
  const dokumente = chunks.map((chunk) => ({ chunk, tokens: tokenisiere(chunk.text) }));
  const df = new Map();
  let gesamtLaenge = 0;
  for (const dok of dokumente) {
    gesamtLaenge += dok.tokens.length;
    for (const token of new Set(dok.tokens)) df.set(token, (df.get(token) ?? 0) + 1);
  }
  const mittlereLaenge = dokumente.length ? gesamtLaenge / dokumente.length : 0;
  const n = dokumente.length;

  function suche(anfrage, topK = 5) {
    const anfrageTokens = tokenisiere(anfrage);
    const treffer = [];
    for (const dok of dokumente) {
      const tf = new Map();
      for (const t of dok.tokens) tf.set(t, (tf.get(t) ?? 0) + 1);
      let score = 0;
      for (const token of new Set(anfrageTokens)) {
        const h = tf.get(token);
        if (!h) continue;
        const idf = Math.log(1 + (n - df.get(token) + 0.5) / (df.get(token) + 0.5));
        score += idf * (h * (k1 + 1)) /
          (h + k1 * (1 - b + b * dok.tokens.length / (mittlereLaenge || 1)));
      }
      if (score > 0) treffer.push({ chunk: dok.chunk, score });
    }
    treffer.sort((a, b2) => b2.score - a.score || a.chunk.id.localeCompare(b2.chunk.id));
    return treffer.slice(0, topK);
  }

  return { suche };
}
