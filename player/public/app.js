// Player-Frontend: Modulauswahl → Diagnosequiz → adaptive Lehrtiefe →
// Wiederholungsplan → Tutormodus. Spricht nur mit dem lokalen Backend;
// der API-Schlüssel des Tutormodus existiert hier nirgends (Issue #32).

const app = document.getElementById('app');
const brotkrumen = document.getElementById('brotkrumen');

async function api(pfad, optionen = {}) {
  const antwort = await fetch(`/api${pfad}`, {
    headers: { 'content-type': 'application/json' },
    ...optionen,
    body: optionen.body ? JSON.stringify(optionen.body) : undefined,
  });
  const daten = await antwort.json();
  if (!antwort.ok) throw new Error(daten.fehler ?? antwort.statusText);
  return daten;
}

// --- Mini-Markdown (mit HTML-Escaping); $...$ bleibt für KaTeX stehen -------

function escapeHtml(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function inlineMd(text) {
  return text
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|\s)\*([^*]+)\*/g, '$1<em>$2</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
}

function renderMarkdown(md) {
  const zeilen = escapeHtml(md ?? '').split('\n');
  const teile = [];
  let i = 0;
  while (i < zeilen.length) {
    const zeile = zeilen[i];
    if (zeile.startsWith('```')) {
      const block = [];
      i++;
      while (i < zeilen.length && !zeilen[i].startsWith('```')) block.push(zeilen[i++]);
      i++;
      teile.push(`<pre><code>${block.join('\n')}</code></pre>`);
      continue;
    }
    if (/^\|.*\|$/.test(zeile.trim())) {
      const tabelle = [];
      while (i < zeilen.length && /^\|.*\|$/.test(zeilen[i].trim())) tabelle.push(zeilen[i++].trim());
      const reihen = tabelle.filter((z) => !/^\|[\s\-|]+\|$/.test(z))
        .map((z, idx) => {
          const zellen = z.slice(1, -1).split('|').map((c) => inlineMd(c.trim()));
          const tag = idx === 0 && tabelle.length > 1 ? 'th' : 'td';
          return `<tr>${zellen.map((c) => `<${tag}>${c}</${tag}>`).join('')}</tr>`;
        });
      teile.push(`<table>${reihen.join('')}</table>`);
      continue;
    }
    const h = zeile.match(/^(#{1,4})\s+(.*)$/);
    if (h) { teile.push(`<h${h[1].length + 2}>${inlineMd(h[2])}</h${h[1].length + 2}>`); i++; continue; }
    if (/^[-*]\s+/.test(zeile)) {
      const punkte = [];
      while (i < zeilen.length && /^[-*]\s+/.test(zeilen[i])) {
        punkte.push(`<li>${inlineMd(zeilen[i].replace(/^[-*]\s+/, ''))}</li>`);
        i++;
      }
      teile.push(`<ul>${punkte.join('')}</ul>`);
      continue;
    }
    if (zeile.trim() === '') { i++; continue; }
    const absatz = [];
    while (i < zeilen.length && zeilen[i].trim() !== '' && !/^(#{1,4}\s|[-*]\s|```|\|)/.test(zeilen[i])) {
      absatz.push(zeilen[i++]);
    }
    teile.push(`<p>${inlineMd(absatz.join(' '))}</p>`);
  }
  return `<div class="inhalt">${teile.join('\n')}</div>`;
}

function typesetze(knoten) {
  if (window.renderMathInElement) {
    window.renderMathInElement(knoten, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$', right: '$', display: false },
      ],
      throwOnError: false,
    });
  }
}

// --- Bausteine ---------------------------------------------------------------

const FORMAT_NAMEN = { mc: 'Multiple Choice', rechnen: 'Rechenaufgabe', freitext: 'Freitext', beweis: 'Beweis' };

function belegChips(belege) {
  if (!belege?.length) return '<span class="chip warnung">ohne Beleg</span>';
  return belege.map((b) =>
    `<span class="chip beleg" title="Beleg: ${escapeHtml(b.quelle)}">📖 ${escapeHtml(b.quelle)} ${escapeHtml(b.position ?? '')}</span>`
  ).join('');
}

function materialLueckenHtml(luecken) {
  if (!luecken?.length) return '';
  return `<div class="karte"><h2>⚠️ Materiallücken</h2>
    <p class="hinweis">Hier schweigen oder widersprechen sich die Materialien —
    markiert statt erfunden. Kandidaten für den Tutormodus oder das Original.</p>
    ${luecken.map((l) => `<div class="materialluecke"><strong>${escapeHtml(l.art)}</strong>:
      ${escapeHtml(l.beschreibung)}</div>`).join('')}</div>`;
}

// --- Ansichten ---------------------------------------------------------------

async function zeigeModulListe() {
  brotkrumen.textContent = 'Module';
  const module = await api('/module');
  if (module.length === 0) {
    app.innerHTML = `<div class="karte"><h2>Keine Lernpakete gefunden</h2>
      <p>Erst die Aufbereitung laufen lassen:</p>
      <pre>cd pipeline && lernpaket &lt;modul-verzeichnis&gt; --ziel ../lernpakete</pre></div>`;
    return;
  }
  app.innerHTML = `<div class="modul-liste">${module.map((m) => `
    <div class="karte modul-karte" data-modul="${m.modul_id}">
      <h2>${escapeHtml(m.titel)}</h2>
      <p class="hinweis">${m.themen_beherrscht}/${m.themen_gesamt} Themen beherrscht</p>
      <div class="balken"><div style="width:${m.themen_gesamt ? (100 * m.themen_beherrscht / m.themen_gesamt) : 0}%"></div></div>
      <p>
        <span class="chip">${FORMAT_NAMEN[m.zielformat.bestaetigt ?? m.zielformat.vorschlag]}${m.zielformat.bestaetigt ? '' : ' (Vorschlag)'}</span>
        ${m.relevanz_unsicherheit === 'hoch' ? '<span class="chip warnung">Relevanz unsicher (keine Optionalquellen)</span>' : ''}
        ${m.klausur_datum ? `<span class="chip">Klausur: ${m.klausur_datum}</span>` : ''}
      </p>
    </div>`).join('')}</div>`;
  app.querySelectorAll('[data-modul]').forEach((el) =>
    el.addEventListener('click', () => { location.hash = `#/modul/${el.dataset.modul}`; }));
}

async function zeigeModul(modulId) {
  const m = await api(`/module/${modulId}`);
  brotkrumen.textContent = m.titel;
  const format = m.zielformat.bestaetigt ?? m.zielformat.vorschlag;

  const zielformatKarte = m.zielformat.bestaetigt ? '' : `
    <div class="karte"><h2>Zielformat bestätigen</h2>
      <p>Vorschlag: <strong>${FORMAT_NAMEN[m.zielformat.vorschlag]}</strong>
      <span class="hinweis">— ${escapeHtml(m.zielformat.begruendung)}</span></p>
      <div class="aktionen">
        <button class="primaer" id="format-ok">Passt</button>
        <select id="format-wahl">
          ${Object.entries(FORMAT_NAMEN).map(([k, name]) =>
            `<option value="${k}" ${k === m.zielformat.vorschlag ? 'selected' : ''}>${name}</option>`).join('')}
        </select>
        <button id="format-korrigieren">Korrigieren</button>
      </div></div>`;

  const planHtml = m.klausur_datum
    ? '<div id="plan-inhalt">Lade Plan …</div>'
    : '<p class="hinweis">Klausurdatum setzen, um den Wiederholungsplan zu starten.</p>';

  app.innerHTML = `
    ${zielformatKarte}
    <div class="karte"><h2>Diagnosequiz</h2>
      ${m.diagnose_fertig
        ? '<p><span class="chip ok">abgeschlossen</span> Lücken schalten Vertiefung frei; Beherrschtes wird nur aufgefrischt.</p>'
        : '<p>Misst, was du schon kannst — nur echte Lücken bekommen Lehrtiefe.</p>'}
      <div class="aktionen">
        <button class="primaer" id="diagnose-start">${m.diagnose_fertig ? 'Diagnose wiederholen' : 'Diagnose starten'}</button>
      </div></div>
    <div class="karte"><h2>Wiederholungsplan</h2>
      <div class="aktionen" style="margin-bottom:0.6rem">
        <label>Klausurdatum: <input type="date" id="klausur-datum" value="${m.klausur_datum ?? ''}"></label>
        <button id="klausur-speichern">Speichern</button>
      </div>
      ${planHtml}</div>
    <div class="karte"><h2>Themen (${m.themen.length})</h2><div id="themen"></div></div>
    ${materialLueckenHtml(m.materialluecken)}
    <div class="karte"><h2>🎓 Tutormodus</h2>
      <p class="hinweis">Freie Rückfragen, geerdet in den Modulmaterialien — mit Belegen.
      Läuft über das lokale Backend (Schlüssel bleibt dort).</p>
      <div class="tutor-verlauf" id="tutor-verlauf"></div>
      <div class="tutor-eingabe">
        <input id="tutor-frage" placeholder="Frage zum Stoff …">
        <button class="primaer" id="tutor-senden">Fragen</button>
      </div></div>`;

  const themenDiv = app.querySelector('#themen');
  themenDiv.innerHTML = m.themen.map((t) => {
    const staerke = t.staerke ?? 0;
    return `<div class="thema-zeile">
      <div><span class="titel">${escapeHtml(t.titel)}</span>
        <small>${escapeHtml(t.beschreibung)} · Relevanz ${(t.relevanz * 100).toFixed(0)} %
          ${t.relevanzsignale.filter((s) => s !== 'abdeckung').map((s) => `<span class="chip">${escapeHtml(s)}</span>`).join('')}
        </small></div>
      <div class="balken ${staerke < 0.7 ? 'schwach' : ''}"><div style="width:${staerke * 100}%"></div></div>
      ${t.luecke ? '<span class="chip luecke">Lücke</span>' : '<span class="chip ok">beherrscht</span>'}
      <button data-thema="${t.id}">Lernen</button>
    </div>`;
  }).join('');
  themenDiv.querySelectorAll('[data-thema]').forEach((el) =>
    el.addEventListener('click', () => { location.hash = `#/modul/${modulId}/thema/${el.dataset.thema}`; }));

  app.querySelector('#diagnose-start').addEventListener('click', () => {
    location.hash = `#/modul/${modulId}/diagnose`;
  });
  app.querySelector('#format-ok')?.addEventListener('click', async () => {
    await api(`/module/${modulId}/zielformat`, { method: 'POST', body: { format: m.zielformat.vorschlag } });
    zeigeModul(modulId);
  });
  app.querySelector('#format-korrigieren')?.addEventListener('click', async () => {
    await api(`/module/${modulId}/zielformat`, {
      method: 'POST', body: { format: app.querySelector('#format-wahl').value } });
    zeigeModul(modulId);
  });
  app.querySelector('#klausur-speichern').addEventListener('click', async () => {
    const datum = app.querySelector('#klausur-datum').value;
    if (!datum) return;
    await api(`/module/${modulId}/klausurdatum`, { method: 'POST', body: { datum } });
    zeigeModul(modulId);
  });

  if (m.klausur_datum) zeigePlan(modulId, m.themen);
  richteTutorEin(modulId);
}

async function zeigePlan(modulId, themen) {
  const plan = await api(`/module/${modulId}/plan`);
  const ziel = app.querySelector('#plan-inhalt');
  if (!ziel || plan.fehlt_klausurdatum) return;
  const titelVon = (id) => themen.find((t) => t.id === id)?.titel ?? id;
  ziel.innerHTML = `
    <p><span class="chip ${plan.modus === 'triage' ? 'luecke' : 'ok'}">Modus: ${plan.modus}</span>
    <span class="hinweis">${plan.modus === 'triage'
      ? `${plan.tage} Tage bis zur Klausur — Triage: jeden Tag das Schwächste zuerst.`
      : `${plan.tage} Tage — verteiltes Wiederholen, schwache Themen kommen mehrfach zurück.`}</span></p>
    ${plan.tage_liste.slice(0, 5).map((tag) => `
      <div class="plan-tag"><span class="datum">${tag.datum}${tag.tag === 0 ? ' (heute)' : ''}</span> —
        ${tag.themen.slice(0, 8).map((id) => `<span class="chip">${escapeHtml(titelVon(id))}</span>`).join('')}
        ${tag.themen.length > 8 ? `<span class="hinweis">+${tag.themen.length - 8} weitere</span>` : ''}
      </div>`).join('')}
    ${plan.tage_liste.length > 5 ? `<p class="hinweis">… und ${plan.tage_liste.length - 5} weitere Tage</p>` : ''}`;
}

function richteTutorEin(modulId) {
  const verlauf = app.querySelector('#tutor-verlauf');
  const eingabe = app.querySelector('#tutor-frage');
  const senden = app.querySelector('#tutor-senden');

  async function frageStellen() {
    const frage = eingabe.value.trim();
    if (!frage) return;
    eingabe.value = '';
    verlauf.insertAdjacentHTML('beforeend',
      `<div class="tutor-nachricht nutzer">${escapeHtml(frage)}</div>`);
    const laden = document.createElement('div');
    laden.className = 'tutor-nachricht tutor';
    laden.textContent = 'Denke nach …';
    verlauf.appendChild(laden);
    try {
      const antwort = await api(`/module/${modulId}/tutor`, { method: 'POST', body: { frage } });
      if (antwort.fehler) {
        laden.innerHTML = `<span class="fehler">${escapeHtml(antwort.fehler)}</span>`;
        return;
      }
      laden.innerHTML = `${renderMarkdown(antwort.antwort_markdown)}
        <div>${belegChips(antwort.belege)}</div>
        ${antwort.materialluecke ? '<span class="chip warnung">Materiallücke</span>' : ''}`;
      typesetze(laden);
    } catch (f) {
      laden.innerHTML = `<span class="fehler">${escapeHtml(f.message)}</span>`;
    }
  }
  senden.addEventListener('click', frageStellen);
  eingabe.addEventListener('keydown', (e) => { if (e.key === 'Enter') frageStellen(); });
}

// --- Quiz (Diagnose und Üben) -------------------------------------------------

async function zeigeQuiz(modulId, fragen, { istDiagnose, titel, zurueck }) {
  brotkrumen.textContent = titel;
  let index = 0;
  let richtig = 0;

  async function sende(frage, nutzlast) {
    return api(`/module/${modulId}/antworten`, {
      method: 'POST',
      body: { frage_id: frage.id, ist_diagnose: istDiagnose, ...nutzlast },
    });
  }

  function zeigeFrage() {
    if (index >= fragen.length) { zeigeErgebnis(); return; }
    const frage = fragen[index];
    app.innerHTML = `<div class="karte">
      <p class="hinweis">Frage ${index + 1}/${fragen.length} ·
        <span class="chip">${FORMAT_NAMEN[frage.format]}</span></p>
      <div id="frage-text">${renderMarkdown(frage.frage_markdown)}</div>
      <div id="antwort-bereich"></div>
      <div id="feedback"></div>
      <div>${belegChips(frage.belege)}</div>
    </div>`;
    typesetze(app.querySelector('#frage-text'));

    const bereich = app.querySelector('#antwort-bereich');
    if (frage.format === 'mc') {
      bereich.innerHTML = `<div class="frage-optionen">${frage.optionen.map((o, i) =>
        `<button data-buchstabe="${'ABCD'[i]}"><strong>${'ABCD'[i]})</strong> ${escapeHtml(o)}</button>`).join('')}</div>`;
      bereich.querySelectorAll('button').forEach((knopf) =>
        knopf.addEventListener('click', async () => {
          bereich.querySelectorAll('button').forEach((b) => { b.disabled = true; });
          const ergebnis = await sende(frage, { antwort: knopf.dataset.buchstabe });
          knopf.classList.add(ergebnis.korrekt ? 'korrekt' : 'falsch');
          if (!ergebnis.korrekt) {
            bereich.querySelector(`[data-buchstabe="${ergebnis.richtige_antwort}"]`)
              ?.classList.add('korrekt');
          }
          zeigeFeedback(ergebnis);
        }));
    } else if (frage.format === 'rechnen') {
      bereich.innerHTML = `<div class="aktionen">
        <input id="rechnen-eingabe" placeholder="Ergebnis">
        <button class="primaer" id="rechnen-ok">Prüfen</button></div>`;
      bereich.querySelector('#rechnen-ok').addEventListener('click', async () => {
        const ergebnis = await sende(frage, { antwort: bereich.querySelector('#rechnen-eingabe').value });
        zeigeFeedback(ergebnis);
      });
    } else {
      // freitext / beweis: Musterlösung aufdecken, dann Selbstbewertung.
      bereich.innerHTML = `<div class="aktionen"><button class="primaer" id="aufdecken">Musterlösung aufdecken</button></div>`;
      bereich.querySelector('#aufdecken').addEventListener('click', async () => {
        const loesung = await api(`/module/${modulId}/fragen/${frage.id}/loesung`);
        bereich.innerHTML = `
          <div class="feedback" id="musterloesung"></div>
          <div class="aktionen">
            <button class="primaer" id="wusste">✓ Wusste ich</button>
            <button id="wusste-nicht">✗ Wusste ich nicht</button>
          </div>`;
        const ml = bereich.querySelector('#musterloesung');
        ml.innerHTML = renderMarkdown(loesung.richtige_antwort)
          + `<div>${belegChips(loesung.belege)}</div>`;
        typesetze(ml);
        const selbst = async (korrekt) => {
          const ergebnis = await sende(frage, { selbst_korrekt: korrekt });
          zeigeFeedback(ergebnis, korrekt);
        };
        bereich.querySelector('#wusste').addEventListener('click', () => selbst(true));
        bereich.querySelector('#wusste-nicht').addEventListener('click', () => selbst(false));
      });
    }

    function zeigeFeedback(ergebnis, selbstKorrekt = null) {
      const korrekt = selbstKorrekt ?? ergebnis.korrekt;
      if (korrekt) richtig += 1;
      const feedback = app.querySelector('#feedback');
      feedback.innerHTML = `
        <div class="feedback ${korrekt ? 'korrekt' : 'falsch'}">
          <strong>${korrekt ? 'Richtig!' : `Leider nein — richtig: ${escapeHtml(ergebnis.richtige_antwort)}`}</strong>
          ${ergebnis.erklaerung_markdown ? renderMarkdown(ergebnis.erklaerung_markdown) : ''}
          <div>${belegChips(ergebnis.belege)}</div>
        </div>
        <div class="aktionen"><button class="primaer" id="weiter">Weiter</button></div>`;
      typesetze(feedback);
      feedback.querySelector('#weiter').addEventListener('click', () => { index += 1; zeigeFrage(); });
    }
  }

  async function zeigeErgebnis() {
    if (istDiagnose) {
      const abschluss = await api(`/module/${modulId}/diagnose/abschliessen`, { method: 'POST', body: {} });
      app.innerHTML = `<div class="karte"><h2>Diagnose abgeschlossen</h2>
        <p>${richtig}/${fragen.length} richtig. ${abschluss.luecken.length} Lücke(n) erkannt —
        dafür ist jetzt Vertiefung freigeschaltet; der Rest wird nur aufgefrischt.</p>
        <div class="aktionen"><button class="primaer" id="zurueck">Zum Modul</button></div></div>`;
    } else {
      app.innerHTML = `<div class="karte"><h2>Runde beendet</h2>
        <p>${richtig}/${fragen.length} richtig.</p>
        <div class="aktionen"><button class="primaer" id="zurueck">Zurück</button></div></div>`;
    }
    app.querySelector('#zurueck').addEventListener('click', zurueck);
  }

  if (fragen.length === 0) {
    app.innerHTML = `<div class="karte"><p>Keine Fragen verfügbar.</p>
      <div class="aktionen"><button class="primaer" id="zurueck">Zurück</button></div></div>`;
    app.querySelector('#zurueck').addEventListener('click', zurueck);
    return;
  }
  zeigeFrage();
}

