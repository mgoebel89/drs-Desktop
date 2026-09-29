/* Unterrichtsbesuche — Detailseite eines Besuchs = Nachbereitung am PC:
 * Kopfdaten, Verlauf (bearbeitbar, derselbe Editor wie am Handy),
 * Reflexionsgespräch und Vereinbarungen, Protokoll-Export, Status, Löschen. */
(function () {
  'use strict';
  if (!window.DRS || !window.UB || !window.UBC || !window.UBC.editor) return;
  const { el, feld, modal, toast, confirmDanger, postJSON } = DRS;
  const { fmtDatum, wochentag, sortiere, verlauf, chipWahl } = UBC;

  const B = window.UB.besuch;
  const STATUS = window.UB.status;

  function zeichneKopf() {
    let zeit = wochentag(B.datum) + ', ' + fmtDatum(B.datum);
    if (B.beginn) zeit += ' · ' + B.beginn + (B.ende ? '–' + B.ende : '') + ' Uhr';
    document.getElementById('ubdMeta').textContent = zeit;
    const st = document.getElementById('ubdStatus');
    st.className = 'ub-status ' + B.status;
    st.textContent = STATUS[B.status] || B.status;
    document.getElementById('ubdStatusBtn').textContent =
      B.status === 'abgeschlossen' ? 'Wieder öffnen' : 'Abschließen';

    const tab = document.getElementById('ubdDaten');
    tab.textContent = '';
    const zeilen = [
      ['Klasse / Raum', [B.klasse, B.raum].filter(Boolean).join(' / ') || '—'],
      ['Thema', B.thema || '—'],
      ['Lernziele', B.lernziele || '—'],
    ];
    zeilen.forEach(function (z) {
      tab.appendChild(el('tr', {}, [el('th', {}, z[0]), el('td', {}, z[1])]));
    });
    tab.appendChild(el('tr', {}, [
      el('th', {}, 'Beratungs­schwerpunkte'),
      el('td', {}, B.schwerpunkte.length
        ? el('ol', { style: 'margin:0 0 0 1.1rem;white-space:normal' },
            B.schwerpunkte.map(function (s) { return el('li', {}, s.text); }))
        : '—'),
    ]));
  }

  // Verlauf: anklickbar, derselbe Editor wie am Handy (ub-eintrag.js)
  const Z = { eintraege: B.eintraege || [] };
  const ed = UBC.editor({
    besuch: B, katalog: window.UB.katalog, icons: window.UB.icons,
    wertungen: window.UB.wertungen, zustand: Z, zeichne: zeichneVerlauf,
  });

  function zeichneVerlauf(scrollZuId) {
    sortiere(Z.eintraege);
    B.eintraege = Z.eintraege;
    const box = document.getElementById('ubdVerlauf');
    verlauf(box, Z.eintraege, {
      katalog: window.UB.katalog, icons: window.UB.icons, wertungen: window.UB.wertungen,
      schwerpunkte: B.schwerpunkte,
      leertext: 'Noch nichts erfasst. „Erfassen" öffnet die Handy-Ansicht zum Mitschreiben.',
      onClick: function (e) { if (e.art === 'phase') ed.phasenBlatt(e); else ed.eintragBlatt(e, null); },
    });
    if (scrollZuId) {
      const n = box.querySelector('[data-id="' + scrollZuId + '"]');
      if (n) n.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  function zeichneVorige() {
    const box = document.getElementById('ubdVorige');
    box.textContent = '';
    if (!B.vorige) return;
    box.appendChild(el('div', { class: 'card ube-vorige' }, [
      el('strong', { style: 'color:#8a5a00' }, 'Vereinbarungen vom letzten Besuch ('),
      el('a', { href: '/unterrichtsbesuche/' + B.vorige.id }, fmtDatum(B.vorige.datum)),
      el('strong', { style: 'color:#8a5a00' }, ')'),
      el('div', { style: 'white-space:pre-wrap;margin-top:.3rem' }, B.vorige.vereinbarungen),
    ]));
  }

  // ── Nachbereitung: Reflexionsgespräch + Vereinbarungen ──────────────
  const refl = document.getElementById('ubdReflexion');
  const vereinb = document.getElementById('ubdVereinbarungen');
  const stand = document.getElementById('ubdNbStand');
  refl.value = B.reflexion || '';
  vereinb.value = B.vereinbarungen || '';
  function nbGeaendert() {
    return refl.value !== (B.reflexion || '') || vereinb.value !== (B.vereinbarungen || '');
  }
  function malStand() { stand.textContent = nbGeaendert() ? 'Nicht gespeicherte Änderungen' : ''; }
  refl.addEventListener('input', malStand);
  vereinb.addEventListener('input', malStand);
  async function nbSpeichern() {
    try {
      const r = await postJSON('/api/ub/besuche/' + B.id + '/save',
        { reflexion: refl.value, vereinbarungen: vereinb.value });
      B.reflexion = r.besuch.reflexion;
      B.vereinbarungen = r.besuch.vereinbarungen;
      malStand();
      toast('Nachbereitung gespeichert.');
    } catch (e) { toast(ed.fehlertext(e)); }
  }
  // Wer mit ungespeichertem Text die Seite verlässt, wird gefragt
  window.addEventListener('beforeunload', function (ev) {
    if (nbGeaendert()) { ev.preventDefault(); ev.returnValue = ''; }
  });

  function bearbeiten() {
    const e = { datum: B.datum, beginn: B.beginn, ende: B.ende, klasse: B.klasse,
      raum: B.raum, thema: B.thema, lernziele: B.lernziele,
      schwerpunkte: B.schwerpunkte.map(function (s) { return s.id; }) };
    function inp(typ, key) {
      const i = el('input', { type: typ, value: e[key] || '' });
      i.addEventListener('input', function () { e[key] = i.value; });
      return i;
    }
    const lz = el('textarea', { rows: '3' });
    lz.value = e.lernziele || '';
    lz.addEventListener('input', function () { e.lernziele = lz.value; });

    // Aktive Beratungsschwerpunkte plus die schon gewählten (auch wenn stillgelegt)
    const katalog = window.UB.katalog.kriterien.filter(function (k) {
      return k.active || e.schwerpunkte.indexOf(k.id) >= 0;
    });
    const spBox = katalog.length
      ? chipWahl(katalog, e.schwerpunkte, true, function (neu) { e.schwerpunkte = neu; })
      : el('p', { class: 'muted' }, 'Noch keine Beratungsschwerpunkte in den Einstellungen.');

    modal({
      title: 'Kopfdaten bearbeiten',
      body: el('div', {}, [
        el('div', { class: 'form-2' }, [
          feld('Datum', inp('date', 'datum')),
          el('div', { class: 'form-2' }, [feld('Beginn', inp('time', 'beginn')), feld('Ende', inp('time', 'ende'))]),
          feld('Klasse', inp('text', 'klasse')),
          feld('Raum', inp('text', 'raum')),
        ]),
        feld('Thema', inp('text', 'thema')),
        feld('Lernziele', lz),
        feld('Beratungsschwerpunkte des Anwärters', spBox,
          'Abwählen nimmt keinem Eintrag seine Zuordnung.'),
      ]),
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: function (c) { c(); } },
        { label: 'Speichern', kind: 'primary', onClick: async function (c) {
          if (!e.datum) { toast('Bitte ein Datum angeben.'); return; }
          try {
            const r = await postJSON('/api/ub/besuche/' + B.id + '/save', e);
            Object.assign(B, r.besuch);
            zeichneKopf();
            zeichneVorige();      // neues Datum → ggf. anderer Vorgänger-Besuch
            zeichneVerlauf();
            c();
            toast('Gespeichert.');
          } catch (err) { toast(err.message); }
        } },
      ],
    });
  }

  async function statusWechsel() {
    const neu = B.status === 'abgeschlossen' ? 'laufend' : 'abgeschlossen';
    try {
      const r = await postJSON('/api/ub/besuche/' + B.id + '/save', { status: neu });
      B.status = r.besuch.status;
      zeichneKopf();
      toast(neu === 'abgeschlossen' ? 'Besuch abgeschlossen.' : 'Wieder geöffnet.');
    } catch (e) { toast(e.message); }
  }

  function loeschen() {
    const eintraege = B.eintraege.filter(function (e) { return e.art === 'eintrag'; });
    const fotos = eintraege.filter(function (e) { return e.foto; }).length;
    confirmDanger({
      title: 'Besuch löschen?',
      facts: [{ wert: eintraege.length, label: 'Einträge' }, { wert: fotos, label: 'Fotos' }],
      warnung: 'Der Besuch wird mit allen Einträgen und Fotos endgültig gelöscht. '
        + 'Wer das Protokoll behalten will, lädt vorher das PDF herunter.',
      danger: 'Endgültig löschen',
      onDanger: async function (c) {
        try {
          await postJSON('/api/ub/besuche/' + B.id + '/delete', {});
          location.href = '/unterrichtsbesuche';
        } catch (e) { toast(e.message); c(); }
      },
    });
  }

  document.getElementById('ubdPdf').addEventListener('click', function () {
    UBC.exportDialog(B.id, window.UB.ordnungen, window.UB.standardOrdnung);
  });
  document.getElementById('ubdNeuEintrag').addEventListener('click', function () { ed.eintragBlatt(null, null); });
  document.getElementById('ubdNeuPhase').addEventListener('click', function () { ed.phasenBlatt(null); });
  document.getElementById('ubdNbSpeichern').addEventListener('click', nbSpeichern);
  zeichneVorige();
  document.getElementById('ubdEdit').addEventListener('click', bearbeiten);
  document.getElementById('ubdStatusBtn').addEventListener('click', statusWechsel);
  document.getElementById('ubdDel').addEventListener('click', loeschen);
  zeichneKopf();
  zeichneVerlauf();
})();
