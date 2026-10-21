/* Prüfungen: Anlege-Assistent und Detail-Overlays.
 *
 * Baut auf DRS (drs.js) auf — gleiche Bausteine wie die Stammdaten, damit sich
 * das Modul designtechnisch nicht fremd anfühlt. Grundsatz des Assistenten:
 * Es wird ERST AM ENDE gespeichert, in einem einzigen Request. Ein Abbruch
 * hinterlässt damit nie eine halbe Prüfung.
 */
(function () {
  'use strict';
  const el = DRS.el;
  const EX = (window.DRSExams = window.DRSExams || {});

  // ---------- gemeinsame Bausteine ----------

  function radioZeile(name, wert, titel, sub, gewaehlt) {
    const rb = el('input', { type: 'radio', name: name, value: String(wert) });
    rb.checked = !!gewaehlt;
    return el('label', { class: 'pick-row' }, [
      rb,
      el('span', {}, [
        el('span', { class: 'pick-title' }, titel),
        sub ? el('span', { class: 'pick-sub' }, sub) : null,
      ]),
    ]);
  }

  function artLabel(art) {
    return { klasse: 'Klasse', kombi: 'zusammengelegt', gruppe: 'Teilgruppe' }[art] || art;
  }

  // ---------- Feedbackpunkt-Editor (im Assistenten und im Overlay) ----------

  function punkteEditor(ctx, box) {
    const liste = el('div', { class: 'fp-list' });

    function zeichne() {
      liste.innerHTML = '';
      if (!ctx.punkte.length) {
        liste.appendChild(el('div', { class: 'muted' },
          'Noch keine Feedbackpunkte — du kannst sie auch später anlegen.'));
      }
      ctx.punkte.forEach((p, i) => {
        const name = el('input', { type: 'text', value: p.name || '' });
        name.addEventListener('input', () => { p.name = name.value; });
        const max = el('input', { type: 'number', min: '0', step: '0.5',
          value: p.max_points != null ? p.max_points : 10, style: 'max-width:90px' });
        max.addEventListener('input', () => { p.max_points = parseFloat(max.value) || 0; });
        const weg = el('button', { class: 'btn-sec fp-del', type: 'button', title: 'Punkt entfernen' }, '🗑');
        weg.addEventListener('click', () => { ctx.punkte.splice(i, 1); zeichne(); });
        liste.appendChild(el('div', { class: 'fp-row' }, [
          el('span', { class: 'fp-num' }, String(i + 1)), name, max, weg,
        ]));
      });
    }

    const neu = el('button', { class: 'btn-sec', type: 'button' }, '+ Feedbackpunkt');
    neu.addEventListener('click', () => {
      ctx.punkte.push({ name: '', max_points: 10, scope: 'individual',
        eval_type: ctx.bewertung_mode === 'note' ? 'note' : 'punkte', weight_pct: 0 });
      zeichne();
    });

    // Vorlage übernehmen — ersetzt die aktuelle Liste
    let vorlageWahl = null;
    if ((ctx.vorlagen || []).length) {
      const sel = el('select', {}, [el('option', { value: '' }, 'Vorlage übernehmen …'),
        ...ctx.vorlagen.map(v => el('option', { value: String(v.id) },
          `${v.name} (${(v.punkte || []).length})`))]);
      sel.addEventListener('change', () => {
        const v = ctx.vorlagen.find(x => String(x.id) === sel.value);
        if (!v) return;
        ctx.punkte = (v.punkte || []).map(p => Object.assign({}, p));
        sel.value = '';
        zeichne();
      });
      vorlageWahl = DRS.feld('Aus Vorlage', sel);
    }

    box.appendChild(el('div', {}, [
      vorlageWahl,
      liste,
      el('div', { style: 'margin-top:8px' }, neu),
    ]));
    zeichne();
  }

  // ---------- Anlege-Assistent ----------

  EX.anlegenWizard = async function (vorbelegung) {
    let daten;
    try {
      daten = await DRS.getJSON('/api/exams/pickers');
    } catch (e) {
      DRS.toast('Stammdaten konnten nicht geladen werden.');
      return;
    }
    const vb = vorbelegung || {};
    const ctx = {
      title: vb.title || '',
      datum: vb.datum || daten.heute,
      ziel_typ: '', ziel_id: null,
      bewertung_mode: 'note',
      input_mode: 'numeric',
      grading_scale_key: daten.default_scale,
      punkte: [],
      vorlagen: daten.vorlagen || [],
      lesson_note_id: vb.lesson_note_id || null,
    };
    // Vorbelegung aus dem Stundenplan: dort ist nur der klassen_key bekannt.
    // Erst unter den Klassen suchen, dann unter den Lerngruppen.
    if (vb.klassen_key) {
      const k = (daten.klassen || []).find(x => x.klassen_key === vb.klassen_key);
      if (k && k.lerngruppe_id) { ctx.ziel_typ = 'klasse'; ctx.ziel_id = k.id; }
      else {
        const g = (daten.lerngruppen || []).find(x => x.klassen_key === vb.klassen_key);
        if (g) { ctx.ziel_typ = 'lerngruppe'; ctx.ziel_id = g.id; }
      }
    }
    if (vb.lerngruppe_id) { ctx.ziel_typ = 'lerngruppe'; ctx.ziel_id = vb.lerngruppe_id; }

    DRS.wizard({
      title: 'Neue Prüfung',
      finishLabel: 'Prüfung anlegen',
      ctx: ctx,
      steps: [
        {
          key: 'grund', label: 'Grunddaten',
          render(c, body) {
            const t = el('input', { type: 'text', value: c.title,
              placeholder: 'z. B. Klassenarbeit Pneumatik' });
            t.addEventListener('input', () => { c.title = t.value; });
            const d = el('input', { type: 'date', value: c.datum });
            d.addEventListener('input', () => { c.datum = d.value; });
            body.appendChild(el('div', {}, [
              DRS.feld('Titel', t),
              DRS.feld('Datum', d, 'Wann wird die Prüfung geschrieben?'),
            ]));
          },
          validate(c) { return c.title.trim() ? null : 'Bitte einen Titel angeben.'; },
        },
        {
          key: 'ziel', label: 'Wer',
          render(c, body) {
            const wrap = el('div', {});
            wrap.appendChild(el('p', { class: 'muted' },
              'Die Prüfung gehört zu genau einer Klasse oder Lerngruppe. '
              + 'Ihre Schülerinnen und Schüler werden als Teilnehmer vorausgewählt.'));

            if (daten.klassen.length) {
              wrap.appendChild(el('div', { class: 'pick-group' }, 'Klassen'));
              daten.klassen.forEach(k => {
                const zeile = radioZeile('ziel', 'klasse:' + k.id, k.name,
                  k.lerngruppe_id
                    ? `${k.jahrgang} · ${k.anzahl} Schüler`
                    : 'keine Lerngruppe in den Stammdaten — nicht wählbar',
                  c.ziel_typ === 'klasse' && c.ziel_id === k.id);
                const rb = zeile.querySelector('input');
                if (!k.lerngruppe_id) { rb.disabled = true; zeile.classList.add('pick-off'); }
                rb.addEventListener('change', () => { c.ziel_typ = 'klasse'; c.ziel_id = k.id; });
                wrap.appendChild(zeile);
              });
            }
            if (daten.lerngruppen.length) {
              wrap.appendChild(el('div', { class: 'pick-group' }, 'Lerngruppen'));
              daten.lerngruppen.forEach(g => {
                const zeile = radioZeile('ziel', 'lg:' + g.id, g.name,
                  `${artLabel(g.art)} · ${g.anzahl} Schüler`,
                  c.ziel_typ === 'lerngruppe' && c.ziel_id === g.id);
                zeile.querySelector('input').addEventListener('change', () => {
                  c.ziel_typ = 'lerngruppe'; c.ziel_id = g.id;
                });
                wrap.appendChild(zeile);
              });
            }
            if (!daten.klassen.length && !daten.lerngruppen.length) {
              wrap.appendChild(el('p', { class: 'flash flash-warn', style: 'display:block' },
                'Es gibt noch keine Klassen. Leg sie zuerst in den Stammdaten an.'));
            }
            body.appendChild(wrap);
          },
          validate(c) { return c.ziel_id ? null : 'Bitte eine Klasse oder Lerngruppe wählen.'; },
        },
        {
          key: 'modus', label: 'Bewertung',
          render(c, body) {
            const wrap = el('div', {});
            wrap.appendChild(el('div', { class: 'pick-group' }, 'Womit wird bewertet?'));
            [['note', 'Schulnoten', 'Jeder Punkt bekommt eine Note; die Endnote ist der gewichtete Schnitt.'],
             ['punkte', 'Punkte', 'Erreichte von möglichen Punkten; die Note kommt aus dem Schlüssel.']]
              .forEach(([wert, titel, sub]) => {
                const z = radioZeile('bmode', wert, titel, sub, c.bewertung_mode === wert);
                z.querySelector('input').addEventListener('change', () => {
                  c.bewertung_mode = wert;
                  c.punkte.forEach(p => { p.eval_type = wert === 'note' ? 'note' : 'punkte'; });
                });
                wrap.appendChild(z);
              });

            const sel = el('select', {}, daten.skalen.map(s =>
              el('option', { value: s.ref }, s.label)));
            sel.value = c.grading_scale_key;
            sel.addEventListener('change', () => { c.grading_scale_key = sel.value; });
            wrap.appendChild(el('div', { style: 'margin-top:14px' },
              DRS.feld('Notenschlüssel', sel)));

            const stufen = el('input', { type: 'checkbox' });
            stufen.checked = c.input_mode === 'stages';
            stufen.addEventListener('change', () => {
              c.input_mode = stufen.checked ? 'stages' : 'numeric';
            });
            wrap.appendChild(el('label', { class: 'pick-row' }, [stufen,
              el('span', {}, [el('span', { class: 'pick-title' }, 'Stufen-Schnellauswahl'),
                el('span', { class: 'pick-sub' },
                  'Eingabe über Stufen statt Zahlen — praktisch am Handy.')])]));
            body.appendChild(wrap);
          },
        },
        {
          key: 'punkte', label: 'Feedbackpunkte',
          render(c, body) {
            body.appendChild(el('p', { class: 'muted' },
              'Woran wird bewertet? Das lässt sich später jederzeit ändern.'));
            punkteEditor(c, body);
          },
        },
      ],
      async onFinish(c) {
        const res = await DRS.postJSON('/api/exams', {
          title: c.title, datum: c.datum,
          ziel_typ: c.ziel_typ, ziel_id: c.ziel_id,
          bewertung_mode: c.bewertung_mode,
          input_mode: c.input_mode,
          grading_scale_key: c.grading_scale_key,
          lesson_note_id: c.lesson_note_id,
          feedback_points: c.punkte.filter(p => (p.name || '').trim()),
        });
        location.href = res.url;
      },
    });
  };

  // ---------- Fragedialog: Namen Schülern zuordnen ----------

  /* Ein Baustein für drei Wege: neue Prüfung aus einem Moodle-Test, Ergebnisse
   * in eine bestehende Prüfung und das Aufräumen der Doppelten aus dem alten
   * Import. Eindeutiges ordnet der Server still zu (`sicher`); gefragt wird
   * nur, was unklar ist — eine Karte je Fall. Treffer aus der anderen
   * Teilgruppe kommen gesammelt in EINE Frage statt in zehn einzelne.
   * Ein Klick auf eine Antwort springt weiter, „Zurück" korrigiert.
   * Geschrieben wird erst am Ende über `opts.onFertig(zeilen)` — ein Abbruch
   * hinterlässt nichts.
   *
   * plan: Antwort von _zuordnungs_plan (zeilen, schueler, klassen, lerngruppe).
   * opts: titel, verb, anlegenLabel, mitProzent, extra (Node für die
   *       Zusammenfassung), onFertig(zeilen) → Promise.
   */
  EX.fragedialog = function (plan, opts) {
    opts = opts || {};
    const zeilen = plan.zeilen;
    const personen = new Map((plan.schueler || []).map((s) => [s.id, s]));
    const klassen = plan.klassen || [];
    const lgName = plan.lerngruppe ? plan.lerngruppe.name : 'der Lerngruppe';

    zeilen.forEach((z) => {
      z.aufnehmen = false;      // nur für 'teilgruppe'
      z.wahl = null;            // {id} | {neu: klassenId} | {skip: true}
    });

    const teilgruppe = zeilen.filter((z) => z.status === 'teilgruppe');
    const fragen = zeilen.filter((z) => z.status === 'frage' || z.status === 'keiner');
    const schritte = [];
    if (teilgruppe.length) schritte.push({ art: 'teilgruppe' });
    fragen.forEach((z) => schritte.push({ art: 'frage', zeile: z }));
    schritte.push({ art: 'ende' });
    let pos = 0;

    const nameAus = (z) => (z.nachname || '') + (z.vorname ? ', ' + z.vorname : '');
    const prozentText = (z) => (opts.mitProzent && z.percent !== null && z.percent !== undefined)
      ? String(z.percent).replace('.', ',') + ' %' : '';

    function gewaehlteId(z) {
      if (z.status === 'sicher') return z.student_id;
      if (z.status === 'teilgruppe') return z.aufnehmen ? z.student_id : null;
      return z.wahl && z.wahl.id ? z.wahl.id : null;
    }
    // Wer ist schon vergeben — außer an die Zeile, um die es gerade geht?
    function vergebenAn(id, ausser) {
      return zeilen.find((z) => z !== ausser && gewaehlteId(z) === id) || null;
    }

    function personKnopf(z, id, vorschlag) {
      const p = personen.get(id) || { name: '?', klasse: '' };
      const belegt = vergebenAn(id, z);
      const aktiv = z.wahl && z.wahl.id === id;
      const knopf = el('button', {
        type: 'button',
        class: 'fz-opt' + (aktiv ? ' fz-aktiv' : ''),
        disabled: belegt ? true : null,
        onClick: () => { z.wahl = { id }; weiter(); },
      }, [
        el('span', { class: 'fz-opt-name' }, p.name),
        el('span', { class: 'fz-opt-sub' }, [
          p.klasse || '',
          vorschlag ? el('span', { class: 'fz-badge' }, 'Vorschlag') : null,
          belegt ? ' · schon für „' + nameAus(belegt) + '"' : null,
        ]),
      ]);
      return knopf;
    }

    function suche(z) {
      const feld = el('input', { type: 'text', placeholder: 'Anderen Schüler suchen …' });
      const treffer = el('div', { class: 'fz-suche-treffer' });
      feld.addEventListener('input', () => {
        treffer.textContent = '';
        const q = feld.value.trim().toLowerCase();
        if (q.length < 2) return;
        (plan.schueler || [])
          .filter((s) => (s.name + ' ' + s.klasse).toLowerCase().includes(q)
                      && !(z.optionen || []).includes(s.id))
          .slice(0, 8)
          .forEach((s) => treffer.appendChild(personKnopf(z, s.id, false)));
        if (!treffer.childNodes.length) {
          treffer.appendChild(el('div', { class: 'muted' }, 'Niemand gefunden.'));
        }
      });
      return el('div', { class: 'fz-suche' }, [feld, treffer]);
    }

    function anlegen(z) {
      if (!klassen.length) return null;
      const sel = el('select', {}, klassen.map((k) =>
        el('option', { value: String(k.id) }, k.name)));
      if (z.wahl && z.wahl.neu) sel.value = String(z.wahl.neu);
      const knopf = el('button', {
        type: 'button', class: 'btn-sec',
        onClick: () => { z.wahl = { neu: parseInt(sel.value, 10) }; weiter(); },
      }, opts.anlegenLabel || 'Als neuen Schüler anlegen');
      return el('div', { class: 'fz-anlegen' }, [
        el('div', { class: 'fz-frage' }, 'Fehlt in den Stammdaten?'),
        el('div', { class: 'fz-anlegen-zeile' },
          klassen.length > 1 ? [sel, knopf] : [knopf]),
      ]);
    }

    function kopf(text) {
      const nr = schritte.filter((s) => s.art !== 'ende').length;
      return el('div', { class: 'fz-kopf' }, [
        el('span', {}, text),
        nr ? el('span', { class: 'muted' }, 'Schritt ' + Math.min(pos + 1, nr) + ' von ' + nr) : null,
      ]);
    }

    function navigation(extra) {
      return el('div', { class: 'fz-nav' }, [
        pos > 0 ? el('button', { type: 'button', class: 'btn-ghost', onClick: () => { pos--; zeichne(); } }, '← Zurück') : el('span'),
        extra || null,
      ]);
    }

    function schrittTeilgruppe() {
      const liste = el('div', { class: 'fz-liste' }, teilgruppe.map((z) => {
        const cb = el('input', { type: 'checkbox' });
        cb.checked = z.aufnehmen;
        cb.addEventListener('change', () => { z.aufnehmen = cb.checked; });
        const p = personen.get(z.student_id) || {};
        return el('label', { class: 'fz-check' }, [
          cb,
          el('span', {}, [el('strong', {}, p.name || nameAus(z)), ' ',
            el('span', { class: 'muted' }, p.klasse || '')]),
          el('span', { class: 'fz-proz' }, prozentText(z)),
        ]);
      }));
      const alle = el('button', { type: 'button', class: 'btn-ghost btn-sm', onClick: () => {
        const an = !teilgruppe.every((z) => z.aufnehmen);
        teilgruppe.forEach((z) => { z.aufnehmen = an; });
        zeichne();
      } }, teilgruppe.every((z) => z.aufnehmen) ? 'Alle abwählen' : 'Alle anhaken');
      return [
        kopf('Andere Teilgruppe'),
        el('p', {}, teilgruppe.length + (teilgruppe.length === 1 ? ' Name gehört' : ' Namen gehören')
          + ' zur Klasse, aber nicht zu „' + lgName + '". Wer soll trotzdem in diese Prüfung?'),
        el('p', { class: 'muted' }, 'Nicht Angehakte werden ignoriert — es entsteht dabei nichts Neues.'),
        alle,
        liste,
        navigation(el('button', { type: 'button', class: 'btn', onClick: weiter }, 'Weiter →')),
      ];
    }

    function schrittFrage(z) {
      const optionen = (z.optionen || []).map((id) =>
        personKnopf(z, id, z.student_id === id));
      return [
        kopf(z.status === 'keiner' ? 'Kein Treffer' : 'Wer ist gemeint?'),
        el('div', { class: 'fz-karte' }, [
          el('div', { class: 'fz-name' }, nameAus(z)),
          prozentText(z) ? el('div', { class: 'fz-proz' }, prozentText(z)) : null,
          z.hinweis ? el('div', { class: 'muted' }, z.hinweis) : null,
        ]),
        optionen.length ? el('div', { class: 'fz-optionen' }, optionen) : null,
        suche(z),
        z.status === 'keiner' ? anlegen(z) : null,
        navigation(el('button', { type: 'button', class: 'btn-sec',
          onClick: () => { z.wahl = { skip: true }; weiter(); } }, 'Überspringen')),
      ];
    }

    function schrittEnde() {
      const sicher = zeilen.filter((z) => z.status === 'sicher');
      const tg = teilgruppe.filter((z) => z.aufnehmen);
      const gefragt = fragen.filter((z) => z.wahl && z.wahl.id);
      const neu = fragen.filter((z) => z.wahl && z.wahl.neu);
      const ohne = zeilen.filter((z) => gewaehlteId(z) === null && !(z.wahl && z.wahl.neu));

      const zeile = (n, text) => n ? el('li', {}, [el('strong', {}, String(n)), ' ' + text]) : null;
      const zuordnungsListe = (liste) => el('ul', { class: 'fz-mini' }, liste.map((z) => {
        const id = gewaehlteId(z);
        return el('li', {}, [nameAus(z),
          id ? ' → ' + ((personen.get(id) || {}).name || '?') : null,
          prozentText(z) ? el('span', { class: 'muted' }, ' · ' + prozentText(z)) : null]);
      }));
      const details = (titel, liste) => liste.length
        ? el('details', { class: 'fz-details' }, [el('summary', {}, titel), zuordnungsListe(liste)])
        : null;

      return [
        kopf('Zusammenfassung'),
        el('ul', { class: 'fz-summe' }, [
          zeile(sicher.length, 'eindeutig zugeordnet'),
          zeile(tg.length, 'aus der anderen Teilgruppe aufgenommen'),
          zeile(gefragt.length, 'per Frage zugeordnet'),
          zeile(neu.length, (opts.anlegenLabel ? 'in die Klasse aufgenommen' : 'werden neu angelegt')),
          zeile(ohne.length, 'bleiben unberücksichtigt'),
        ]),
        details('Eindeutige Zuordnungen ansehen', sicher),
        details('Unberücksichtigt ansehen', ohne),
        opts.extra || null,
        navigation(el('button', { type: 'button', class: 'btn', onClick: fertig },
          opts.verb || 'Übernehmen')),
      ];
    }

    const body = el('div', { class: 'fz' });
    function zeichne() {
      body.textContent = '';
      const s = schritte[pos];
      const teile = s.art === 'teilgruppe' ? schrittTeilgruppe()
        : (s.art === 'frage' ? schrittFrage(s.zeile) : schrittEnde());
      teile.forEach((t) => { if (t) body.appendChild(t); });
      const f = body.querySelector('.fz-optionen button:not([disabled]), .fz-suche input');
      if (f && s.art === 'frage') f.focus();
    }
    function weiter() { if (pos < schritte.length - 1) pos++; zeichne(); }

    let laeuft = false;
    async function fertig() {
      if (laeuft) return;
      laeuft = true;
      const ergebnis = zeilen.map((z) => Object.assign({}, z, {
        student_id: gewaehlteId(z),
        neu_klasse_id: z.wahl && z.wahl.neu ? z.wahl.neu : null,
      }));
      try {
        await opts.onFertig(ergebnis);
        dlg.close();
      } catch (e) {
        DRS.toast(e.message || 'Speichern fehlgeschlagen.');
      } finally { laeuft = false; }
    }

    const dlg = DRS.modal({
      title: opts.titel || 'Namen zuordnen',
      body,
      actions: [{ label: 'Abbrechen', kind: 'sec', onClick: (c) => c() }],
    });
    zeichne();
    return dlg;
  };

  // ---------- Moodle-Test importieren ----------

  /* Neue Prüfung aus einer Moodle-JSON. Erst Grunddaten + Klasse/Lerngruppe +
   * Datei, dann der Fragedialog; die Prüfung entsteht erst, wenn er durch ist.
   * Die Klassen müssen VOR dem Öffnen geladen sein — sonst bliebe die Auswahl
   * leer (dieselbe Falle wie beim Lerngruppen-Assistenten). */
  EX.moodleImport = async function () {
    let daten;
    try {
      daten = await DRS.getJSON('/api/exams/pickers');
    } catch (e) {
      DRS.toast('Klassen konnten nicht geladen werden.');
      return;
    }
    const titel = el('input', { type: 'text', placeholder: 'z. B. Moodle-Test Pneumatik' });
    const datum = el('input', { type: 'date', value: daten.heute || new Date().toISOString().slice(0, 10) });
    const datei = el('input', { type: 'file', accept: '.json,application/json' });
    const ziel = el('select', {}, [el('option', { value: '' }, 'Bitte wählen …')]);
    if (daten.klassen.length) {
      ziel.appendChild(el('optgroup', { label: 'Klassen' }, daten.klassen.map((k) =>
        el('option', { value: 'klasse:' + k.id, disabled: k.lerngruppe_id ? null : true },
          k.name + (k.lerngruppe_id ? ' · ' + k.anzahl + ' Schüler' : ' · keine Lerngruppe')))));
    }
    if (daten.lerngruppen.length) {
      ziel.appendChild(el('optgroup', { label: 'Lerngruppen' }, daten.lerngruppen.map((g) =>
        el('option', { value: 'lerngruppe:' + g.id },
          g.name + ' · ' + artLabel(g.art) + ' · ' + g.anzahl + ' Schüler'))));
    }

    const body = el('div', {}, [
      el('p', { class: 'muted' },
        'Die Namen aus der Datei werden den Schülern der gewählten Klasse oder '
        + 'Lerngruppe zugeordnet — es entstehen keine doppelten Schüler. Was '
        + 'unklar ist, fragt der nächste Schritt ab. Bewertet wird über einen '
        + 'Punkt „Gesamtbewertung" mit dem Moodle-Prozentwert.'),
      DRS.feld('Titel', titel),
      DRS.feld('Datum', datum),
      DRS.feld('Klasse oder Lerngruppe', ziel),
      DRS.feld('Moodle-JSON', datei),
    ]);

    let laeuft = false;
    DRS.modal({
      title: '⬆ Moodle-Test importieren',
      body,
      actions: [
        {
          label: 'Weiter →', kind: 'primary', onClick: async (close) => {
            if (laeuft) return;
            if (!ziel.value) { DRS.toast('Bitte eine Klasse oder Lerngruppe wählen.'); return; }
            if (!datei.files.length) { DRS.toast('Bitte eine Datei wählen.'); return; }
            const [zielTyp, zielId] = ziel.value.split(':');
            const fd = new FormData();
            fd.append('datei', datei.files[0]);
            fd.append('ziel_typ', zielTyp);
            fd.append('ziel_id', zielId);
            laeuft = true;
            let plan;
            try {
              const r = await fetch('/api/exams/moodle/vorschau', { method: 'POST', body: fd });
              plan = await r.json();
              if (!r.ok) throw new Error(plan.detail || 'Datei nicht lesbar');
            } catch (e) {
              DRS.toast(e.message || 'Datei konnte nicht gelesen werden.');
              return;
            } finally { laeuft = false; }
            close();
            const grund = { titel: titel.value.trim(), datum: datum.value,
                            ziel_typ: zielTyp, ziel_id: parseInt(zielId, 10) };
            EX.fragedialog(plan, {
              titel: '⬆ ' + (grund.titel || 'Moodle-Test') + ' — Namen zuordnen',
              verb: 'Prüfung anlegen',
              mitProzent: true,
              extra: plan.ohne_ergebnis
                ? el('p', { class: 'muted' }, plan.ohne_ergebnis === 1
                    ? '1 Zeile der Datei hat kein Ergebnis und bekommt keine Bewertung.'
                    : plan.ohne_ergebnis + ' Zeilen der Datei haben kein Ergebnis und bekommen keine Bewertung.')
                : null,
              async onFertig(zeilen) {
                const d = await DRS.postJSON('/api/exams/moodle', Object.assign({}, grund, {
                  zeilen: zeilen.map((z) => ({
                    nachname: z.nachname, vorname: z.vorname, percent: z.percent,
                    student_id: z.student_id, neu_klasse_id: z.neu_klasse_id,
                  })),
                }));
                location.href = d.url;
              },
            });
          },
        },
        { label: 'Abbrechen', kind: 'sec', onClick: (c) => c() },
      ],
    });
  };

  // ---------- Moodle-Ergebnisse in eine bestehende Prüfung ----------

  /* Die Prüfung steht schon und hängt an einer Lerngruppe — importiert werden
   * nur die ERGEBNISSE. Gleicher Fragedialog wie beim Anlegen; das Ziel
   * (welcher Feedbackpunkt) wird in der Zusammenfassung gewählt. */
  EX.moodleErgebnisse = function (examId) {
    const datei = el('input', { type: 'file', accept: '.json,application/json' });
    let laeuft = false;

    function zielAuswahl(plan) {
      // Nur Punkte-Feedbackpunkte je Schüler können einen Prozentwert aufnehmen —
      // für Schulnote, Stufen oder Gruppenpunkte gäbe es keine ehrliche Umrechnung.
      const passend = (plan.feedback_points || []).filter(
        (f) => f.eval_type === 'punkte' && f.scope !== 'group' && f.max_points > 0);
      const wahl = el('select', {}, [el('option', { value: '' }, 'Neuen Feedbackpunkt anlegen')]
        .concat(passend.map((f) => el('option', { value: String(f.id) },
          f.name + ' (max ' + f.max_points + ')'))));
      const name = el('input', { type: 'text', value: 'Moodle-Test' });
      const neuFeld = DRS.feld('Name des neuen Punktes', name,
        'Bekommt 100 Punkte — der Moodle-Prozentwert steht dann unverändert drin.');
      wahl.addEventListener('change', () => { neuFeld.style.display = wahl.value ? 'none' : ''; });
      // Schon ein Moodle-Punkt da (z. B. Teil der anderen Teilgruppe)? Dann
      // dorthin — ein zweiter gleichnamiger Punkt stünde doppelt im PDF.
      if (plan.vorschlag_fp_id && passend.some((f) => f.id === plan.vorschlag_fp_id)) {
        wahl.value = String(plan.vorschlag_fp_id);
        neuFeld.style.display = 'none';
      }
      const box = el('div', { class: 'fz-ziel' }, [
        DRS.feld('Ergebnisse buchen auf', wahl, passend.length
          ? 'Bei einem vorhandenen Punkt wird der Prozentwert auf dessen Maximalpunkte '
            + 'umgerechnet. Schüler ohne Prozentwert in dieser Datei behalten ihren Wert.'
          : 'Diese Prüfung hat noch keinen passenden Punkte-Feedbackpunkt.'),
        neuFeld,
      ]);
      return { box, wahl, name };
    }

    DRS.modal({
      title: '⬆ Moodle-Ergebnisse übernehmen',
      body: el('div', {}, [
        el('p', { class: 'muted' },
          'Die Namen aus der Datei werden den Schülern dieser Prüfung zugeordnet — '
          + 'es entstehen keine doppelten Schüler. Was unklar ist, fragt der '
          + 'nächste Schritt ab.'),
        DRS.feld('Moodle-JSON', datei),
      ]),
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: (c) => c() },
        {
          label: 'Weiter →', kind: 'primary', onClick: async (close) => {
            if (laeuft) return;
            if (!datei.files.length) { DRS.toast('Bitte eine Datei wählen.'); return; }
            const fd = new FormData();
            fd.append('datei', datei.files[0]);
            laeuft = true;
            let plan;
            try {
              const r = await fetch('/api/exams/' + examId + '/moodle/vorschau',
                { method: 'POST', body: fd });
              plan = await r.json();
              if (!r.ok) throw new Error(plan.detail || 'Datei nicht lesbar');
            } catch (e) {
              DRS.toast(e.message || 'Datei konnte nicht gelesen werden.');
              return;
            } finally { laeuft = false; }
            close();
            const ziel = zielAuswahl(plan);
            EX.fragedialog(plan, {
              titel: '⬆ Moodle-Ergebnisse — Namen zuordnen',
              verb: 'Ergebnisse übernehmen',
              mitProzent: true,
              extra: ziel.box,
              async onFertig(zeilen) {
                const zuordnung = zeilen
                  .filter((z) => (z.student_id || z.neu_klasse_id)
                                 && z.percent !== null && z.percent !== undefined)
                  .map((z) => ({ student_id: z.student_id, neu_klasse_id: z.neu_klasse_id,
                                 percent: z.percent, nachname: z.nachname, vorname: z.vorname }));
                if (!zuordnung.length) throw new Error('Keine Zeile hat Schüler und Ergebnis.');
                const d = await DRS.postJSON('/api/exams/' + examId + '/moodle/import', {
                  zuordnung,
                  fp_id: ziel.wahl.value ? parseInt(ziel.wahl.value, 10) : null,
                  fp_name: ziel.name.value.trim(),
                });
                DRS.toast(d.gebucht + ' Ergebnisse übernommen — lade neu …');
                setTimeout(() => location.reload(), 700);
              },
            });
          },
        },
      ],
    });
  };

  // ---------- Doppelte aus dem alten Moodle-Import zusammenführen ----------

  EX.gaesteAufraeumen = async function (examId) {
    let plan;
    try {
      // nicht DRS.getJSON: das verschluckt die Begründung des Servers
      const r = await fetch('/api/exams/' + examId + '/gaeste');
      plan = await r.json();
      if (!r.ok) throw new Error(plan.detail || 'Serverfehler');
    } catch (e) {
      DRS.toast(e.message || 'Konnte nicht geladen werden.');
      return;
    }
    if (!plan.zeilen.length) { DRS.toast('Keine Doppelten mehr in dieser Prüfung.'); return; }
    EX.fragedialog(plan, {
      titel: '🧹 Doppelte Schüler zusammenführen',
      verb: 'Zusammenführen',
      anlegenLabel: 'In die Klasse aufnehmen',
      extra: el('p', { class: 'muted' },
        'Bewertungen der Doppelten wandern auf den echten Schüler. Hat der schon '
        + 'Werte, bleiben seine stehen. Leere Doppelte werden danach gelöscht.'),
      async onFertig(zeilen) {
        const d = await DRS.postJSON('/api/exams/' + examId + '/gaeste/zusammenfuehren', {
          zeilen: zeilen.map((z) => ({ gast_id: z.gast_id, student_id: z.student_id,
                                       neu_klasse_id: z.neu_klasse_id })),
        });
        DRS.toast(d.zusammengefuehrt + ' zusammengeführt'
          + (d.eingeordnet ? ', ' + d.eingeordnet + ' in die Klasse aufgenommen' : '')
          + ' — lade neu …');
        setTimeout(() => { location.href = location.pathname; }, 700);
      },
    });
  };

  // ---------- Gesamt-PDF ----------

  /* Holt das PDF per fetch statt über einen nackten Link: So lässt sich
   * melden, wer mangels Bewertung fehlt, und der Knopf zeigt, dass gerade
   * gerendert wird (je Schüler ein Chromium-Durchlauf, das dauert). */
  EX.gesamtPdf = async function (examId, duplex, knopf) {
    const vorher = knopf ? knopf.textContent : '';
    if (knopf) { knopf.disabled = true; knopf.textContent = 'PDF wird erstellt …'; }
    try {
      const r = await fetch('/exams/' + examId + '/export.pdf?duplex=' + (duplex ? 1 : 0));
      if (!r.ok) {
        let msg = 'PDF konnte nicht erstellt werden.';
        try { msg = (await r.json()).detail || msg; } catch (e) { /* kein JSON */ }
        throw new Error(msg);
      }
      const blob = await r.blob();
      const cd = r.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename="([^"]+)"/);
      const a = el('a', { href: URL.createObjectURL(blob),
                          download: m ? decodeURIComponent(m[1]) : 'pruefung.pdf' });
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      const ohne = decodeURIComponent(r.headers.get('X-Ohne-Bewertung') || '');
      const fehler = decodeURIComponent(r.headers.get('X-Fehler') || '');
      if (fehler) DRS.toast('Nicht erzeugt: ' + fehler, 8000);
      else if (ohne) DRS.toast('Ohne Bewertung, daher nicht enthalten: ' + ohne, 8000);
    } catch (e) {
      DRS.toast(e.message || 'PDF konnte nicht erstellt werden.');
    } finally {
      if (knopf) { knopf.disabled = false; knopf.textContent = vorher; }
    }
  };

  // ---------- Zuordnung ändern ----------

  EX.zuordnungModal = async function (examId) {
    let daten;
    try {
      daten = await DRS.getJSON('/api/exams/pickers');
    } catch (e) {
      DRS.toast('Klassen konnten nicht geladen werden.');
      return;
    }
    let ziel = { typ: '', id: null };

    const wrap = el('div', {});
    wrap.appendChild(el('p', { class: 'muted' },
      'Die Prüfung gehört zu genau einer Klasse oder Lerngruppe. Beim Wechsel '
      + 'werden deren Schüler als Teilnehmer ergänzt; bereits erfasste '
      + 'Teilnehmer und ihre Bewertungen bleiben erhalten.'));

    if (daten.klassen.length) {
      wrap.appendChild(el('div', { class: 'pick-group' }, 'Klassen'));
      daten.klassen.forEach(k => {
        const z = radioZeile('zuord', 'k' + k.id, k.name,
          k.lerngruppe_id ? `${k.jahrgang} · ${k.anzahl} Schüler`
                          : 'keine Lerngruppe in den Stammdaten — nicht wählbar',
          false);
        const rb = z.querySelector('input');
        if (!k.lerngruppe_id) { rb.disabled = true; z.classList.add('pick-off'); }
        rb.addEventListener('change', () => { ziel = { typ: 'klasse', id: k.id }; });
        wrap.appendChild(z);
      });
    }
    if (daten.lerngruppen.length) {
      wrap.appendChild(el('div', { class: 'pick-group' }, 'Lerngruppen'));
      daten.lerngruppen.forEach(g => {
        const z = radioZeile('zuord', 'g' + g.id, g.name,
          `${artLabel(g.art)} · ${g.anzahl} Schüler`, false);
        z.querySelector('input').addEventListener('change', () => {
          ziel = { typ: 'lerngruppe', id: g.id };
        });
        wrap.appendChild(z);
      });
    }

    DRS.modal({
      title: '🎓 Zuordnung ändern',
      body: wrap,
      actions: [
        {
          label: 'Übernehmen', kind: 'primary', onClick: async (close) => {
            if (!ziel.id) { DRS.toast('Bitte eine Klasse oder Lerngruppe wählen.'); return; }
            // Eine Klasse löst der Server auf ihre 1:1-Lerngruppe auf.
            let lgId = ziel.id;
            if (ziel.typ === 'klasse') {
              const k = daten.klassen.find(x => x.id === ziel.id);
              lgId = k && k.lerngruppe_id;
            }
            if (!lgId) { DRS.toast('Zu dieser Klasse fehlt die Lerngruppe.'); return; }
            try {
              await DRS.postJSON(`/exams/${examId}/save`,
                { tab: 'einstellungen', lerngruppe_id: lgId });
              close();
              // Stecken noch Doppelte aus dem alten Moodle-Import drin, öffnet
              // die Seite nach dem Laden direkt das Zusammenführen.
              location.href = location.pathname + '?aufraeumen=1';
            } catch (e) { DRS.toast(e.message || 'Konnte nicht speichern.'); }
          },
        },
        { label: 'Abbrechen', kind: 'sec', onClick: (c) => c() },
      ],
    });
  };

  // ---------- Löschen mit Auswirkungen ----------

  EX.loeschen = function (id, titel, fakten, danach) {
    DRS.confirmDanger({
      title: 'Prüfung löschen?',
      text: `„${titel}" wird endgültig entfernt.`,
      facts: fakten || [],
      warnung: 'Alle Bewertungen und Teilnehmer dieser Prüfung gehen verloren. '
             + 'Das lässt sich nicht rückgängig machen.',
      danger: 'Endgültig löschen',
      async onDanger(close) {
        try {
          await DRS.postJSON(`/api/exams/${id}/delete`, {});
          close();
          if (danach) location.href = danach; else location.reload();
        } catch (e) { DRS.toast(e.message || 'Löschen fehlgeschlagen.'); }
      },
    });
  };
})();
