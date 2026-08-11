/* Schüler-Detailseite im Klassenmodul: die Notiz-Zeitleiste.
 *
 * Die Notizen kommen beim ersten Aufbau serverseitig mit (window.KLASSEN_SCHUELER),
 * danach hält dieses Skript die Liste im Speicher und schreibt sie nach jedem
 * Request neu — ein Reload nach dem Speichern wäre auf dem Handy im Unterricht
 * genau der Moment, in dem man ihn nicht gebrauchen kann.
 *
 * Regel aus früheren Fehlern: Dieses Skript läuft im scripts-Block, also NACH
 * drs.js — sonst gäbe es window.DRS beim Verdrahten noch nicht.
 */
(function () {
  'use strict';
  if (!window.DRS || !window.KLASSEN_SCHUELER) return;
  const { el, feld, modal, toast, confirmDanger, postJSON } = DRS;

  const SID = window.KLASSEN_SCHUELER.id;
  const HEUTE = window.KLASSEN_SCHUELER.heute;
  const KATEGORIEN = window.KLASSEN_SCHUELER.kategorien || {};
  let NOTIZEN = window.KLASSEN_SCHUELER.notizen || [];

  const histEl = document.getElementById('ksHist');

  function fmtDate(iso) {
    if (!iso) return 'ohne Datum';
    const p = String(iso).split('-');
    return p.length === 3 ? p[2] + '.' + p[1] + '.' + p[0] : iso;
  }

  // Sortierung wie der Server: jüngstes Datum zuerst, bei Gleichstand die
  // zuletzt angelegte Notiz oben. So springt ein frischer Eintrag nicht
  // woandershin, sobald man die Seite neu lädt.
  function sortiere() {
    NOTIZEN.sort(function (a, b) {
      if ((a.datum || '') !== (b.datum || '')) {
        return (b.datum || '') < (a.datum || '') ? -1 : 1;
      }
      return b.id - a.id;
    });
  }

  function zeichne() {
    histEl.textContent = '';
    if (!NOTIZEN.length) {
      histEl.appendChild(el('p', { class: 'muted' },
        'Noch nichts notiert. „+ Notiz" hält Beobachtungen, Gespräche und '
        + 'Vereinbarungen mit Datum fest.'));
      return;
    }
    for (const n of NOTIZEN) {
      histEl.appendChild(zeile(n));
    }
  }

  function zeile(n) {
    const node = el('div', { class: 'ks-eintrag' }, [
      el('div', { class: 'ks-e-kopf' }, [
        el('span', { class: 'ks-kat ' + (n.farbe || '') }, n.kategorie_label),
        el('span', { class: 'ks-e-datum' }, fmtDate(n.datum)),
      ]),
      el('div', { class: 'ks-e-body' }, n.text),
    ]);
    node.addEventListener('click', function () { bearbeiten(n); });
    return node;
  }

  function kategorieWahl(wert) {
    const s = el('select', {}, Object.keys(KATEGORIEN).map(function (k) {
      return el('option', { value: k }, KATEGORIEN[k].label);
    }));
    s.value = wert || 'beobachtung';
    return s;
  }

  function formular(entwurf) {
    const datum = el('input', { type: 'date', value: entwurf.datum || HEUTE });
    const kategorie = kategorieWahl(entwurf.kategorie);
    const text = el('textarea', { rows: '6' });
    text.value = entwurf.text || '';
    return {
      node: el('div', {}, [
        feld('Datum', datum, 'Wann war die Beobachtung — nicht, wann du tippst.'),
        feld('Kategorie', kategorie),
        feld('Notiz', text),
      ]),
      lies: function () {
        return {
          datum: datum.value || '',
          kategorie: kategorie.value,
          text: (text.value || '').trim(),
        };
      },
    };
  }

  function neu() {
    const f = formular({ datum: HEUTE });
    const dlg = modal({
      title: 'Neue Notiz',
      body: f.node,
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: function (c) { c(); } },
        {
          label: 'Speichern', kind: 'primary', onClick: async function (c) {
            const daten = f.lies();
            if (!daten.text) { toast('Die Notiz braucht einen Text.'); return; }
            try {
              const r = await postJSON('/api/schueler/' + SID + '/notizen', daten);
              NOTIZEN.push(r.notiz);
              sortiere();
              zeichne();
              c();
              toast('Notiz gespeichert.');
            } catch (e) {
              toast(e.message || 'Speichern fehlgeschlagen.');
            }
          },
        },
      ],
    });
    return dlg;
  }

  function bearbeiten(n) {
    const f = formular(n);
    modal({
      title: 'Notiz bearbeiten',
      body: f.node,
      actions: [
        {
          label: 'Löschen', kind: 'danger', onClick: function (c) {
            c();
            confirmDanger({
              title: 'Notiz löschen?',
              text: 'Die Notiz wird endgültig entfernt.',
              danger: 'Löschen',
              onDanger: async function (c2) {
                try {
                  await postJSON('/api/schueler-notizen/' + n.id + '/delete', {});
                  NOTIZEN = NOTIZEN.filter(function (x) { return x.id !== n.id; });
                  zeichne();
                  c2();
                  toast('Notiz gelöscht.');
                } catch (e) {
                  toast(e.message || 'Löschen fehlgeschlagen.');
                }
              },
            });
          },
        },
        { label: 'Abbrechen', kind: 'sec', onClick: function (c) { c(); } },
        {
          label: 'Speichern', kind: 'primary', onClick: async function (c) {
            const daten = f.lies();
            if (!daten.text) { toast('Die Notiz braucht einen Text.'); return; }
            try {
              const r = await postJSON('/api/schueler-notizen/' + n.id + '/save', daten);
              const i = NOTIZEN.findIndex(function (x) { return x.id === n.id; });
              if (i >= 0) NOTIZEN[i] = r.notiz;
              sortiere();
              zeichne();
              c();
              toast('Notiz gespeichert.');
            } catch (e) {
              toast(e.message || 'Speichern fehlgeschlagen.');
            }
          },
        },
      ],
    });
  }

  document.getElementById('ksNeu').addEventListener('click', neu);
  sortiere();
  zeichne();
})();
