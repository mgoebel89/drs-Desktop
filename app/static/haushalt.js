/* Haushalt: zwei Töpfe je Haushaltsjahr, dazu die Ideenliste fürs Folgejahr.
 *
 * Alles hängt an EINEM Abruf (/api/haushalt/uebersicht?jahr=…) — Budget,
 * Verbrauch, Restmittel und Ideen kommen fertig gerechnet aus dem Server, das
 * Frontend zeigt sie nur an. Die Rechenregeln (was zählt als Verbrauch, was
 * verfällt) stehen damit an einer Stelle und nicht doppelt.
 */
(function () {
  'use strict';
  if (!window.DRS) return;
  const { el, feld, modal, toast, confirmDanger, postJSON, getJSON } = DRS;

  const jahrSel = document.getElementById('hhJahr');
  const toepfeEl = document.getElementById('hhToepfe');
  const ideenEl = document.getElementById('hhIdeen');

  const ARTEN = [
    ['verwaltung', 'Verwaltungshaushalt'],
    ['vermoegen', 'Vermögenshaushalt'],
  ];
  const PRIOS = [[1, 'hoch'], [2, 'mittel'], [3, 'niedrig']];
  const STATUS = [
    ['offen', 'Offen'], ['beantragt', 'Beantragt'], ['bewilligt', 'Bewilligt'],
    ['abgelehnt', 'Abgelehnt'], ['verworfen', 'Verworfen'],
  ];

  let jahr = new Date().getFullYear();
  let daten = null;

  function eur(n) {
    return (Number(n) || 0).toLocaleString('de-DE',
      { style: 'currency', currency: 'EUR' });
  }
  function label(paare, wert) {
    const p = paare.find((x) => String(x[0]) === String(wert));
    return p ? p[1] : String(wert);
  }
  function auswahl(paare, wert) {
    const s = el('select', {}, paare.map(([v, l]) => el('option', { value: v }, l)));
    s.value = String(wert);
    return s;
  }

  // ── Laden ─────────────────────────────────────────────────────────────
  async function laden() {
    let d;
    try {
      d = await getJSON('/api/haushalt/uebersicht?jahr=' + jahr);
    } catch (_) {
      toepfeEl.innerHTML = '<div class="card"><div class="flash flash-err" '
        + 'style="display:block">Der Haushalt konnte nicht geladen werden.</div></div>';
      return;
    }
    if (!d.ok) { toast(d.error || 'Fehler beim Laden.'); return; }
    daten = d;
    fuelleJahre(d.jahre || []);
    render();
  }

  function fuelleJahre(jahre) {
    if (!jahrSel) return;
    const vorhanden = jahre.slice();
    if (!vorhanden.includes(jahr)) vorhanden.push(jahr);
    vorhanden.sort((a, b) => b - a);
    jahrSel.innerHTML = '';
    vorhanden.forEach((j) => jahrSel.appendChild(
      el('option', { value: j, selected: j === jahr ? true : null }, String(j))));
    jahrSel.value = String(jahr);
  }

  // ── Töpfe ─────────────────────────────────────────────────────────────
  function render() {
    toepfeEl.innerHTML = '';
    ARTEN.forEach(([art, name]) => {
      const topf = (daten.toepfe || {})[art];
      if (!topf) return;
      toepfeEl.appendChild(topfKarte(art, name, topf));
    });
    renderIdeen();
  }

  function topfKarte(art, name, topf) {
    const zeilen = (topf.posten || []).map((p) => {
      const anteil = p.budget > 0 ? Math.min(100, (p.verbrauch / p.budget) * 100) : 0;
      return el('tr', {
        class: 'hh-row' + (p.ueberzogen ? ' hh-row-neg' : ''),
        onClick: () => postenDialog(art, p),
      }, [
        el('td', {}, [
          el('div', {}, p.bezeichnung || '(ohne Bezeichnung)'),
          p.notiz ? el('div', { class: 'muted', style: 'font-size:11px' }, p.notiz) : null,
          el('div', { class: 'hh-bar-rest' + (p.ueberzogen ? ' voll' : '') },
            el('span', { style: 'width:' + anteil + '%' })),
        ]),
        el('td', { class: 'hh-num' }, eur(p.budget)),
        el('td', { class: 'hh-num' }, eur(p.verbrauch)),
        el('td', { class: 'hh-num', style: 'font-weight:600' }, eur(p.rest)),
      ]);
    });

    const tabelle = zeilen.length ? el('table', { class: 'hh-table' }, [
      el('thead', {}, el('tr', {}, [
        el('th', {}, 'Posten'),
        el('th', { class: 'hh-num' }, 'Genehmigt'),
        el('th', { class: 'hh-num' }, 'Verausgabt'),
        el('th', { class: 'hh-num' }, 'Restmittel'),
      ])),
      el('tbody', {}, zeilen),
      el('tfoot', {}, el('tr', {}, [
        el('td', {}, 'Summe'),
        el('td', { class: 'hh-num' }, eur(topf.summe_budget)),
        el('td', { class: 'hh-num' }, eur(topf.summe_verbrauch)),
        el('td', { class: 'hh-num' }, eur(topf.summe_rest)),
      ])),
    ]) : el('p', { class: 'muted' }, 'Für ' + jahr + ' ist hier noch kein Posten angelegt.');

    return el('div', { class: 'card' }, [
      el('div', { class: 'hh-kopf' }, [
        el('h2', {}, topf.label || name),
        el('span', { class: 'muted' }, topf.hinweis || ''),
        el('div', { style: 'flex:1' }),
        el('button', {
          type: 'button', class: 'btn-sec',
          onClick: () => postenDialog(art, null),
        }, '+ Posten'),
      ]),
      el('div', { style: 'overflow-x:auto' }, tabelle),
    ]);
  }

  function postenDialog(art, posten) {
    const bez = el('input', { value: posten ? posten.bezeichnung : '', maxlength: '200' });
    const betrag = el('input', {
      type: 'number', step: '0.01', min: '0',
      value: posten ? String(posten.budget) : '',
    });
    const artSel = auswahl(ARTEN, art);
    const notiz = el('textarea', { rows: '2' }, posten ? posten.notiz : '');

    const info = posten ? el('p', { class: 'muted' },
      'Verausgabt: ' + eur(posten.verbrauch) + ' · Restmittel: ' + eur(posten.rest)) : null;

    const aktionen = [{ label: 'Abbrechen', kind: 'sec', onClick: (c) => c() }];
    if (posten) {
      aktionen.push({
        label: 'Löschen', kind: 'danger', onClick: (c) => {
          c();
          confirmDanger({
            title: 'Posten löschen?',
            text: 'Der Posten „' + (posten.bezeichnung || '') + '" wird entfernt.',
            facts: [{ label: 'bereits verausgabt', wert: eur(posten.verbrauch) }],
            warnung: 'Solange Kosten darauf gebucht sind, verweigert der Server das Löschen — '
              + 'sonst änderten sich die Summen eines abgeschlossenen Jahres rückwirkend.',
            danger: 'Endgültig löschen',
            onDanger: async (close) => {
              try {
                await postJSON('/api/haushalt/posten/' + posten.id + '/delete', {});
                close(); toast('Posten gelöscht.'); laden();
              } catch (e) { toast(e.message, 5000); }
            },
          });
        },
      });
    }
    aktionen.push({
      label: 'Speichern', kind: 'primary', onClick: async (close) => {
        try {
          await postJSON('/api/haushalt/posten', {
            id: posten ? posten.id : null,
            jahr: jahr,
            art: artSel.value,
            bezeichnung: bez.value,
            betrag: betrag.value,
            notiz: notiz.value,
          });
          close(); toast('Gespeichert.'); laden();
        } catch (e) { toast(e.message); }
      },
    });

    modal({
      title: posten ? 'Haushaltsposten bearbeiten' : 'Neuer Haushaltsposten',
      body: el('div', {}, [
        feld('Bezeichnung', bez, 'z. B. „Werkstattverbrauchsmaterial"'),
        feld('Genehmigter Betrag (€)', betrag),
        feld('Haushalt', artSel,
          'Verwaltungshaushalt bis 999 €, Vermögenshaushalt ab 1000 €.'),
        feld('Notiz', notiz),
        info,
      ]),
      actions: aktionen,
    });
  }

  // ── Ideen fürs Folgejahr ──────────────────────────────────────────────
  function renderIdeen() {
    ideenEl.innerHTML = '';
    const d = daten.ideen || { ideen: [], zieljahr: jahr + 1 };

    const liste = (d.ideen || []).map((i) => el('div', {
      class: 'hh-idee', onClick: () => ideeDialog(i),
    }, [
      el('span', { class: 'hh-prio p' + i.prioritaet }, i.prio_label),
      el('div', { class: 'hh-idee-haupt' }, [
        el('div', { class: 'hh-idee-titel' }, i.titel || '(ohne Titel)'),
        el('div', { class: 'muted', style: 'font-size:11px' },
          label(ARTEN, i.art) + ' · ' + label(STATUS, i.status)
          + (i.vorgang_id ? ' · Vorgang angelegt' : '')),
      ]),
      el('span', { class: 'hh-num', style: 'font-weight:600' }, eur(i.betrag)),
    ]));

    ideenEl.appendChild(el('div', { class: 'card' }, [
      el('div', { class: 'hh-kopf' }, [
        el('h2', {}, 'Anschaffungsideen ' + d.zieljahr),
        el('span', { class: 'muted' },
          'Sammlung fürs kommende Haushaltsjahr — Grundlage der Anträge.'),
        el('div', { style: 'flex:1' }),
        el('button', {
          type: 'button', class: 'btn-sec', onClick: () => ideeDialog(null),
        }, '+ Idee'),
      ]),
      liste.length ? el('div', {}, liste)
        : el('p', { class: 'muted' }, 'Noch keine Idee für ' + d.zieljahr + ' notiert.'),
      el('p', { class: 'muted', style: 'margin-top:.8rem' },
        'Angemeldeter Bedarf: ' + eur(d.summe_verwaltung) + ' Verwaltungshaushalt · '
        + eur(d.summe_vermoegen) + ' Vermögenshaushalt '
        + '(ohne abgelehnte und verworfene).'),
    ]));
  }

  function ideeDialog(idee) {
    const zieljahr = (daten.ideen && daten.ideen.zieljahr) || (jahr + 1);
    const titel = el('input', { value: idee ? idee.titel : '', maxlength: '200' });
    const betrag = el('input', {
      type: 'number', step: '0.01', min: '0',
      value: idee ? String(idee.betrag) : '',
    });
    const artSel = auswahl(ARTEN, idee ? idee.art : 'verwaltung');
    const prio = auswahl(PRIOS, idee ? idee.prioritaet : 2);
    const status = auswahl(STATUS, idee ? idee.status : 'offen');
    const begr = el('textarea', { rows: '3' }, idee ? idee.begruendung : '');

    // Der Betrag schlägt den Topf vor, solange man ihn nicht selbst gewählt hat.
    let artBeruehrt = !!idee;
    artSel.addEventListener('change', () => { artBeruehrt = true; });
    betrag.addEventListener('input', () => {
      if (artBeruehrt) return;
      artSel.value = Number(betrag.value) >= 1000 ? 'vermoegen' : 'verwaltung';
    });

    const aktionen = [{ label: 'Abbrechen', kind: 'sec', onClick: (c) => c() }];
    if (idee) {
      if (!idee.vorgang_id) {
        aktionen.push({
          label: 'Vorgang anlegen', kind: 'sec', onClick: async (close) => {
            try {
              const r = await postJSON('/api/haushalt/ideen/' + idee.id + '/vorgang', {});
              close();
              location.href = '/vorgaenge/' + r.vorgang_id;
            } catch (e) { toast(e.message); }
          },
        });
      }
      aktionen.push({
        label: 'Löschen', kind: 'danger', onClick: async (close) => {
          try {
            await postJSON('/api/haushalt/ideen/' + idee.id + '/delete', {});
            close(); toast('Idee gelöscht.'); laden();
          } catch (e) { toast(e.message); }
        },
      });
    }
    aktionen.push({
      label: 'Speichern', kind: 'primary', onClick: async (close) => {
        try {
          await postJSON('/api/haushalt/ideen', {
            id: idee ? idee.id : null,
            zieljahr: zieljahr,
            art: artSel.value,
            titel: titel.value,
            betrag: betrag.value,
            begruendung: begr.value,
            prioritaet: prio.value,
            status: status.value,
          });
          close(); toast('Gespeichert.'); laden();
        } catch (e) { toast(e.message); }
      },
    });

    modal({
      title: idee ? 'Anschaffungsidee' : 'Neue Anschaffungsidee für ' + zieljahr,
      body: el('div', {}, [
        feld('Was soll angeschafft werden?', titel),
        feld('Geschätzter Betrag (€)', betrag),
        feld('Haushalt', artSel, 'Wird aus dem Betrag vorgeschlagen.'),
        feld('Priorität', prio),
        feld('Begründung', begr, 'Wandert später in den Antrag.'),
        idee ? feld('Status', status) : null,
      ]),
      actions: aktionen,
    });
  }

  // ── Verdrahtung ───────────────────────────────────────────────────────
  if (jahrSel) jahrSel.addEventListener('change', () => {
    jahr = Number(jahrSel.value) || jahr;
    laden();
  });
  const neuBtn = document.getElementById('hhNeuerPosten');
  if (neuBtn) neuBtn.addEventListener('click', () => postenDialog('verwaltung', null));

  laden();
})();
