// Player-Backend: dünner lokaler HTTP-Server (ADR 0005). Liest Lernpakete von
// der Datei-Grenze, hält Fortschritt in SQLite und proxyt den Tutormodus —
// der API-Schlüssel bleibt hier im Backend (Issue #32).
import { createServer } from 'node:http';
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, normalize, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ladeAlleLernpakete } from './lernpakete.js';
import {
  oeffneDb, speichereAntwort, holeThemenStand, holeDiagnoseAntworten,
  setzeEinstellung, holeEinstellung,
} from './db.js';
import { bestimmeLuecken, filtereLehrbloecke, diagnoseFragen, uebungsFragen } from './adaptiv.js';
import { baueWiederholungsplan, tageBis } from './plan.js';
import { erstelleTutor, erstelleLlm, LLM_HINWEIS } from './tutor.js';

const HIER = dirname(fileURLToPath(import.meta.url));
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf',
  '.svg': 'image/svg+xml', '.png': 'image/png',
};

function normalisiereZahl(text) {
  return String(text).trim().replace(',', '.').replace(/\s+/g, '');
}

// Bewertet eine Antwort serverseitig, wo das objektiv geht (mc, rechnen);
// freitext/beweis werden vom Nutzer selbst bewertet (selbst_korrekt).
export function bewerteAntwort(frage, { antwort, selbst_korrekt }) {
  if (frage.format === 'mc') return String(antwort).trim().toUpperCase() === frage.antwort;
  if (frage.format === 'rechnen') {
    return normalisiereZahl(antwort) === normalisiereZahl(frage.antwort);
  }
  return Boolean(selbst_korrekt);
}

