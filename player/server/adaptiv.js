// Adaptive Lehrtiefe (Issue #26): Diagnose → Lücke → Freischaltung.
// Das Diagnosequiz misst, was der Nutzer schon kann; nur echte Lücken
// schalten Vertiefungs-Lehrblöcke frei, Beherrschtes wird nur aufgefrischt.
import { BEHERRSCHT_AB } from './db.js';

// Bestimmt Lücken aus den Diagnose-Antworten. Ein Thema ohne Diagnose-Antwort
// gilt als Lücke (nicht raten — lieber lehren).
export function bestimmeLuecken(themen, diagnoseAntworten) {
  const proThema = new Map();
  for (const antwort of diagnoseAntworten) {
    const bisher = proThema.get(antwort.thema_id) ?? { richtig: 0, gesamt: 0 };
    bisher.gesamt += 1;
    bisher.richtig += antwort.korrekt ? 1 : 0;
    proThema.set(antwort.thema_id, bisher);
  }
  const luecken = new Set();
  for (const thema of themen) {
    const stand = proThema.get(thema.id);
    if (!stand || stand.richtig / stand.gesamt < BEHERRSCHT_AB) luecken.add(thema.id);
  }
  return luecken;
}

// Welche Lehrtiefen sind für ein Thema freigeschaltet?
export function freigeschalteteTiefen(themaId, luecken) {
  return luecken.has(themaId) ? ['auffrischung', 'vertiefung'] : ['auffrischung'];
}

export function filtereLehrbloecke(lehrbloecke, themaId, luecken) {
  const tiefen = new Set(freigeschalteteTiefen(themaId, luecken));
  return lehrbloecke.filter((b) => b.thema_id === themaId && tiefen.has(b.tiefe));
}

export function diagnoseFragen(fragen) {
  // Verifikations-Abweichungen werden nie ausgespielt (ADR 0003).
  return fragen.filter((f) => f.diagnose && f.verifikation?.status !== 'abweichung');
}

export function uebungsFragen(fragen, themaId, zielformat) {
  const brauchbar = fragen.filter(
    (f) => f.thema_id === themaId && f.verifikation?.status !== 'abweichung');
  const imFormat = brauchbar.filter((f) => f.format === zielformat);
  return imFormat.length > 0 ? imFormat : brauchbar;
}
