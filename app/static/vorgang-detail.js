/* Ein Vorgang: Eckdaten, Budget-Aufschlüsselung und die Zeitleiste.
 *
 * Die Zeitleiste besteht aus getippten Einträgen. Jeder Typ bringt eigene
 * Felder mit; welche das sind, sagt der Server (/api/vorgaenge/stamm), die
 * Formulare dazu stehen hier in `FORMULARE`. Ein Eintrag wird immer als
 * Ganzes über EINEN Request gespeichert — bricht man ab, bleibt nichts Halbes
 * zurück.
 *
 * Regel aus früheren Fehlern: Dieses Skript läuft im scripts-Block, also NACH
 * drs.js — sonst gäbe es window.DRS beim Verdrahten noch nicht.
 */
(function () {
  'use strict';
  if (!window.DRS) return;
  const { el, feld, modal, toast, confirmDanger, postJSON, getJSON } = DRS;

  const VID = window.VORGANG_ID;
  const kopfEl = document.getElementById('vgKopf');
  const budgetEl = document.getElementById('vgBudget');
  const histEl = document.getElementById('vgHist');

  let STAMM = { typen: [], status: [], wege: [], lerngruppen: [], posten: [],
    jahre: [], kontakte: [], score_label: {}, vikunja_bereit: false };
  let DATEN = null;

  const heute = () => new Date().toISOString().slice(0, 10);
  function eur(n) {
    return (Number(n) || 0).toLocaleString('de-DE',
      { style: 'currency', currency: 'EUR' });
  }
  function fmtDate(iso) {
    if (!iso) return '';
    const p = String(iso).split('-');
    return p.length === 3 ? p[2] + '.' + p[1] + '.' + p[0] : iso;
  }
  function auswahl(paare, wert) {
    const s = el('select', {}, paare.map(([v, l]) => el('option', { value: v }, l)));
    s.value = String(wert == null ? '' : wert);
    return s;
  }
  function typLabel(typ) {
    const t = (STAMM.typen || []).find((x) => x.typ === typ);
    return t ? t.label : typ;
  }
  function typInfo(typ) {
    return (STAMM.typen || []).find((x) => x.typ === typ) || {};
  }
  function wegLabel(w) {
    const x = (STAMM.wege || []).find((y) => y.wert === w);
    return x ? x.label : w;
  }

  // ── Laden ─────────────────────────────────────────────────────────────
  async function ladeStamm(jahr) {
    try {
      const d = await getJSON('/api/vorgaenge/stamm?jahr=' + (jahr || 0));
      if (d.ok) STAMM = d;
    } catch (_) { /* Dialoge zeigen dann leere Listen */ }
  }

  async function laden() {
    let d;
    try {
      d = await getJSON('/api/vorgaenge/' + VID);
    } catch (_) {
      kopfEl.innerHTML = '<div class="flash flash-err" style="display:block">'
        + 'Vorgang nicht ladbar.</div>';
      return;
    }
    if (!d.ok) { toast(d.error || 'Fehler.'); return; }
    DATEN = d;
    // Die Posten-Auswahl hängt am Haushaltsjahr des Vorgangs — erst jetzt bekannt.
    await ladeStamm(d.vorgang.haushaltsjahr);
    renderKopf();
    renderBudget();
    renderHist();
    const abg = document.getElementById('vgAbgleich');
    if (abg) abg.hidden = !(STAMM.vikunja_bereit
      && (d.eintraege || []).some((e) => e.typ === 'aufgabe'));
  }

  // ── Kopf ──────────────────────────────────────────────────────────────
  function renderKopf() {
    const v = DATEN.vorgang;
    const meta = [];
    if (v.kategorie) meta.push(v.kategorie);
    if (v.lerngruppe) meta.push(v.lerngruppe);
    if (v.haushaltsjahr) meta.push('Haushaltsjahr ' + v.haushaltsjahr);

    kopfEl.innerHTML = '';
    kopfEl.appendChild(el('div', { class: 'vg-kopf' }, [
      el('div', { style: 'flex:1;min-width:200px' }, [
        el('h1', {}, v.titel || '(ohne Titel)'),
        meta.length ? el('p', { class: 'muted', style: 'margin:.2rem 0 0' },
          meta.join(' · ')) : null,
        v.beschreibung ? el('p', { style: 'margin:.5rem 0 0;white-space:pre-wrap' },
          v.beschreibung) : null,
      ]),
      el('div', { style: 'display:flex;gap:.5rem;align-items:center;flex-wrap:wrap' }, [
        el('span', { class: 'vg-status ' + v.status }, v.status_label),
        el('button', { type: 'button', class: 'btn-sec', onClick: eckdatenDialog },
          'Bearbeiten'),
      ]),
    ]));
  }

  function eckdatenDialog() {
    const v = DATEN.vorgang;
    const titel = el('input', { value: v.titel, maxlength: '250' });
    const kategorie = el('input', { value: v.kategorie, maxlength: '80' });
    const beschreibung = el('textarea', { rows: '3' }, v.beschreibung);
    const status = auswahl((STAMM.status || []).map((s) => [s.wert, s.label]), v.status);
    const lg = auswahl([['', '— keine —']].concat(
      (STAMM.lerngruppen || []).map((g) => [g.id, g.name])), v.lerngruppe_id || '');
    const jahr = auswahl([['0', '— keins —']].concat(
      (STAMM.jahre || []).map((j) => [j, String(j)])), v.haushaltsjahr || '0');

    modal({
      title: 'Vorgang bearbeiten',
      body: el('div', {}, [
        feld('Titel', titel),
        feld('Kategorie', kategorie),
        feld('Status', status),
        feld('Klasse / Lerngruppe', lg),
        feld('Haushaltsjahr', jahr,
          'Bestimmt, welche Haushaltsposten bei den Kosten zur Wahl stehen.'),
        feld('Beschreibung', beschreibung),
      ]),
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: (c) => c() },
        {
          label: 'Vorgang löschen', kind: 'danger', onClick: (c) => {
            c();
            confirmDanger({
              title: 'Vorgang löschen?',
              text: 'Der Vorgang „' + (v.titel || '') + '" wird mit seiner ganzen '
                + 'Zeitleiste entfernt.',
              facts: [{ label: 'Einträge in der Zeitleiste',
                wert: (DATEN.eintraege || []).length }],
              warnung: 'Das lässt sich nicht rückgängig machen. Verknüpfte Dokumente '
                + 'bleiben in Paperless, die Zuordnung geht aber verloren. Wer den '
                + 'Vorgang nur abschließen will, setzt den Status auf „Beendet".',
              danger: 'Endgültig löschen',
              safe: 'Stattdessen beenden',
              onSafe: async (close) => {
                try {
                  await postJSON('/api/vorgaenge', { id: VID, titel: v.titel,
                    status: 'beendet', kategorie: v.kategorie,
                    beschreibung: v.beschreibung, lerngruppe_id: v.lerngruppe_id,
                    haushaltsjahr: v.haushaltsjahr });
                  close(); laden();
                } catch (e) { toast(e.message); }
              },
              onDanger: async (close) => {
                try {
                  await postJSON('/api/vorgaenge/' + VID + '/delete', {});
                  close(); location.href = '/vorgaenge';
                } catch (e) { toast(e.message); }
              },
            });
          },
        },
        {
          label: 'Speichern', kind: 'primary', onClick: async (close) => {
            try {
              await postJSON('/api/vorgaenge', {
                id: VID, titel: titel.value, kategorie: kategorie.value,
                beschreibung: beschreibung.value, status: status.value,
                lerngruppe_id: lg.value || null, haushaltsjahr: jahr.value,
              });
              close(); toast('Gespeichert.'); laden();
            } catch (e) { toast(e.message); }
          },
        },
      ],
    });
  }

  // ── Budget ────────────────────────────────────────────────────────────
  function renderBudget() {
    budgetEl.innerHTML = '';
    const zeilen = DATEN.budget || [];
    if (!zeilen.length) return;

    budgetEl.appendChild(el('div', { class: 'card' }, [
      el('h2', { style: 'margin:0 0 .3rem;font-size:17px' }, 'Budget'),
      el('p', { class: 'muted' },
        'Was dieser Vorgang auf welchen Posten gebucht hat — und was auf dem Posten '
        + 'insgesamt noch übrig ist (alle Vorgänge zusammen).'),
      el('div', { style: 'overflow-x:auto' }, el('table', { class: 'vg-btable' }, [
        el('thead', {}, el('tr', {}, [
          el('th', {}, 'Haushaltsposten'),
          el('th', { class: 'vg-num' }, 'Dieser Vorgang'),
          el('th', { class: 'vg-num' }, 'Posten gesamt'),
          el('th', { class: 'vg-num' }, 'Budget'),
          el('th', { class: 'vg-num' }, 'Restmittel'),
        ])),
        el('tbody', {}, zeilen.map((b) => el('tr', {
          class: b.rest < 0 ? 'vg-row-neg' : '',
        }, [
          el('td', {}, (b.bezeichnung || '') + (b.jahr ? ' · ' + b.jahr : '')),
          el('td', { class: 'vg-num' }, eur(b.dieser_vorgang)),
          el('td', { class: 'vg-num' }, eur(b.verbrauch_gesamt)),
          el('td', { class: 'vg-num' }, eur(b.budget)),
          el('td', { class: 'vg-num', style: 'font-weight:600' }, eur(b.rest)),
        ]))),
      ])),
    ]));
  }

  // ── Zeitleiste ────────────────────────────────────────────────────────
  function renderHist() {
    histEl.innerHTML = '';
    const liste = DATEN.eintraege || [];
    if (!liste.length) {
      histEl.appendChild(el('p', { class: 'muted' },
        'Noch nichts passiert. Oben „+ Eintrag".'));
      return;
    }
    liste.forEach((e) => histEl.appendChild(eintragEl(e)));
  }

  function eintragEl(e) {
    const p = e.payload || {};
    const kopf = el('div', { class: 'vg-e-kopf' }, [
      el('span', { class: 'vg-typ' }, e.typ_label || typLabel(e.typ)),
      el('span', { class: 'vg-e-datum' }, fmtDate(e.datum)),
      e.betrag ? el('span', { class: 'vg-e-betrag' }, eur(e.betrag)) : null,
    ]);

    const box = el('div', {
      class: 'vg-eintrag' + (e.erledigt ? ' erledigt' : ''),
      onClick: () => eintragOverlay(e),
    }, [kopf]);

    const titel = (t) => t ? box.appendChild(el('div', { class: 'vg-e-titel' }, t)) : null;
    const text = (t) => t ? box.appendChild(el('div', { class: 'vg-e-body' }, t)) : null;

    if (e.typ === 'notiz') {
      text(p.text);
    } else if (e.typ === 'aufgabe') {
      titel((e.erledigt ? '✓ ' : '') + (p.titel || ''));
      text(p.faellig ? 'fällig ' + fmtDate(p.faellig) : '');
    } else if (e.typ === 'frist') {
      titel((e.erledigt ? '✓ ' : '') + (p.titel || ''));
      text(p.faellig ? 'bis ' + fmtDate(p.faellig) : '');
    } else if (e.typ === 'weiterleitung') {
      titel(p.info || 'Information weitergeleitet');
      const chips = (p.empfaenger || []).map((x) => el('span', {
        class: 'vg-empf-chip' + (x.erledigt ? ' ok' : ''),
      }, (x.erledigt ? '✓ ' : '') + x.name + ' · ' + wegLabel(x.weg)
        + (x.datum ? ' · ' + fmtDate(x.datum) : '')));
      if (chips.length) box.appendChild(el('div', { class: 'vg-empf' }, chips));
      else text('(noch niemand eingetragen)');
    } else if (e.typ === 'email') {
      titel((p.richtung === 'aus' ? '↗ ' : '↙ ') + (p.betreff || '(kein Betreff)'));
      text(p.richtung === 'aus' ? 'an ' + (p.an || '—') : 'von ' + (p.von || '—'));
    } else if (e.typ === 'telefonat') {
      titel(p.partner || 'Gespräch');
      text(p.text);
    } else if (e.typ === 'dokument') {
      titel(p.titel || 'Dokumente');
    } else if (e.typ === 'angebot') {
      titel(p.anbieter || '(ohne Anbieter)');
      text(p.beschreibung);
    } else if (e.typ === 'genehmigung') {
      const zeichen = { genehmigt: '✓ ', abgelehnt: '✗ ', beantragt: '… ' };
      titel((zeichen[p.ergebnis] || '') + (p.stelle || 'Genehmigung'));
      text(p.begruendung);
    } else if (e.typ === 'bestellung') {
      titel(p.haendler || 'Bestellung');
      const teile = [];
      if (p.bestellt_am) teile.push('bestellt ' + fmtDate(p.bestellt_am));
      teile.push(p.geliefert_am ? 'geliefert ' + fmtDate(p.geliefert_am)
        : 'noch nicht geliefert');
      text(teile.join(' · ') + (p.beschreibung ? '\n' + p.beschreibung : ''));
    } else if (e.typ === 'kosten') {
      titel(p.beschreibung || 'Ausgabe');
      const posten = (STAMM.posten || []).find((x) => x.id === e.hh_posten_id);
      text([p.haendler, posten ? posten.label : (e.hh_posten_id
        ? 'Posten aus einem anderen Jahr' : '⚠ keinem Posten zugeordnet')]
        .filter(Boolean).join(' · '));
    } else if (e.typ === 'entscheidung') {
      titel(p.titel || 'Entscheidungsmatrix');
      const m = e.matrix || {};
      const namen = {};
      (p.teilnehmer || []).forEach((t) => { namen[t.id] = t.name; });
      if (m.gewaehlt) text('✓ Gewählt: ' + (namen[m.gewaehlt] || m.gewaehlt));
      else if (m.empfehlung) text('Empfehlung: ' + (namen[m.empfehlung] || '—')
        + ' (' + (m.punkte || {})[m.empfehlung] + ' Punkte)');
      else text('(noch keine Anbieter bewertet)');
    }

    const docs = p.docs || [];
    if (docs.length) {
      box.appendChild(el('div', { class: 'vg-empf' }, docs.map((d) => el('a', {
        class: 'vg-empf-chip', href: '/dokumente/' + d.id + '/datei/preview',
        target: '_blank', rel: 'noopener',
        onClick: (ev) => ev.stopPropagation(),
      }, '📄 ' + (d.title || ('Dokument ' + d.id))))));
    }
    return box;
  }

  // ── Dokument-Verknüpfung (klein gehalten, gemeinsam für alle Typen) ────
  function docsFeld(ctx) {
    const liste = el('div', { class: 'vg-empf' });
    function render() {
      liste.innerHTML = '';
      if (!ctx.docs.length) {
        liste.appendChild(el('span', { class: 'muted', style: 'font-size:12px' },
          'keine'));
      }
      ctx.docs.forEach((d, i) => liste.appendChild(el('span', { class: 'vg-empf-chip' }, [
        '📄 ' + (d.title || ('Dokument ' + d.id)) + ' ',
        el('button', {
          type: 'button', class: 'drs-x', style: 'font-size:14px;line-height:1',
          onClick: () => { ctx.docs.splice(i, 1); render(); },
        }, '×'),
      ])));
    }
    render();

    const btn = el('button', {
      type: 'button', class: 'btn-sec', style: 'margin-top:.3rem',
      onClick: () => dokWaehlen((doc) => {
        if (ctx.docs.some((d) => d.id === doc.id)) return;
        ctx.docs.push({ id: doc.id, title: doc.title });
        render();
      }),
    }, '＋ Dokument verknüpfen');

    return el('div', { class: 'drs-field' }, [
      el('span', { class: 'drs-field-label' }, 'Dokumente (Paperless)'),
      liste, btn,
    ]);
  }

  function dokWaehlen(onPick) {
    const suche = el('input', { type: 'search', placeholder: 'Titel oder Inhalt …' });
    const treffer = el('div', { style: 'max-height:300px;overflow:auto;margin-top:.5rem' });
    let seq = 0;

    async function suchen() {
      const my = ++seq;
      treffer.innerHTML = '<p class="muted">sucht …</p>';
      let d;
      try {
        d = await getJSON('/api/dokumente/liste?query='
          + encodeURIComponent(suche.value.trim()));
      } catch (_) {
        treffer.innerHTML = '<p class="muted">Paperless ist nicht erreichbar.</p>';
        return;
      }
      if (my !== seq) return;
      treffer.innerHTML = '';
      if (!d.ok) {
        treffer.appendChild(el('p', { class: 'muted' },
          d.error || 'Dokumente nicht verfügbar.'));
        return;
      }
      if (!(d.results || []).length) {
        treffer.appendChild(el('p', { class: 'muted' }, 'Nichts gefunden.'));
        return;
      }
      d.results.forEach((doc) => treffer.appendChild(el('button', {
        type: 'button', class: 'doc-listrow',
        style: 'width:100%;border:0;border-bottom:1px solid var(--border);'
          + 'background:transparent;text-align:left;padding:.4rem .2rem;cursor:pointer',
        onClick: () => { onPick(doc); dlg.close(); },
      }, '📄 ' + (doc.title || 'Dokument ' + doc.id)
        + (doc.created ? ' · ' + fmtDate(doc.created) : ''))));
    }

    let tippTimer = null;
    suche.addEventListener('input', () => {
      clearTimeout(tippTimer);
      tippTimer = setTimeout(suchen, 300);
    });

    const dlg = modal({
      title: 'Dokument verknüpfen',
      body: el('div', {}, [feld('Suche', suche), treffer]),
    });
    suchen();
  }

  // ── Eintrags-Formulare je Typ ─────────────────────────────────────────
  // Jede Funktion baut ihre Felder und liefert `sammeln()`, das den Payload
  // für den Server zurückgibt. So bleibt jeder Typ an einer Stelle.
  const FORMULARE = {
    notiz(p, host) {
      const t = el('textarea', { rows: '6' }, p.text || '');
      host.appendChild(feld('Notiz', t));
      return () => ({ text: t.value });
    },

    aufgabe(p, host) {
      const titel = el('input', { value: p.titel || '', maxlength: '250' });
      const faellig = el('input', { type: 'date', value: p.faellig || '' });
      const prio = auswahl([[0, '— keine —'], [1, 'Niedrig'], [2, 'Mittel'],
        [3, 'Hoch'], [4, 'Dringend'], [5, 'DRINGEND!']], p.prioritaet || 0);
      host.appendChild(feld('Aufgabe', titel));
      host.appendChild(feld('Fällig am', faellig));
      host.appendChild(feld('Priorität', prio));
      host.appendChild(el('p', { class: 'muted' }, p.vikunja_task_id
        ? 'Liegt als Aufgabe #' + p.vikunja_task_id + ' in Vikunja. Titel und '
          + 'Fälligkeit änderst du dort oder unter „Aufgaben".'
        : (STAMM.vikunja_bereit
          ? 'Wird beim Speichern in Vikunja angelegt — mit dem Label „Vorgang: …".'
          : '⚠ Vikunja ist nicht eingerichtet; der Eintrag bleibt dann nur hier stehen.')));
      return () => ({
        titel: titel.value, faellig: faellig.value,
        prioritaet: prio.value, vikunja_task_id: p.vikunja_task_id || null,
      });
    },

    frist(p, host) {
      const titel = el('input', { value: p.titel || '', maxlength: '250' });
      const faellig = el('input', { type: 'date', value: p.faellig || '' });
      host.appendChild(feld('Was muss passieren?', titel));
      host.appendChild(feld('Bis wann', faellig));
      return () => ({ titel: titel.value, faellig: faellig.value });
    },

    weiterleitung(p, host) {
      const info = el('input', { value: p.info || '', maxlength: '250' });
      const ctx = { empfaenger: (p.empfaenger || []).map((x) => Object.assign({}, x)) };
      const liste = el('div');

      // Bereits benutzte Namen als Vorschlagsliste — Freitext mit Gedächtnis.
      const datalist = el('datalist', { id: 'vgKontakte' },
        (STAMM.kontakte || []).map((n) => el('option', { value: n })));

      function render() {
        liste.innerHTML = '';
        ctx.empfaenger.forEach((x, i) => {
          const name = el('input', {
            value: x.name, list: 'vgKontakte', placeholder: 'Name oder Stelle',
            onInput: (ev) => { x.name = ev.target.value; },
          });
          const weg = auswahl((STAMM.wege || []).map((w) => [w.wert, w.label]), x.weg);
          weg.addEventListener('change', () => { x.weg = weg.value; });
          const datum = el('input', {
            type: 'date', value: x.datum || '',
            onInput: (ev) => { x.datum = ev.target.value; },
          });
          const ok = el('input', { type: 'checkbox', style: 'width:auto' });
          ok.checked = !!x.erledigt;
          ok.addEventListener('change', () => { x.erledigt = ok.checked; });

          liste.appendChild(el('div', {
            style: 'display:flex;gap:.4rem;align-items:center;margin-bottom:.3rem;flex-wrap:wrap',
          }, [
            el('div', { style: 'flex:2;min-width:140px' }, name),
            el('div', { style: 'flex:1;min-width:110px' }, weg),
            el('div', { style: 'flex:1;min-width:130px' }, datum),
            el('label', { style: 'display:flex;gap:.25rem;align-items:center;font-size:12px' },
              [ok, 'informiert']),
            el('button', {
              type: 'button', class: 'drs-x',
              onClick: () => { ctx.empfaenger.splice(i, 1); render(); },
            }, '×'),
          ]));
        });
        if (!ctx.empfaenger.length) {
          liste.appendChild(el('p', { class: 'muted' }, 'Noch niemand eingetragen.'));
        }
      }
      render();

      host.appendChild(feld('Worum geht es?', info));
      host.appendChild(datalist);
      host.appendChild(el('div', { class: 'drs-field' }, [
        el('span', { class: 'drs-field-label' }, 'An wen'),
        liste,
        el('button', {
          type: 'button', class: 'btn-sec',
          onClick: () => {
            ctx.empfaenger.push({ name: '', weg: 'persoenlich', datum: heute(), erledigt: false });
            render();
          },
        }, '＋ Empfänger'),
      ]));
      return () => ({ info: info.value, empfaenger: ctx.empfaenger });
    },

    email(p, host) {
      const richtung = auswahl([['ein', 'empfangen'], ['aus', 'gesendet']],
        p.richtung || 'ein');
      const von = el('input', { value: p.von || '', maxlength: '250' });
      const an = el('input', { value: p.an || '', maxlength: '250' });
      const betreff = el('input', { value: p.betreff || '', maxlength: '250' });
      const text = el('textarea', { rows: '4' }, p.text || '');
      const ctx = { docs: (p.docs || []).slice() };

      host.appendChild(feld('Richtung', richtung));
      host.appendChild(feld('Von', von));
      host.appendChild(feld('An', an));
      host.appendChild(feld('Betreff', betreff));
      host.appendChild(feld('Inhalt', text, 'Kurzfassung genügt — die Mail selbst '
        + 'kannst du als Datei in Paperless ablegen und hier verknüpfen.'));
      host.appendChild(docsFeld(ctx));
      return () => ({
        richtung: richtung.value, von: von.value, an: an.value,
        betreff: betreff.value, text: text.value, docs: ctx.docs,
      });
    },

    telefonat(p, host) {
      const partner = el('input', { value: p.partner || '', maxlength: '250' });
      const text = el('textarea', { rows: '4' }, p.text || '');
      host.appendChild(feld('Mit wem', partner));
      host.appendChild(feld('Ergebnis', text));
      return () => ({ partner: partner.value, text: text.value });
    },

    dokument(p, host) {
      const titel = el('input', { value: p.titel || '', maxlength: '250' });
      const ctx = { docs: (p.docs || []).slice() };
      host.appendChild(feld('Bezeichnung', titel));
      host.appendChild(docsFeld(ctx));
      return () => ({ titel: titel.value, docs: ctx.docs });
    },

    angebot(p, host) {
      const anbieter = el('input', { value: p.anbieter || '', maxlength: '250' });
      const beschreibung = el('textarea', { rows: '3' }, p.beschreibung || '');
      const ctx = { docs: (p.docs || []).slice() };
      host.appendChild(feld('Anbieter', anbieter));
      host.appendChild(feld('Was wird angeboten', beschreibung));
      host.appendChild(docsFeld(ctx));
      host.appendChild(el('p', { class: 'muted' },
        'Ein Angebot mindert die Restmittel noch nicht — das tut erst ein Kosten-Eintrag.'));
      return () => ({ anbieter: anbieter.value, beschreibung: beschreibung.value,
        docs: ctx.docs });
    },

    genehmigung(p, host) {
      const stelle = el('input', { value: p.stelle || '', maxlength: '250',
        placeholder: 'z. B. Schulleitung' });
      const ergebnis = auswahl([['beantragt', 'beantragt'], ['genehmigt', 'genehmigt'],
        ['abgelehnt', 'abgelehnt']], p.ergebnis || 'beantragt');
      const begruendung = el('textarea', { rows: '3' }, p.begruendung || '');
      const ctx = { docs: (p.docs || []).slice() };
      host.appendChild(feld('Bei wem', stelle));
      host.appendChild(feld('Ergebnis', ergebnis));
      host.appendChild(feld('Begründung / Auflagen', begruendung));
      host.appendChild(docsFeld(ctx));
      return () => ({ stelle: stelle.value, ergebnis: ergebnis.value,
        begruendung: begruendung.value, docs: ctx.docs });
    },

    bestellung(p, host) {
      const haendler = el('input', { value: p.haendler || '', maxlength: '250' });
      const bestellt = el('input', { type: 'date', value: p.bestellt_am || '' });
      const geliefert = el('input', { type: 'date', value: p.geliefert_am || '' });
      const beschreibung = el('textarea', { rows: '2' }, p.beschreibung || '');
      const ctx = { docs: (p.docs || []).slice() };
      host.appendChild(feld('Händler', haendler));
      host.appendChild(feld('Bestellt am', bestellt));
      host.appendChild(feld('Geliefert am', geliefert,
        'Leer lassen, solange die Lieferung aussteht.'));
      host.appendChild(feld('Was', beschreibung));
      host.appendChild(docsFeld(ctx));
      return () => ({ haendler: haendler.value, bestellt_am: bestellt.value,
        geliefert_am: geliefert.value, beschreibung: beschreibung.value, docs: ctx.docs });
    },

    kosten(p, host) {
      const beschreibung = el('input', { value: p.beschreibung || '', maxlength: '250' });
      const haendler = el('input', { value: p.haendler || '', maxlength: '250' });
      const ctx = { docs: (p.docs || []).slice() };
      host.appendChild(feld('Wofür', beschreibung));
      host.appendChild(feld('Händler', haendler));
      host.appendChild(docsFeld(ctx));
      return () => ({ beschreibung: beschreibung.value, haendler: haendler.value,
        docs: ctx.docs });
    },

    entscheidung(p, host) {
      // Kriterien mit Gewicht, Anbieter mit Punkten 0–5 → gewichtete Summe.
      const titel = el('input', { value: p.titel || '', maxlength: '250',
        placeholder: 'z. B. Beschaffung Messgeräte' });
      const ctx = {
        kriterien: (p.kriterien || []).map((k) => Object.assign({}, k)),
        teilnehmer: (p.teilnehmer || []).map((t) => Object.assign({}, t,
          { punkte: Object.assign({}, t.punkte) })),
        gewaehlt: p.gewaehlt || '',
      };
      const tabelle = el('div', { style: 'overflow-x:auto' });

      const neueId = (pre) => pre + Math.random().toString(36).slice(2, 8);
      function punktzahl(t) {
        return ctx.kriterien.reduce(
          (s, k) => s + (Number(t.punkte[k.id]) || 0) * (Number(k.gewicht) || 1), 0);
      }

      function render() {
        tabelle.innerHTML = '';
        if (!ctx.kriterien.length || !ctx.teilnehmer.length) {
          tabelle.appendChild(el('p', { class: 'muted' },
            'Erst Kriterien und Anbieter anlegen, dann bewerten.'));
        } else {
          const punkte = ctx.teilnehmer.map(punktzahl);
          const best = Math.max.apply(null, punkte);

          const kopf = el('tr', {}, [el('th', {}, 'Kriterium (Gewicht)')]
            .concat(ctx.teilnehmer.map((t, i) => el('th', {
              class: punkte[i] === best ? 'gewinner' : '',
            }, t.name || '(ohne Namen)'))));

          const zeilen = ctx.kriterien.map((k) => el('tr', {}, [
            el('td', {}, (k.name || '') + ' (×' + k.gewicht + ')'),
          ].concat(ctx.teilnehmer.map((t) => {
            const sel = auswahl(Object.entries(STAMM.score_label || {})
              .map(([w, l]) => [w, w + ' – ' + l]), t.punkte[k.id] || 0);
            sel.addEventListener('change', () => {
              t.punkte[k.id] = Number(sel.value);
              render();
            });
            return el('td', {}, sel);
          }))));

          const summe = el('tr', {}, [el('td', {}, el('strong', {}, 'Punkte'))]
            .concat(ctx.teilnehmer.map((t, i) => el('td', {
              class: 'vg-num' + (punkte[i] === best ? ' gewinner' : ''),
            }, el('strong', {}, String(punkte[i]))))));

          const wahl = el('tr', {}, [el('td', {}, 'Gewählt')]
            .concat(ctx.teilnehmer.map((t) => {
              const r = el('input', { type: 'radio', name: 'vgWahl', style: 'width:auto' });
              r.checked = ctx.gewaehlt === t.id;
              r.addEventListener('change', () => { ctx.gewaehlt = t.id; });
              return el('td', { style: 'text-align:center' }, r);
            })));

          tabelle.appendChild(el('table', { class: 'vg-matrix' }, [
            el('thead', {}, kopf),
            el('tbody', {}, zeilen.concat([summe, wahl])),
          ]));
        }
      }
      render();

      const kritListe = el('div');
      function renderKrit() {
        kritListe.innerHTML = '';
        ctx.kriterien.forEach((k, i) => {
          const name = el('input', { value: k.name, placeholder: 'Kriterium',
            onInput: (ev) => { k.name = ev.target.value; render(); } });
          const gew = el('input', { type: 'number', min: '1', max: '10',
            value: String(k.gewicht), style: 'width:70px',
            onInput: (ev) => { k.gewicht = Number(ev.target.value) || 1; render(); } });
          kritListe.appendChild(el('div', {
            style: 'display:flex;gap:.4rem;align-items:center;margin-bottom:.3rem',
          }, [
            el('div', { style: 'flex:1' }, name), gew,
            el('button', { type: 'button', class: 'drs-x',
              onClick: () => { ctx.kriterien.splice(i, 1); renderKrit(); render(); } }, '×'),
          ]));
        });
      }
      renderKrit();

      const teilListe = el('div');
      function renderTeil() {
        teilListe.innerHTML = '';
        ctx.teilnehmer.forEach((t, i) => {
          const name = el('input', { value: t.name, placeholder: 'Anbieter',
            onInput: (ev) => { t.name = ev.target.value; render(); } });
          teilListe.appendChild(el('div', {
            style: 'display:flex;gap:.4rem;align-items:center;margin-bottom:.3rem',
          }, [
            el('div', { style: 'flex:1' }, name),
            el('button', { type: 'button', class: 'drs-x',
              onClick: () => { ctx.teilnehmer.splice(i, 1); renderTeil(); render(); } }, '×'),
          ]));
        });
      }
      renderTeil();

      host.appendChild(feld('Worum geht es', titel));
      host.appendChild(el('div', { class: 'drs-field' }, [
        el('span', { class: 'drs-field-label' }, 'Kriterien und ihr Gewicht'),
        kritListe,
        el('button', { type: 'button', class: 'btn-sec', onClick: () => {
          ctx.kriterien.push({ id: neueId('k'), name: '', gewicht: 1 });
          renderKrit(); render();
        } }, '＋ Kriterium'),
      ]));
      host.appendChild(el('div', { class: 'drs-field' }, [
        el('span', { class: 'drs-field-label' }, 'Anbieter'),
        teilListe,
        el('button', { type: 'button', class: 'btn-sec', onClick: () => {
          // Vorhandene Angebote als Anbieter übernehmen, statt neu zu tippen.
          const offen = (DATEN.angebote || []).filter(
            (a) => !ctx.teilnehmer.some((t) => t.name === a.name));
          if (offen.length) {
            offen.forEach((a) => ctx.teilnehmer.push({
              id: neueId('t'), name: a.name, preis: a.preis, punkte: {},
            }));
          } else {
            ctx.teilnehmer.push({ id: neueId('t'), name: '', punkte: {} });
          }
          renderTeil(); render();
        } }, '＋ Anbieter'),
        el('span', { class: 'muted' },
          'Übernimmt die Angebote dieses Vorgangs, sofern noch nicht in der Tabelle.'),
      ]));
      host.appendChild(el('div', { class: 'drs-field' }, [
        el('span', { class: 'drs-field-label' }, 'Bewertung'), tabelle,
      ]));

      return () => ({ titel: titel.value, kriterien: ctx.kriterien,
        teilnehmer: ctx.teilnehmer, gewaehlt: ctx.gewaehlt });
    },
  };

  // ── Eintrag anlegen / bearbeiten ──────────────────────────────────────
  function typWaehlen() {
    const body = el('div', { style: 'display:grid;gap:.4rem' });
    const dlg = modal({ title: 'Was ist passiert?', body: body });
    (STAMM.typen || []).forEach((t) => body.appendChild(el('button', {
      type: 'button', class: 'btn-sec',
      style: 'text-align:left;padding:.5rem .7rem',
      onClick: () => { dlg.close(); eintragOverlay(null, t.typ); },
    }, [
      el('div', { style: 'font-weight:600' }, t.label),
      el('div', { class: 'muted', style: 'font-size:11px' }, t.hinweis || ''),
    ])));
  }

  function eintragOverlay(eintrag, typVorgabe) {
    const typ = eintrag ? eintrag.typ : typVorgabe;
    const info = typInfo(typ);
    const p = eintrag ? (eintrag.payload || {}) : {};

    const datum = el('input', { type: 'date', value: eintrag ? eintrag.datum : heute() });
    const host = el('div');
    const bauer = FORMULARE[typ];
    if (!bauer) { toast('Unbekannter Eintragstyp.'); return; }
    const sammeln = bauer(p, host);

    // Betrag und Haushaltsposten sind echte Spalten — deshalb hier und nicht
    // im typ-eigenen Formular.
    let betrag = null, posten = null, erledigt = null;
    const extra = el('div');
    if (info.betrag) {
      betrag = el('input', { type: 'number', step: '0.01', min: '0',
        value: eintrag && eintrag.betrag ? String(eintrag.betrag) : '' });
      extra.appendChild(feld('Betrag (€)', betrag));
    }
    if (info.posten) {
      const wahl = [['', '— kein Posten —']].concat(
        (STAMM.posten || []).map((x) => [x.id, x.label]));
      posten = auswahl(wahl, eintrag && eintrag.hh_posten_id ? eintrag.hh_posten_id : '');
      extra.appendChild(feld('Haushaltsposten', posten,
        (STAMM.posten || []).length
          ? 'Bucht auf das Haushaltsjahr des Vorgangs.'
          : '⚠ Für dieses Haushaltsjahr gibt es noch keine Posten — erst unter „Haushalt" anlegen.'));
    }
    if (typ === 'aufgabe' || typ === 'frist') {
      erledigt = el('input', { type: 'checkbox', style: 'width:auto' });
      erledigt.checked = !!(eintrag && eintrag.erledigt);
      extra.appendChild(el('label', {
        class: 'drs-field', style: 'flex-direction:row;gap:.4rem;align-items:center',
      }, [erledigt, el('span', {}, 'erledigt')]));
    }

    const aktionen = [{ label: 'Abbrechen', kind: 'sec', onClick: (c) => c() }];
    if (eintrag) {
      aktionen.push({
        label: 'Löschen', kind: 'danger', onClick: async (close) => {
          try {
            await postJSON('/api/vorgaenge/' + VID + '/eintrag/' + eintrag.id + '/delete', {});
            close(); toast('Eintrag gelöscht.'); laden();
          } catch (e) { toast(e.message); }
        },
      });
    }
    aktionen.push({
      label: 'Speichern', kind: 'primary', onClick: async (close) => {
        try {
          const r = await postJSON('/api/vorgaenge/' + VID + '/eintrag', {
            id: eintrag ? eintrag.id : null,
            typ: typ,
            datum: datum.value || heute(),
            erledigt: erledigt ? erledigt.checked : false,
            betrag: betrag ? betrag.value : null,
            hh_posten_id: posten && posten.value ? posten.value : null,
            payload: sammeln(),
          });
          close();
          toast(r.hinweis || 'Gespeichert.', r.hinweis ? 6000 : 2400);
          laden();
        } catch (e) { toast(e.message); }
      },
    });

    modal({
      title: (eintrag ? 'Eintrag: ' : 'Neu: ') + typLabel(typ),
      body: el('div', {}, [feld('Datum', datum), host, extra]),
      actions: aktionen,
    });
  }

  // ── Verdrahtung ───────────────────────────────────────────────────────
  const neuBtn = document.getElementById('vgNeuerEintrag');
  if (neuBtn) neuBtn.addEventListener('click', typWaehlen);

  const abgBtn = document.getElementById('vgAbgleich');
  if (abgBtn) abgBtn.addEventListener('click', async () => {
    abgBtn.disabled = true;
    try {
      const d = await postJSON('/api/vorgaenge/' + VID + '/aufgaben/abgleichen', {});
      toast(d.fehler ? 'Vikunja meldet: ' + d.fehler
        : (d.geaendert ? d.geaendert + ' Aufgabe(n) aktualisiert.'
          : 'Alles schon aktuell.'), d.fehler ? 6000 : 2400);
      laden();
    } catch (e) { toast(e.message); } finally { abgBtn.disabled = false; }
  });

  laden();
})();
