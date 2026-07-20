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

  // ---------- Moodle-Test importieren ----------

  EX.moodleImport = function () {
    const titel = el('input', { type: 'text', placeholder: 'z. B. Moodle-Test Pneumatik' });
    const datum = el('input', { type: 'date', value: new Date().toISOString().slice(0, 10) });
    const datei = el('input', { type: 'file', accept: '.json,application/json' });
    const info = el('div', { class: 'moodle-info muted' },
      'Wähle die aus Moodle exportierte JSON-Datei.');
    let geprueft = null;

    // Erst Vorschau holen — es wird nichts geschrieben, bevor du sie gesehen hast.
    datei.addEventListener('change', async () => {
      geprueft = null;
      if (!datei.files.length) { info.textContent = 'Keine Datei gewählt.'; return; }
      info.textContent = 'lese Datei …';
      const fd = new FormData();
      fd.append('datei', datei.files[0]);
      try {
        const r = await fetch('/api/exams/moodle/vorschau', { method: 'POST', body: fd });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || 'Datei nicht lesbar');
        geprueft = d;
        info.innerHTML = '';
        info.appendChild(el('strong', {}, `${d.anzahl} Schüler gefunden`));
        if (d.abteilungen.length) {
          info.appendChild(el('div', {}, 'Abteilungen: ' + d.abteilungen.join(', ')));
        }
        if (d.ohne_ergebnis) {
          info.appendChild(el('div', {}, `${d.ohne_ergebnis} davon ohne Ergebnis`));
        }
        info.appendChild(el('div', { class: 'muted' },
          d.namen.join(' · ') + (d.anzahl > d.namen.length ? ' …' : '')));
      } catch (e) {
        info.textContent = e.message || 'Datei konnte nicht gelesen werden.';
      }
    });

    const body = el('div', {}, [
      el('p', { class: 'muted' },
        'Die Teilnehmer kommen aus der Datei, nicht aus einer Klasse — eine '
        + 'Zuordnung zu einer Lerngruppe gibt es hier deshalb nicht. Bewertet '
        + 'wird über einen Punkt „Gesamtbewertung" mit dem Moodle-Prozentwert.'),
      DRS.feld('Titel', titel),
      DRS.feld('Datum', datum),
      DRS.feld('Moodle-JSON', datei),
      info,
    ]);

    DRS.modal({
      title: '⬆ Moodle-Test importieren',
      body,
      actions: [
        {
          label: 'Importieren', kind: 'primary', onClick: async (close) => {
            if (!datei.files.length) { DRS.toast('Bitte eine Datei wählen.'); return; }
            if (!geprueft) { DRS.toast('Die Datei wird noch geprüft.'); return; }
            const fd = new FormData();
            fd.append('titel', titel.value.trim());
            fd.append('datum', datum.value);
            fd.append('datei', datei.files[0]);
            try {
              const r = await fetch('/api/exams/moodle', { method: 'POST', body: fd });
              const d = await r.json();
              if (!r.ok) throw new Error(d.detail || 'Import fehlgeschlagen');
              close();
              location.href = d.url;
            } catch (e) { DRS.toast(e.message || 'Import fehlgeschlagen.'); }
          },
        },
        { label: 'Abbrechen', kind: 'sec', onClick: (c) => c() },
      ],
    });
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
              location.reload();
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