export function erstelleApp({
  lernpaketeDir,
  datenDir,
  dbPfad = null,
  llmCall = erstelleLlm(),
} = {}) {
  const pakete = ladeAlleLernpakete(lernpaketeDir);
  const db = oeffneDb(dbPfad ?? join(datenDir, 'fortschritt.db'));
  const tutoren = new Map();
  mkdirSync(join(datenDir, 'nachgeneriert'), { recursive: true });

  function tutorFuer(modulId) {
    if (!tutoren.has(modulId)) {
      tutoren.set(modulId, erstelleTutor({ paket: pakete.get(modulId), llmCall }));
    }
    return tutoren.get(modulId);
  }

  function nachgenerierteBloecke(modulId) {
    const pfad = join(datenDir, 'nachgeneriert', `${modulId}.json`);
    return existsSync(pfad) ? JSON.parse(readFileSync(pfad, 'utf-8')) : [];
  }

  function speichereNachgeneriert(modulId, block) {
    const bloecke = nachgenerierteBloecke(modulId);
    bloecke.push(block);
    writeFileSync(join(datenDir, 'nachgeneriert', `${modulId}.json`),
      JSON.stringify(bloecke, null, 2));
  }

  function lueckenFuer(paket) {
    return bestimmeLuecken(paket.themen, holeDiagnoseAntworten(db, paket.manifest.modul_id));
  }

  function modulUebersicht(paket) {
    const modulId = paket.manifest.modul_id;
    const stand = holeThemenStand(db, modulId);
    const diagnoseFertig = holeEinstellung(db, modulId, 'diagnose_fertig') === '1';
    return {
      modul_id: modulId,
      titel: paket.manifest.titel,
      relevanz_unsicherheit: paket.manifest.relevanz_unsicherheit,
      zielformat: {
        vorschlag: paket.manifest.zielformat.vorschlag,
        begruendung: paket.manifest.zielformat.begruendung ?? '',
        bestaetigt: holeEinstellung(db, modulId, 'zielformat') ?? null,
      },
      klausur_datum: holeEinstellung(db, modulId, 'klausur_datum'),
      diagnose_fertig: diagnoseFertig,
      themen_gesamt: paket.themen.length,
      themen_beherrscht: [...stand.values()].filter((s) => s.staerke >= 0.7).length,
    };
  }

  const routen = [
    ['GET', /^\/api\/module$/, (m, req, url) =>
      [...pakete.values()].map(modulUebersicht)],

    ['GET', /^\/api\/module\/([\w-]+)$/, (m) => {
      const paket = pakete.get(m[1]);
      const stand = holeThemenStand(db, m[1]);
      const luecken = lueckenFuer(paket);
      return {
        ...modulUebersicht(paket),
        materialluecken: paket.manifest.materialluecken,
        themen: paket.themen.map((t) => ({
          ...t,
          staerke: stand.get(t.id)?.staerke ?? null,
          versuche: stand.get(t.id)?.versuche ?? 0,
          luecke: luecken.has(t.id),
        })),
      };
    }],

    ['POST', /^\/api\/module\/([\w-]+)\/zielformat$/, (m, koerper) => {
      const gueltig = ['mc', 'rechnen', 'freitext', 'beweis'];
      if (!gueltig.includes(koerper.format)) throw fehler(400, 'Ungültiges Format');
      setzeEinstellung(db, m[1], 'zielformat', koerper.format);
      return { ok: true, zielformat: koerper.format };
    }],

    ['POST', /^\/api\/module\/([\w-]+)\/klausurdatum$/, (m, koerper) => {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(koerper.datum ?? '')) throw fehler(400, 'Datum als JJJJ-MM-TT');
      setzeEinstellung(db, m[1], 'klausur_datum', koerper.datum);
      return { ok: true };
    }],

    ['GET', /^\/api\/module\/([\w-]+)\/diagnose$/, (m) => {
      const paket = pakete.get(m[1]);
      // Antworten nicht mitschicken — bewertet wird serverseitig.
      return diagnoseFragen(paket.fragen).map(({ antwort, erklaerung_markdown, ...rest }) => rest);
    }],

    ['POST', /^\/api\/module\/([\w-]+)\/antworten$/, (m, koerper) => {
      const paket = pakete.get(m[1]);
      const frage = paket.fragen.find((f) => f.id === koerper.frage_id);
      if (!frage) throw fehler(404, `Unbekannte Frage ${koerper.frage_id}`);
      const korrekt = bewerteAntwort(frage, koerper);
      const staerke = speichereAntwort(db, {
        modulId: m[1], frageId: frage.id, themaId: frage.thema_id,
        korrekt, istDiagnose: Boolean(koerper.ist_diagnose),
      });
      return {
        korrekt,
        richtige_antwort: frage.antwort,
        erklaerung_markdown: frage.erklaerung_markdown ?? '',
        belege: frage.belege,
        staerke,
      };
    }],

    // Musterlösung aufdecken (freitext/beweis) — bewertet und speichert nichts.
    ['GET', /^\/api\/module\/([\w-]+)\/fragen\/([\w-]+)\/loesung$/, (m) => {
      const paket = pakete.get(m[1]);
      const frage = paket.fragen.find((f) => f.id === m[2]);
      if (!frage) throw fehler(404, `Unbekannte Frage ${m[2]}`);
      return {
        richtige_antwort: frage.antwort,
        erklaerung_markdown: frage.erklaerung_markdown ?? '',
        belege: frage.belege,
      };
    }],

    ['POST', /^\/api\/module\/([\w-]+)\/diagnose\/abschliessen$/, (m) => {
      setzeEinstellung(db, m[1], 'diagnose_fertig', '1');
      const paket = pakete.get(m[1]);
      const luecken = lueckenFuer(paket);
      return { ok: true, luecken: [...luecken] };
    }],

    ['GET', /^\/api\/module\/([\w-]+)\/plan$/, (m, req, url) => {
      const paket = pakete.get(m[1]);
      const klausur = holeEinstellung(db, m[1], 'klausur_datum');
      if (!klausur) return { fehlt_klausurdatum: true };
      const heute = url.searchParams.get('heute') ?? new Date().toISOString().slice(0, 10);
      return baueWiederholungsplan({
        themen: paket.themen, stand: holeThemenStand(db, m[1]),
        heute, klausurDatum: klausur,
      });
    }],

    ['GET', /^\/api\/module\/([\w-]+)\/themen\/([\w-]+)\/lehrbloecke$/, (m) => {
      const paket = pakete.get(m[1]);
      const luecken = lueckenFuer(paket);
      const statisch = filtereLehrbloecke(paket.lehrbloecke, m[2], luecken);
      const nachgeneriert = nachgenerierteBloecke(m[1]).filter((b) => b.thema_id === m[2]);
      return {
        luecke: luecken.has(m[2]),
        lehrbloecke: [...statisch, ...nachgeneriert],
      };
    }],

    ['GET', /^\/api\/module\/([\w-]+)\/themen\/([\w-]+)\/quiz$/, (m) => {
      const paket = pakete.get(m[1]);
      const format = holeEinstellung(db, m[1], 'zielformat')
        ?? paket.manifest.zielformat.vorschlag;
      return uebungsFragen(paket.fragen, m[2], format)
        .map(({ antwort, erklaerung_markdown, ...rest }) => rest);
    }],

    ['POST', /^\/api\/module\/([\w-]+)\/tutor$/, async (m, koerper) => {
      if (!koerper.frage?.trim()) throw fehler(400, 'Leere Frage');
      return tutorFuer(m[1]).frage(koerper.frage);
    }],

    ['POST', /^\/api\/module\/([\w-]+)\/tutor\/nachgenerieren$/, async (m, koerper) => {
      const ergebnis = await tutorFuer(m[1]).nachgeneriere(koerper.thema_id, koerper.wunsch);
      if (ergebnis.lehrblock) speichereNachgeneriert(m[1], ergebnis.lehrblock);
      return ergebnis;
    }],
  ];

  function fehler(status, meldung) {
    const f = new Error(meldung);
    f.status = status;
    return f;
  }

  async function behandleApi(req, res, url) {
    const passend = routen.find(([methode, muster]) =>
      methode === req.method && muster.test(url.pathname));
    if (!passend) return false;
    const m = url.pathname.match(passend[1]);
    if (m[1] && url.pathname.startsWith('/api/module/') && !pakete.has(m[1])) {
      res.writeHead(404, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ fehler: `Unbekanntes Modul ${m[1]}` }));
      return true;
    }
    try {
      const koerper = req.method === 'POST' ? await liesJson(req) : req;
      const ergebnis = await passend[2](m, koerper, url);
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(ergebnis));
    } catch (f) {
      res.writeHead(f.status ?? 500, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ fehler: f.message }));
    }
    return true;
  }

  function liesJson(req) {
    return new Promise((aufloesen, ablehnen) => {
      let daten = '';
      req.on('data', (stueck) => { daten += stueck; });
      req.on('end', () => {
        try { aufloesen(daten ? JSON.parse(daten) : {}); } catch (f) { ablehnen(f); }
      });
      req.on('error', ablehnen);
    });
  }

  function sendeDatei(res, basis, relativ) {
    const pfad = normalize(join(basis, relativ));
    if (!pfad.startsWith(normalize(basis)) || !existsSync(pfad)) {
      res.writeHead(404); res.end('Nicht gefunden'); return;
    }
    const endung = pfad.slice(pfad.lastIndexOf('.'));
    res.writeHead(200, { 'content-type': MIME[endung] ?? 'application/octet-stream' });
    res.end(readFileSync(pfad));
  }

  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname.startsWith('/api/')) {
      if (await behandleApi(req, res, url)) return;
      res.writeHead(404, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ fehler: 'Unbekannte Route' }));
      return;
    }
    if (url.pathname.startsWith('/vendor/katex/')) {
      sendeDatei(res, join(HIER, '..', 'node_modules', 'katex', 'dist'),
        url.pathname.slice('/vendor/katex/'.length));
      return;
    }
    sendeDatei(res, join(HIER, '..', 'public'),
      url.pathname === '/' ? 'index.html' : url.pathname.slice(1));
  });
  server.spieler = { pakete, db };
  return server;
}

const istHauptmodul = process.argv[1] && fileURLToPath(import.meta.url) === normalize(process.argv[1]);
if (istHauptmodul) {
  const port = Number(process.env.PORT ?? 4321);
  const server = erstelleApp({
    lernpaketeDir: process.env.LERNPAKETE_DIR ?? join(HIER, '..', '..', 'lernpakete'),
    datenDir: process.env.DATEN_DIR ?? join(HIER, '..', 'daten'),
  });
  server.listen(port, () => {
    console.log(`Player läuft: http://localhost:${port}`);
    if (!erstelleLlm()) {
      console.log(`Hinweis: Tutormodus ist deaktiviert. ${LLM_HINWEIS}`);
    }
  });
}
