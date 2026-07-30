/* Vorgänge & Projekte — Übersicht als Kacheln.
 *
 * Die Karten führen ins Detail; angelegt und in den Eckdaten geändert wird
 * über einen Dialog. Beendete Vorgänge stehen in einem eigenen, eingeklappten
 * Bereich, damit die Übersicht die laufende Arbeit zeigt.
 */
(function () {
  'use strict';
  if (!window.DRS) return;
  const { el, feld, modal, toast, postJSON, getJSON } = DRS;

  const aktivEl = document.getElementById('vgAktiv');
  const beendetEl = document.getElementById('vgBeendet');
  const sucheEl = document.getElementById('vgSuche');
  const statusEl = document.getElementById('vgStatus');
  const jahrEl = document.getElementById('vgJahr');

  let STAMM = { lerngruppen: [], status: [], jahre: [] };
  let seq = 0;

  function eur(n) {
    return (Number(n) || 0).toLocaleString('de-DE',
      { style: 'currency', currency: 'EUR' });
  }

  async function ladeStamm() {
    try {
      const d = await getJSON('/api/vorgaenge/stamm');
      if (!d.ok) return;
      STAMM = d;
      if (jahrEl) {
        (d.jahre || []).forEach((j) => jahrEl.appendChild(
          el('option', { value: j }, String(j))));
      }
    } catch (_) { /* Filter sind Komfort */ }
  }

  async function laden() {
    const my = ++seq;
    const p = new URLSearchParams();
    if (sucheEl && sucheEl.value.trim()) p.set('suche', sucheEl.value.trim());
    if (statusEl && statusEl.value) p.set('status', statusEl.value);
    if (jahrEl && jahrEl.value !== '0') p.set('jahr', jahrEl.value);

    let d;
    try {
      d = await getJSON('/api/vorgaenge?' + p.toString());
    } catch (_) {
      aktivEl.innerHTML = '<div class="card"><div class="flash flash-err" '
        + 'style="display:block">Konnte die Vorgänge nicht laden.</div></div>';
      return;
    }
    if (my !== seq) return;          // eine neuere Anfrage hat übernommen
    if (!d.ok) { toast(d.error || 'Fehler beim Laden.'); return; }

    aktivEl.innerHTML = '';
    if (!(d.aktiv || []).length) {
      aktivEl.appendChild(el('div', { class: 'card' },
        el('p', { class: 'muted' }, 'Kein laufender Vorgang. Oben „+ Neuer Vorgang".')));
    } else {
      aktivEl.appendChild(el('div', { class: 'vg-grid' }, d.aktiv.map(karte)));
    }

    beendetEl.innerHTML = '';
    if ((d.beendet || []).length) {
      beendetEl.appendChild(el('details', { class: 'card' }, [
        el('summary', { style: 'cursor:pointer;font-weight:600' },
          'Abgeschlossen (' + d.beendet.length + ')'),
        el('div', { class: 'vg-grid' }, d.beendet.map(karte)),
      ]));
    }
  }

  function karte(v) {
    const meta = [];
    if (v.kategorie) meta.push(v.kategorie);
    if (v.lerngruppe) meta.push(v.lerngruppe);
    if (v.haushaltsjahr) meta.push('HH ' + v.haushaltsjahr);

    return el('button', {
      type: 'button', class: 'vg-card',
      onClick: () => { location.href = '/vorgaenge/' + v.id; },
    }, [
      el('div', { class: 'vg-card-titel' }, v.titel || '(ohne Titel)'),
      meta.length ? el('div', { class: 'vg-card-meta' }, meta.join(' · ')) : null,
      v.beschreibung
        ? el('div', { class: 'vg-card-meta' }, v.beschreibung.slice(0, 110)
          + (v.beschreibung.length > 110 ? ' …' : ''))
        : null,
      el('div', { class: 'vg-card-fuss' }, [
        el('span', { class: 'vg-status ' + v.status }, v.status_label),
        v.kosten ? el('span', { class: 'vg-kosten' }, eur(v.kosten)) : null,
      ]),
    ]);
  }

  // ── Anlegen ───────────────────────────────────────────────────────────
  function neuDialog() {
    const titel = el('input', { maxlength: '250' });
    const kategorie = el('input', { maxlength: '80', placeholder: 'z. B. Anschaffung, Klassenfahrt' });
    const beschreibung = el('textarea', { rows: '3' });
    const lg = el('select', {}, [el('option', { value: '' }, '— keine —')]
      .concat((STAMM.lerngruppen || []).map((g) => el('option', { value: g.id }, g.name))));
    const jahr = el('select', {}, [el('option', { value: '0' }, '— keins —')]
      .concat((STAMM.jahre || []).map((j) => el('option', { value: j }, String(j)))));
    jahr.value = String(new Date().getFullYear());

    modal({
      title: 'Neuer Vorgang',
      body: el('div', {}, [
        feld('Titel', titel),
        feld('Kategorie', kategorie),
        feld('Klasse / Lerngruppe', lg, 'Optional — für Vorgänge der Klassenführung.'),
        feld('Haushaltsjahr', jahr, 'Bestimmt, welche Posten bei den Kosten zur Wahl stehen.'),
        feld('Beschreibung', beschreibung),
      ]),
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: (c) => c() },
        {
          label: 'Anlegen', kind: 'primary', onClick: async (close) => {
            try {
              const r = await postJSON('/api/vorgaenge', {
                titel: titel.value, kategorie: kategorie.value,
                beschreibung: beschreibung.value,
                lerngruppe_id: lg.value || null,
                haushaltsjahr: jahr.value,
                status: 'geplant',
              });
              close();
              location.href = '/vorgaenge/' + r.id;
            } catch (e) { toast(e.message); }
          },
        },
      ],
    });
  }

  // ── Verdrahtung ───────────────────────────────────────────────────────
  let tippTimer = null;
  if (sucheEl) sucheEl.addEventListener('input', () => {
    clearTimeout(tippTimer);
    tippTimer = setTimeout(laden, 300);
  });
  if (statusEl) statusEl.addEventListener('change', laden);
  if (jahrEl) jahrEl.addEventListener('change', laden);
  const neuBtn = document.getElementById('vgNeu');
  if (neuBtn) neuBtn.addEventListener('click', neuDialog);

  ladeStamm();
  laden();
})();
