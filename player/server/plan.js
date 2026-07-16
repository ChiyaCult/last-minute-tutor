// Wiederholungsplan (Issue #27, ADR 0006): fensteradaptive Eigenlogik statt
// SM-2/FSRS. Begründung: Das Fenster ist 3 Tage bis 2 Wochen — klassische
// SRS-Intervalle (Wochen/Monate) greifen nie. Zwei Modi:
//   - Triage  (<= 4 Tage): jeden Tag alles, schwach & relevant zuerst.
//   - Spacing (> 4 Tage):  komprimierte Intervalle nach Stärke; schwache
//     Themen kommen mehrfach zurück, alles kommt am Vortag der Klausur wieder.
import { BEHERRSCHT_AB } from './db.js';

export const TRIAGE_GRENZE_TAGE = 4;
const MS_PRO_TAG = 24 * 60 * 60 * 1000;

function alsDatum(wert) {
  const d = wert instanceof Date ? new Date(wert) : new Date(`${wert}T00:00:00`);
  d.setHours(0, 0, 0, 0);
  return d;
}

export function tageBis(heute, klausurDatum) {
  const diff = Math.round((alsDatum(klausurDatum) - alsDatum(heute)) / MS_PRO_TAG);
  return Math.max(1, diff);
}

function prioritaet(thema, staerke) {
  // Schwäche dominiert, Relevanzsignal bricht Gleichstände.
  return (1 - staerke) * 0.7 + (thema.relevanz ?? 0.3) * 0.3;
}

// Wiederholungs-Offsets (Tag 0 = heute) je nach Stärke, in das Fenster gestaucht.
function spacingOffsets(staerke, tage) {
  const vortag = tage - 1;
  let basis;
  if (staerke < 0.4) basis = [0, 1, 3, 6, 10, 15, 21];
  else if (staerke < BEHERRSCHT_AB) basis = [0, 2, 6, 12, 20];
  else basis = [1, Math.floor(tage / 2)];
  const offsets = new Set(basis.filter((t) => t < vortag));
  offsets.add(vortag); // alles kommt am Vortag der Klausur zurück
  return [...offsets].sort((a, b) => a - b);
}

export function baueWiederholungsplan({ themen, stand, heute, klausurDatum }) {
  const tage = tageBis(heute, klausurDatum);
  const modus = tage <= TRIAGE_GRENZE_TAGE ? 'triage' : 'spacing';
  const staerkeVon = (id) => stand.get?.(id)?.staerke ?? stand.get?.(id) ?? 0;

  const tageListe = [];
  for (let tag = 0; tag < tage; tag++) {
    tageListe.push({ tag, datum: neuesDatum(heute, tag), themen: [] });
  }

  if (modus === 'triage') {
    // Jeden Tag alle Themen, sortiert nach Priorität — bei 3 Tagen zählt
    // Wiederholung von allem mehr als perfekte Verteilung.
    const sortiert = [...themen].sort(
      (a, b) => prioritaet(b, staerkeVon(b.id)) - prioritaet(a, staerkeVon(a.id)));
    for (const tag of tageListe) tag.themen = sortiert.map((t) => t.id);
  } else {
    for (const thema of themen) {
      for (const offset of spacingOffsets(staerkeVon(thema.id), tage)) {
        tageListe[offset].themen.push(thema.id);
      }
    }
    for (const tag of tageListe) {
      tag.themen.sort((a, b) => {
        const ta = themen.find((t) => t.id === a);
        const tb = themen.find((t) => t.id === b);
        return prioritaet(tb, staerkeVon(b)) - prioritaet(ta, staerkeVon(a));
      });
    }
  }
  return { modus, tage, tage_liste: tageListe };
}

function neuesDatum(heute, plusTage) {
  const d = alsDatum(heute);
  d.setDate(d.getDate() + plusTage);
  return d.toISOString().slice(0, 10);
}