async function zeigeDiagnose(modulId) {
  const fragen = await api(`/module/${modulId}/diagnose`);
  zeigeQuiz(modulId, fragen, {
    istDiagnose: true, titel: 'Diagnosequiz',
    zurueck: () => { location.hash = `#/modul/${modulId}`; },
  });
}

// --- Thema lernen: Lehrblöcke + Üben + Nachgenerieren --------------------------

async function zeigeThema(modulId, themaId) {
  const [modul, bloecke] = await Promise.all([
    api(`/module/${modulId}`),
    api(`/module/${modulId}/themen/${themaId}/lehrbloecke`),
  ]);
  const thema = modul.themen.find((t) => t.id === themaId);
  brotkrumen.textContent = `${modul.titel} → ${thema?.titel ?? themaId}`;

  const lueckenDesThemas = modul.materialluecken.filter((l) => l.thema_id === themaId);
  app.innerHTML = `
    <div class="karte">
      <h2>${escapeHtml(thema?.titel ?? themaId)}
        ${bloecke.luecke ? '<span class="chip luecke">Lücke — Vertiefung freigeschaltet</span>'
                         : '<span class="chip ok">beherrscht — nur Auffrischung</span>'}</h2>
      ${lueckenDesThemas.map((l) => `<div class="materialluecke">${escapeHtml(l.beschreibung)}</div>`).join('')}
    </div>
    <div id="bloecke"></div>
    <div class="karte aktionen">
      <button class="primaer" id="ueben">Üben (${FORMAT_NAMEN[modul.zielformat.bestaetigt ?? modul.zielformat.vorschlag]})</button>
      <button id="nachgenerieren">🎓 Mehr Lehrinhalt nachgenerieren</button>
      <button id="zurueck">Zurück</button>
    </div>`;

  const bloeckeDiv = app.querySelector('#bloecke');
  bloeckeDiv.innerHTML = bloecke.lehrbloecke.map((b) => `
    <div class="karte">
      <p><span class="chip">${b.tiefe}</span>${b.nachgeneriert ? '<span class="chip ok">nachgeneriert</span>' : ''}</p>
      ${renderMarkdown(b.inhalt_markdown)}
      <div>${belegChips(b.belege)}</div>
    </div>`).join('') || '<div class="karte hinweis">Keine Lehrblöcke freigeschaltet.</div>';
  typesetze(bloeckeDiv);

  app.querySelector('#zurueck').addEventListener('click', () => {
    location.hash = `#/modul/${modulId}`;
  });
  app.querySelector('#ueben').addEventListener('click', async () => {
    const fragen = await api(`/module/${modulId}/themen/${themaId}/quiz`);
    zeigeQuiz(modulId, fragen, {
      istDiagnose: false, titel: `Üben: ${thema?.titel}`,
      zurueck: () => zeigeThema(modulId, themaId),
    });
  });
  app.querySelector('#nachgenerieren').addEventListener('click', async () => {
    const wunsch = prompt('Worauf soll der zusätzliche Lehrblock fokussieren? (optional)') ?? '';
    const knopf = app.querySelector('#nachgenerieren');
    knopf.disabled = true; knopf.textContent = 'Generiere …';
    try {
      const ergebnis = await api(`/module/${modulId}/tutor/nachgenerieren`, {
        method: 'POST', body: { thema_id: themaId, wunsch } });
      if (ergebnis.fehler) alert(ergebnis.fehler);
      else zeigeThema(modulId, themaId);
    } finally {
      knopf.disabled = false; knopf.textContent = '🎓 Mehr Lehrinhalt nachgenerieren';
    }
  });
}

// --- Router --------------------------------------------------------------------

async function route() {
  const teile = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  try {
    if (teile.length === 0) return await zeigeModulListe();
    if (teile[0] === 'modul' && teile.length === 2) return await zeigeModul(teile[1]);
    if (teile[0] === 'modul' && teile[2] === 'diagnose') return await zeigeDiagnose(teile[1]);
    if (teile[0] === 'modul' && teile[2] === 'thema') return await zeigeThema(teile[1], teile[3]);
    location.hash = '#/';
  } catch (f) {
    app.innerHTML = `<div class="karte fehler">Fehler: ${escapeHtml(f.message)}</div>`;
  }
}

window.addEventListener('hashchange', route);
route();
