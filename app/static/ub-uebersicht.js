/* Unterrichtsbesuche — Übersicht: Anwärter-Karten, Anwärter-Modal und der
 * Assistent „Neuer Besuch".
 *
 * Der Assistent speichert erst am Ende, in EINEM Request — auch ein dabei neu
 * angelegter Anwärter entsteht erst dort. Ein Abbruch hinterlässt nichts.
 */
(function () {
  'use strict';
  if (!window.DRS || !window.UB || !window.UBC) return;
  const { el, feld, modal, toast, confirmDanger, wizard, postJSON, getJSON } = DRS;
  const { fmtDatum } = UBC;

  let ANWAERTER = window.UB.anwaerter || [];
  const grid = document.getElementById('ubAnwGrid');

  // ── Anwärter-Karten ─────────────────────────────────────────────────

  function zeichneAnwaerter() {
    grid.textContent = '';
    if (!ANWAERTER.length) {
      grid.appendChild(el('p', { class: 'muted' },
        'Noch keine Anwärter. „+ Anwärter" legt jemanden an — oder direkt im Assistenten „+ Besuch".'));
      return;
    }
    ANWAERTER.forEach(function (a) {
      grid.appendChild(el('button', {
        type: 'button', class: 'obj-card' + (a.active ? '' : ' inaktiv'),
        onClick: function () { anwaerterModal(a); },
      }, [
        el('span', { class: 'obj-card-title' }, a.name),
        el('span', { class: 'obj-card-meta' }, [a.faecher, a.seminar].filter(Boolean).join(' · ') || '—'),
        el('span', { class: 'obj-card-meta' },
          (a.besuche === 1 ? '1 Besuch' : a.besuche + ' Besuche') + (a.active ? '' : ' · stillgelegt')),
      ]));
    });
  }

  function anwaerterFelder(a) {
    const name = el('input', { type: 'text', value: a.name || '', maxlength: '120' });
    const faecher = el('input', { type: 'text', value: a.faecher || '', placeholder: 'z. B. Mechatronik / Physik' });
    const seminar = el('input', { type: 'text', value: a.seminar || '', placeholder: 'Studienseminar, Fachleiter …' });
    const notiz = el('textarea', { rows: '3' });
    notiz.value = a.notiz || '';
    return {
      nodes: [feld('Name', name), feld('Fächer', faecher), feld('Seminar', seminar), feld('Notiz', notiz)],
      name: name,
      lies: function () {
        return { name: name.value.trim(), faecher: faecher.value.trim(),
          seminar: seminar.value.trim(), notiz: notiz.value.trim() };
      },
    };
  }

  function neuerAnwaerter() {
    const f = anwaerterFelder({});
    modal({
      title: 'Neuer Anwärter',
      body: el('div', {}, f.nodes),
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: function (c) { c(); } },
        { label: 'Anlegen', kind: 'primary', onClick: async function (c) {
          const d = f.lies();
          if (!d.name) { toast('Bitte einen Namen eintragen.'); return; }
          try {
            const r = await postJSON('/api/ub/anwaerter', d);
            r.anwaerter.besuche = 0;
            ANWAERTER.push(r.anwaerter);
            ANWAERTER.sort(function (x, y) { return x.name.localeCompare(y.name, 'de'); });
            zeichneAnwaerter();
            c();
            toast('Anwärter angelegt.');
          } catch (e) { toast(e.message); }
        } },
      ],
    });
  }

  function anwaerterModal(a) {
    const f = anwaerterFelder(a);
    const besucheBox = el('div', { class: 'muted' }, 'Besuche werden geladen …');
    getJSON('/api/ub/anwaerter/' + a.id + '/besuche').then(function (r) {
      besucheBox.textContent = '';
      besucheBox.className = '';
      if (!r.besuche.length) {
        besucheBox.appendChild(el('p', { class: 'muted' }, 'Noch kein Besuch.'));
        return;
      }
      besucheBox.appendChild(el('ul', { style: 'margin:0 0 0 1.1rem' }, r.besuche.map(function (b) {
        return el('li', {}, [
          el('a', { href: '/unterrichtsbesuche/' + b.id }, fmtDatum(b.datum)),
          ' · ' + (b.thema || 'ohne Thema') + ' · ' + b.status_label,
        ]);
      })));
    }).catch(function () { besucheBox.textContent = 'Konnte die Besuche nicht laden.'; });

    const dlg = modal({
      title: a.name,
      body: el('div', {}, f.nodes.concat([
        el('div', { class: 'drs-field' }, [el('span', { class: 'drs-field-label' }, 'Besuche'), besucheBox]),
        el('button', { type: 'button', class: 'btn-sec', onClick: function () {
          dlg.close();
          besuchAssistent(a.id);
        } }, '+ Besuch für ' + a.name),
      ])),
      actions: [
        { label: a.active ? 'Stilllegen / Löschen' : 'Reaktivieren', kind: 'sec', onClick: function (c) {
          c();
          if (!a.active) { speichern(a, { active: true }, 'Wieder aktiv.'); return; }
          entfernen(a);
        } },
        { label: 'Abbrechen', kind: 'sec', onClick: function (c) { c(); } },
        { label: 'Speichern', kind: 'primary', onClick: async function (c) {
          const d = f.lies();
          if (!d.name) { toast('Bitte einen Namen eintragen.'); return; }
          if (await speichern(a, d, 'Gespeichert.')) c();
        } },
      ],
    });
  }

  async function speichern(a, daten, meldung) {
    try {
      const r = await postJSON('/api/ub/anwaerter/' + a.id + '/save', daten);
      Object.assign(a, r.anwaerter);
      zeichneAnwaerter();
      toast(meldung);
      return true;
    } catch (e) { toast(e.message); return false; }
  }

  function entfernen(a) {
    const hatBesuche = a.besuche > 0;
    confirmDanger({
      title: a.name + ' entfernen?',
      facts: [{ wert: a.besuche, label: a.besuche === 1 ? 'Besuch mit Protokoll' : 'Besuche mit Protokoll' }],
      text: hatBesuche
        ? 'Weil Besuche an dieser Person hängen, kann sie nur stillgelegt werden. '
          + 'Sie verschwindet dann aus der Auswahl im Assistenten, die Protokolle bleiben.'
        : 'Noch kein Besuch — die Person kann gelöscht oder stillgelegt werden.',
      safe: 'Stilllegen',
      onSafe: async function (c) { c(); await speichern(a, { active: false }, 'Stillgelegt.'); },
      danger: hatBesuche ? null : 'Löschen',
      onDanger: hatBesuche ? null : async function (c) {
        try {
          await postJSON('/api/ub/anwaerter/' + a.id + '/delete', {});
          ANWAERTER = ANWAERTER.filter(function (x) { return x.id !== a.id; });
          zeichneAnwaerter();
          c();
          toast('Gelöscht.');
        } catch (e) { toast(e.message); }
      },
    });
  }

  // ── Assistent „Neuer Besuch" ────────────────────────────────────────

  function besuchAssistent(vorwahl) {
    const aktive = ANWAERTER.filter(function (a) { return a.active; });
    const ctx = {
      anwaerter_id: vorwahl || (aktive.length === 1 ? aktive[0].id : null),
      neu: !aktive.length,
      neuer: { name: '', faecher: '', seminar: '' },
      datum: window.UB.heute, beginn: '', ende: '', klasse: '', raum: '',
      thema: '', lernziele: '',
      schwerpunkte: ['', ''],
    };

    function binde(input, key, ziel) {
      const obj = ziel || ctx;
      input.value = obj[key] || '';
      input.addEventListener('input', function () { obj[key] = input.value; });
      return input;
    }

    wizard({
      title: 'Neuer Unterrichtsbesuch',
      ctx: ctx,
      finishLabel: 'Besuch anlegen',
      steps: [
        {
          key: 'anwaerter', label: 'Anwärter',
          render: function (ctx, body) {
            const wahl = el('div', { class: 'ub-wahl' });
            const neuBox = el('div', { style: 'margin-top:1rem' }, [
              feld('Name', binde(el('input', { type: 'text' }), 'name', ctx.neuer)),
              feld('Fächer', binde(el('input', { type: 'text' }), 'faecher', ctx.neuer)),
              feld('Seminar', binde(el('input', { type: 'text' }), 'seminar', ctx.neuer)),
            ]);
            function zeichne() {
              wahl.textContent = '';
              aktive.forEach(function (a) {
                wahl.appendChild(el('button', {
                  type: 'button', class: (!ctx.neu && ctx.anwaerter_id === a.id) ? 'aktiv' : '',
                  onClick: function () { ctx.neu = false; ctx.anwaerter_id = a.id; zeichne(); },
                }, [a.name, el('small', {}, a.faecher || ' ')]));
              });
              wahl.appendChild(el('button', {
                type: 'button', class: ctx.neu ? 'aktiv' : '',
                onClick: function () { ctx.neu = true; zeichne(); },
              }, ['+ Neue Person', el('small', {}, 'wird mit dem Besuch angelegt')]));
              neuBox.style.display = ctx.neu ? 'block' : 'none';
            }
            body.appendChild(el('p', { class: 'muted' }, 'Wen besuchst du?'));
            body.appendChild(wahl);
            body.appendChild(neuBox);
            zeichne();
          },
          validate: function (ctx) {
            if (ctx.neu) return ctx.neuer.name.trim() ? null : 'Bitte den Namen der neuen Person eintragen.';
            return ctx.anwaerter_id ? null : 'Bitte eine Person auswählen.';
          },
        },
        {
          key: 'stunde', label: 'Stunde',
          render: function (ctx, body) {
            const lz = el('textarea', { rows: '3', placeholder: 'Die Lernenden …' });
            body.appendChild(el('div', { class: 'form-2' }, [
              feld('Datum', binde(el('input', { type: 'date' }), 'datum')),
              el('div', { class: 'form-2' }, [
                feld('Beginn', binde(el('input', { type: 'time' }), 'beginn')),
                feld('Ende', binde(el('input', { type: 'time' }), 'ende')),
              ]),
              feld('Klasse', binde(el('input', { type: 'text', placeholder: 'z. B. BSMT 26a' }), 'klasse')),
              feld('Raum', binde(el('input', { type: 'text' }), 'raum')),
            ]));
            body.appendChild(feld('Thema der Stunde', binde(el('input', { type: 'text' }), 'thema')));
            body.appendChild(feld('Lernziele', binde(lz, 'lernziele'), 'Eine Zeile je Ziel.'));
          },
          validate: function (ctx) { return ctx.datum ? null : 'Bitte ein Datum angeben.'; },
        },
        {
          key: 'schwerpunkte', label: 'Schwerpunkte',
          render: function (ctx, body) {
            const liste = el('div');
            function zeichne() {
              liste.textContent = '';
              ctx.schwerpunkte.forEach(function (t, i) {
                const inp = el('input', { type: 'text', value: t,
                  placeholder: 'z. B. Impulsgebung, Ergebnissicherung …' });
                inp.addEventListener('input', function () { ctx.schwerpunkte[i] = inp.value; });
                liste.appendChild(el('div', { class: 'ub-sp-zeile' }, [
                  el('span', { class: 'muted', style: 'align-self:center;width:1.4rem' }, (i + 1) + '.'),
                  inp,
                  el('button', { type: 'button', class: 'btn-ghost', 'aria-label': 'Entfernen',
                    onClick: function () { ctx.schwerpunkte.splice(i, 1); zeichne(); } }, '×'),
                ]));
              });
            }
            body.appendChild(el('p', { class: 'muted' },
              'Die Beobachtungsschwerpunkte, die der Anwärter für diese Stunde festgelegt hat. '
              + 'Beim Mitschreiben kannst du Einträge direkt einem Schwerpunkt zuordnen. Optional.'));
            body.appendChild(liste);
            body.appendChild(el('button', { type: 'button', class: 'chip-add',
              onClick: function () { ctx.schwerpunkte.push(''); zeichne(); } }, '+ Schwerpunkt'));
            zeichne();
          },
        },
      ],
      onFinish: async function (ctx) {
        const daten = {
          datum: ctx.datum, beginn: ctx.beginn, ende: ctx.ende, klasse: ctx.klasse,
          raum: ctx.raum, thema: ctx.thema, lernziele: ctx.lernziele,
          schwerpunkte: ctx.schwerpunkte.filter(function (s) { return s.trim(); }),
        };
        if (ctx.neu) daten.neuer_anwaerter = ctx.neuer;
        else daten.anwaerter_id = ctx.anwaerter_id;
        const r = await postJSON('/api/ub/besuche', daten);
        location.href = '/unterrichtsbesuche/' + r.id;
      },
    });
  }

  document.getElementById('ubNeuAnw').addEventListener('click', neuerAnwaerter);
  document.getElementById('ubNeuBesuch').addEventListener('click', function () { besuchAssistent(null); });
  zeichneAnwaerter();
})();
