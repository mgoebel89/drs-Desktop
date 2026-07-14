/* Assistenten und Detail-Modals der Stammdaten.
 *
 * Der Jahrgangs-Assistent sammelt Name, Klassen und Lernfelder und schickt sie
 * am Ende in EINEM Request an /api/stammdaten/jahrgang. Bricht der Lehrer ab,
 * bleibt nichts Halbes zurück.
 *
 * Der Stundenplan-Schlüssel (klassen_key) steckt bewusst hinter „Erweitert":
 * Für eine neue Klasse ist er egal — es hängen ja noch keine Notizen dran, und
 * der Name taugt als Schlüssel. Wer eine Bestandsklasse aus Untis nachbaut, muss
 * ihn dagegen exakt treffen, sonst findet die Klasse ihre alten Notizen nicht.
 */
(function () {
  'use strict';
  const { el, feld, erweitert, wizard, modal, confirmDanger, toast, postJSON, getJSON } = DRS;

  // "BSMT 26" -> ["BSMT 26 a", "BSMT 26 b"]; Züge sind an der DRS üblich.
  function klassenVorschlag(jahrgang) {
    const n = (jahrgang || '').trim();
    if (!n) return [];
    return ['a', 'b'].map((zug) => ({ name: `${n} ${zug}`, kuerzel: '', klassen_key: '' }));
  }

  // ---------- Assistent: Neuer Jahrgang ----------

  function jahrgangWizard() {
    const ctx = { name: '', kuerzel: '', klassen: [], faecher: [], katalog: [] };

    getJSON('/api/stammdaten/katalog')
      .then((k) => { ctx.katalog = k.faecher; })
      .catch(() => { /* Katalog ist nicht kritisch — Schritt 3 zeigt dann nur "neu" */ });

    wizard({
      title: 'Neuer Jahrgang',
      finishLabel: 'Jahrgang anlegen',
      ctx,
      steps: [
        {
          key: 'name',
          label: 'Name',
          render(c, body) {
            const name = el('input', {
              value: c.name, placeholder: 'BSMT 26', autofocus: true,
              onInput: (e) => { c.name = e.target.value; },
            });
            const kuerzel = el('input', {
              value: c.kuerzel, placeholder: 'MT26',
              onInput: (e) => { c.kuerzel = e.target.value; },
            });
            body.appendChild(feld('Wie heißt der Jahrgang?', name,
              'So, wie du ihn im Alltag nennst.'));
            body.appendChild(feld('Kürzel (optional)', kuerzel));
          },
          validate(c) {
            if (!c.name.trim()) return 'Der Jahrgang braucht einen Namen.';
            // Klassenvorschlag erst hier bilden — der Name steht ja jetzt fest.
            if (!c.klassen.length) c.klassen = klassenVorschlag(c.name);
            return null;
          },
        },
        {
          key: 'klassen',
          label: 'Klassen',
          render(c, body) {
            body.appendChild(el('p', {}, [
              'Welche Klassen hat ', el('strong', {}, c.name.trim()), '?',
            ]));
            body.appendChild(el('p', { class: 'muted' },
              'Für jede Klasse entsteht automatisch die passende Lerngruppe im Stundenplan.'));

            const liste = el('div', { style: 'margin:14px 0' });
            body.appendChild(liste);

            function zeichne() {
              liste.innerHTML = '';
              c.klassen.forEach((k, i) => {
                const name = el('input', {
                  value: k.name, placeholder: 'BSMT 26 a',
                  onInput: (e) => { k.name = e.target.value; },
                });
                const key = el('input', {
                  value: k.klassen_key, placeholder: k.name || 'wie der Name',
                  onInput: (e) => { k.klassen_key = e.target.value; },
                });
                liste.appendChild(el('div', { class: 'card', style: 'padding:12px;margin-bottom:10px' }, [
                  el('div', { style: 'display:flex;gap:8px;align-items:flex-end' }, [
                    el('div', { style: 'flex:1' }, feld('Klasse', name)),
                    el('button', {
                      class: 'btn-sec', type: 'button', title: 'Klasse entfernen',
                      style: 'color:var(--pink);border-color:var(--pink);margin-bottom:14px',
                      onClick: () => { c.klassen.splice(i, 1); zeichne(); },
                    }, '✕'),
                  ]),
                  erweitert(feld('Stundenplan-Schlüssel', key,
                    'Leer lassen = der Name wird verwendet. Nur ändern, wenn die Klasse aus '
                    + 'Untis übernommen wird — dann muss der Schlüssel exakt stimmen, sonst '
                    + 'finden die alten Stundennotizen ihre Klasse nicht. Später nicht mehr änderbar.')),
                ]));
              });
              liste.appendChild(el('button', {
                class: 'chip-add', type: 'button',
                onClick: () => {
                  c.klassen.push({ name: '', kuerzel: '', klassen_key: '' });
                  zeichne();
                },
              }, '+ Klasse'));
            }
            zeichne();
          },
          validate(c) {
            const namen = c.klassen.map((k) => k.name.trim()).filter(Boolean);
            if (!namen.length) return 'Lege mindestens eine Klasse an.';
            if (new Set(namen).size !== namen.length) return 'Zwei Klassen heißen gleich.';
            c.klassen = c.klassen.filter((k) => k.name.trim());
            return null;
          },
        },
        {
          key: 'faecher',
          label: 'Lernfelder',
          render(c, body) {
            body.appendChild(el('p', {}, 'Welche Lernfelder gelten in diesem Jahrgang?'));
            body.appendChild(el('p', { class: 'muted' },
              'Nur diese stehen später im Stundenplan zur Auswahl, wenn eine Lerngruppe '
              + 'dieses Jahrgangs eingetragen wird.'));

            const liste = el('div', { style: 'margin:14px 0' });
            body.appendChild(liste);

            function zeichne() {
              liste.innerHTML = '';

              c.faecher.forEach((f, i) => {
                const std = el('input', {
                  type: 'number', min: '0', value: f.stundenansatz, style: 'max-width:90px',
                  onInput: (e) => { f.stundenansatz = Number(e.target.value) || 0; },
                });
                liste.appendChild(el('div', {
                  class: 'card', style: 'padding:10px 12px;margin-bottom:8px;display:flex;'
                    + 'align-items:center;gap:10px;flex-wrap:wrap',
                }, [
                  el('strong', { style: 'flex:1' }, f.label),
                  el('label', { class: 'sd-check' }, [el('span', { class: 'muted' }, 'Stunden'), std]),
                  el('button', {
                    class: 'btn-sec', type: 'button',
                    style: 'color:var(--pink);border-color:var(--pink)',
                    onClick: () => { c.faecher.splice(i, 1); zeichne(); },
                  }, '✕'),
                ]));
              });

              const gewaehlt = new Set(c.faecher.map((f) => f.fach_id).filter(Boolean));
              const offen = c.katalog.filter((f) => !gewaehlt.has(f.id));

              if (offen.length) {
                const sel = el('select', { style: 'max-width:280px' },
                  offen.map((f) => el('option', { value: String(f.id) }, `${f.name} (${f.key})`)));
                liste.appendChild(el('div', { class: 'sd-inline', style: 'margin-top:10px' }, [
                  sel,
                  el('button', {
                    class: 'btn-sec', type: 'button',
                    onClick: () => {
                      const f = offen.find((x) => String(x.id) === sel.value);
                      if (!f) return;
                      c.faecher.push({ fach_id: f.id, label: f.name, stundenansatz: 0 });
                      zeichne();
                    },
                  }, '+ Aus dem Katalog'),
                ]));
              }

              liste.appendChild(el('button', {
                class: 'chip-add', type: 'button', style: 'margin-top:10px',
                onClick: () => neuesLernfeld((neu) => { c.faecher.push(neu); zeichne(); }),
              }, '+ Neues Lernfeld'));
            }
            zeichne();
          },
          validate() { return null; },   // ohne Lernfelder gilt der volle Katalog
        },
        {
          key: 'pruefen',
          label: 'Prüfen',
          render(c, body) {
            const key = (k) => (k.klassen_key.trim() || k.name.trim());
            body.appendChild(el('p', {}, 'Das wird angelegt:'));
            body.appendChild(el('ul', { class: 'drs-facts' }, [
              el('li', {}, [el('strong', {}, 'Jahrgang: '), c.name.trim()]),
              el('li', {}, [
                el('strong', {}, `${c.klassen.length} Klassen: `),
                c.klassen.map((k) => k.name.trim()).join(', '),
              ]),
              el('li', {}, [
                el('strong', {}, `${c.faecher.length} Lernfelder: `),
                c.faecher.length ? c.faecher.map((f) => f.label).join(', ') : '—',
              ]),
            ]));
            body.appendChild(el('p', { class: 'muted' },
              'Dazu entsteht je Klasse eine Lerngruppe für den Stundenplan mit dem Schlüssel: '
              + c.klassen.map(key).join(', ') + '. Diese Schlüssel sind danach unveränderlich.'));
          },
        },
      ],
      async onFinish(c) {
        const res = await postJSON('/api/stammdaten/jahrgang', {
          name: c.name.trim(),
          kuerzel: c.kuerzel.trim(),
          klassen: c.klassen.map((k) => ({
            name: k.name.trim(), kuerzel: k.kuerzel || '',
            klassen_key: k.klassen_key.trim(),
          })),
          faecher: c.faecher.map((f) => ({
            fach_id: f.fach_id || null,
            subjects_key: f.subjects_key || '',
            display_name: f.display_name || '',
            stundenansatz: f.stundenansatz || 0,
          })),
        });
        location.href = res.url;
      },
    });
  }

  // Kleines Modal im Assistenten: Lernfeld anlegen, das noch nicht im Katalog steht.
  function neuesLernfeld(onDone) {
    const name = el('input', { placeholder: 'LF7 Steuerungen realisieren', autofocus: true });
    const key = el('input', { placeholder: 'LF7' });
    const body = el('div', {}, [
      feld('Name des Lernfelds', name),
      feld('Schlüssel', key,
        'Der technische Name aus Untis. Leer lassen = der Name wird verwendet.'),
    ]);
    const m = modal({
      title: 'Neues Lernfeld',
      body,
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: (close) => close() },
        {
          label: 'Übernehmen',
          kind: 'primary',
          onClick: (close) => {
            const n = name.value.trim();
            if (!n) { name.focus(); return; }
            onDone({
              fach_id: null, subjects_key: key.value.trim() || n,
              display_name: n, label: n, stundenansatz: 0,
            });
            close();
          },
        },
      ],
    });
    return m;
  }

  // ---------- Anlegen per Modal (nachträglich, außerhalb des Assistenten) ----------

  function klasseAnlegen(jid) {
    const name = el('input', { placeholder: 'BSMT 26 c', autofocus: true });
    const kuerzel = el('input', { placeholder: 'MT26c' });
    const key = el('input', { placeholder: 'wie der Name' });
    modal({
      title: 'Klasse hinzufügen',
      body: el('div', {}, [
        feld('Name', name, 'Die passende Lerngruppe für den Stundenplan entsteht automatisch.'),
        feld('Kürzel (optional)', kuerzel),
        erweitert(feld('Stundenplan-Schlüssel', key,
          'Leer lassen = der Name wird verwendet. Nur setzen, wenn die Klasse aus Untis '
          + 'übernommen wird — dann muss der Schlüssel exakt stimmen. Später nicht mehr änderbar.')),
      ]),
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: (c) => c() },
        {
          label: 'Anlegen',
          kind: 'primary',
          onClick: async (close) => {
            try {
              await postJSON(`/api/stammdaten/jahrgang/${jid}/klasse`, {
                name: name.value, kuerzel: kuerzel.value, klassen_key: key.value,
              });
              close();
              location.reload();
            } catch (e) { toast(e.message); }
          },
        },
      ],
    });
  }

  function fachZuordnen(jid) {
    getJSON('/api/stammdaten/katalog').then((k) => {
      const sel = el('select', {},
        [el('option', { value: '' }, '— neues Lernfeld anlegen —')].concat(
          k.faecher.map((f) => el('option', { value: String(f.id) }, `${f.name} (${f.key})`))));
      const neuName = el('input', { placeholder: 'LF7 Steuerungen realisieren' });
      const neuKey = el('input', { placeholder: 'LF7' });
      const std = el('input', { type: 'number', min: '0', value: '0' });
      const von = el('input', { type: 'date' });
      const bis = el('input', { type: 'date' });
      const neuBox = el('div', {}, [
        feld('Name des Lernfelds', neuName),
        feld('Schlüssel', neuKey, 'Der technische Name aus Untis. Leer = der Name wird verwendet.'),
      ]);

      function sync() { neuBox.style.display = sel.value ? 'none' : ''; }
      sel.addEventListener('change', sync);
      sync();

      modal({
        title: 'Lernfeld zuordnen',
        body: el('div', {}, [
          feld('Aus dem Katalog', sel),
          neuBox,
          feld('Stundenansatz', std),
          feld('Zeitraum von / bis (optional)',
            el('div', { class: 'sd-inline' }, [von, bis])),
        ]),
        actions: [
          { label: 'Abbrechen', kind: 'sec', onClick: (c) => c() },
          {
            label: 'Zuordnen',
            kind: 'primary',
            onClick: async (close) => {
              try {
                await postJSON(`/api/stammdaten/jahrgang/${jid}/fach`, {
                  fach_id: sel.value ? Number(sel.value) : null,
                  subjects_key: neuKey.value, display_name: neuName.value,
                  stundenansatz: Number(std.value) || 0,
                  zeitraum_von: von.value, zeitraum_bis: bis.value,
                });
                close();
                location.reload();
              } catch (e) { toast(e.message); }
            },
          },
        ],
      });
    }).catch((e) => toast(e.message));
  }

  // Lernfeld eines Jahrgangs bearbeiten. Die Daten stehen schon als data-* an der
  // Karte — kein zusätzlicher Request nötig.
  function fachModal(data) {
    const std = el('input', { type: 'number', min: '0', value: data.stunden || '0' });
    const von = el('input', { type: 'date', value: data.von || '' });
    const bis = el('input', { type: 'date', value: data.bis || '' });
    modal({
      title: data.name,
      body: el('div', {}, [
        feld('Stundenansatz', std),
        feld('Zeitraum von / bis', el('div', { class: 'sd-inline' }, [von, bis])),
      ]),
      actions: [
        {
          label: 'Aus dem Jahrgang nehmen',
          kind: 'danger',
          onClick: async (close) => {
            try {
              await postJSON(`/api/stammdaten/jahrgangfach/${data.fach}/delete`, {});
              close();
              toast('Aus dem Jahrgang genommen — das Fach selbst bleibt im Katalog.');
              location.reload();
            } catch (e) { toast(e.message); }
          },
        },
        {
          label: 'Speichern',
          kind: 'primary',
          onClick: async (close) => {
            try {
              await postJSON(`/api/stammdaten/jahrgangfach/${data.fach}/save`, {
                stundenansatz: Number(std.value) || 0,
                zeitraum_von: von.value, zeitraum_bis: bis.value,
              });
              close();
              location.reload();
            } catch (e) { toast(e.message); }
          },
        },
      ],
    });
  }

  // ---------- Fächer-Katalog ----------

  function katalogFachAnlegen() {
    const name = el('input', { placeholder: 'LF7 Steuerungen realisieren', autofocus: true });
    const key = el('input', { placeholder: 'LF7' });
    const kuerzel = el('input', { placeholder: 'LF7' });
    modal({
      title: 'Neues Fach',
      body: el('div', {}, [
        feld('Name', name, 'So steht es im Stundenplan.'),
        feld('Kürzel (optional)', kuerzel),
        erweitert(feld('Schlüssel', key,
          'Der technische Name aus Untis (oft ein Platzhalter wie BBU_Mt2). Leer lassen = der '
          + 'Name wird verwendet. Später nicht mehr änderbar — an ihm hängen die Stundennotizen.')),
      ]),
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: (c) => c() },
        {
          label: 'Anlegen',
          kind: 'primary',
          onClick: async (close) => {
            try {
              await postJSON('/api/stammdaten/fach', {
                display_name: name.value, subjects_key: key.value, kuerzel: kuerzel.value,
              });
              close();
              location.reload();
            } catch (e) { toast(e.message); }
          },
        },
      ],
    });
  }

  function katalogFachModal(fid) {
    getJSON(`/api/stammdaten/fach/${fid}`).then((f) => {
      const name = el('input', { value: f.display_name });
      const kuerzel = el('input', { value: f.kuerzel });
      const aktiv = el('input', { type: 'checkbox', checked: f.active });
      modal({
        title: f.display_name || f.subjects_key,
        body: el('div', {}, [
          feld('Name', name),
          feld('Kürzel', kuerzel),
          el('label', { class: 'sd-check' }, [aktiv, ' aktiv']),
          el('p', { class: 'muted', style: 'margin-top:.8rem' }, [
            'Schlüssel: ', el('code', {}, f.subjects_key),
            ' — unveränderlich, denn daran hängen die Stundennotizen.',
          ]),
        ]),
        actions: [
          {
            label: 'Löschen',
            kind: 'danger',
            onClick: (close) => {
              close();
              loeschenBestaetigen({
                titel: `Fach „${f.display_name || f.subjects_key}“ löschen?`,
                fakten: f.impact,
                url: `/api/stammdaten/fach/${fid}/delete`,
                warnung: 'Endgültig löschen entfernt das Fach aus allen Jahrgängen und alle '
                  + 'Stunden im Grundstundenplan, die es benutzen. Deine Stundennotizen bleiben '
                  + `erhalten — sie hängen am Schlüssel „${f.subjects_key}“, nicht am `
                  + 'Katalogeintrag.',
                stilllegen: () => postJSON(`/api/stammdaten/fach/${fid}/save`, {
                  display_name: f.display_name, kuerzel: f.kuerzel, active: false,
                }),
              });
            },
          },
          {
            label: 'Speichern',
            kind: 'primary',
            onClick: async (close) => {
              try {
                await postJSON(`/api/stammdaten/fach/${fid}/save`, {
                  display_name: name.value, kuerzel: kuerzel.value, active: aktiv.checked,
                });
                close();
                location.reload();
              } catch (e) { toast(e.message); }
            },
          },
        ],
      });
    }).catch((e) => toast(e.message));
  }

  // ---------- Assistent: Lerngruppe bilden ----------

  // Der Katalog wird hier VOR dem Öffnen geladen — anders als beim Jahrgangs-
  // Assistenten braucht ihn schon der erste Schritt (Jahrgangs-Auswahl); ein
  // nachträglich eintreffender Fetch fände das Dropdown bereits gerendert vor.
  async function lerngruppeWizard() {
    const ctx = {
      art: 'kombi', jahrgang_id: null, alleKlassen: [], jahrgaenge: [],
      schulklasse_ids: [], student_ids: [], quelle_klasse: null, schueler: [],
      klassen_key: '', display_name: '',
    };

    try {
      const k = await getJSON('/api/stammdaten/katalog');
      ctx.jahrgaenge = k.jahrgaenge;
      ctx.alleKlassen = k.klassen;
      if (k.jahrgaenge.length) ctx.jahrgang_id = k.jahrgaenge[0].id;
    } catch (e) {
      toast('Konnte die Stammdaten nicht laden.');
      return;
    }
    if (!ctx.jahrgaenge.length) {
      toast('Lege zuerst einen Jahrgang an.');
      return;
    }

    wizard({
      title: 'Lerngruppe bilden',
      finishLabel: 'Lerngruppe anlegen',
      ctx,
      steps: [
        {
          key: 'art',
          label: 'Art',
          render(c, body) {
            body.appendChild(el('p', {}, 'Was für eine Lerngruppe soll es werden?'));
            const wahl = (wert, titel, text) => {
              const r = el('input', {
                type: 'radio', name: 'art', value: wert, checked: c.art === wert,
                onChange: () => { c.art = wert; },
              });
              return el('label', { class: 'card', style: 'display:flex;gap:10px;padding:12px;margin:10px 0;cursor:pointer' }, [
                r,
                el('div', {}, [
                  el('strong', {}, titel),
                  el('div', { class: 'muted' }, text),
                ]),
              ]);
            };
            body.appendChild(wahl('kombi', 'Klassen zusammenlegen',
              'Mehrere Klassen sitzen gemeinsam im Unterricht, z. B. MT23a + MT23b.'));
            body.appendChild(wahl('gruppe', 'Teilgruppe einer Klasse',
              'Nur ein Teil der Schüler, z. B. eine geteilte Werkstattgruppe.'));

            const sel = el('select', {
              onChange: (e) => {
                c.jahrgang_id = Number(e.target.value);
                c.schulklasse_ids = []; c.student_ids = []; c.quelle_klasse = null;
              },
            }, c.jahrgaenge.map((j) => el('option', {
              value: String(j.id), selected: c.jahrgang_id === j.id,
            }, j.name)));
            body.appendChild(feld('Jahrgang', sel,
              'Es lassen sich nur Klassen desselben Jahrgangs zusammenlegen.'));
          },
          validate(c) {
            if (!c.jahrgang_id) return 'Lege zuerst einen Jahrgang an.';
            return null;
          },
        },
        {
          key: 'wer',
          label: 'Wer',
          render(c, body) {
            const klassen = c.alleKlassen.filter((k) => k.jahrgang_id === c.jahrgang_id);

            if (c.art === 'kombi') {
              body.appendChild(el('p', {}, 'Welche Klassen werden zusammengelegt?'));
              const box = el('div', { class: 'chip-row', style: 'margin-top:10px' },
                klassen.map((k) => {
                  const cb = el('input', {
                    type: 'checkbox', checked: c.schulklasse_ids.includes(k.id),
                    onChange: (e) => {
                      if (e.target.checked) c.schulklasse_ids.push(k.id);
                      else c.schulklasse_ids = c.schulklasse_ids.filter((x) => x !== k.id);
                      // Schlüssel und Anzeigename entstehen erst im nächsten Schritt
                      // aus der Auswahl — hier nur die Auswahl mitschreiben.
                      c.klassen_key = '';
                      c.display_name = '';
                    },
                  });
                  return el('label', { class: 'sd-check', style: 'border:1px solid var(--border);border-radius:8px;padding:6px 10px' },
                    [cb, ' ' + k.name]);
                }));
              body.appendChild(box);
              if (!klassen.length) {
                body.appendChild(el('p', { class: 'muted' },
                  'Dieser Jahrgang hat noch keine Klassen.'));
              }
              return;
            }

            body.appendChild(el('p', {}, 'Aus welcher Klasse kommt die Teilgruppe?'));
            const sel = el('select', {
              onChange: async (e) => {
                c.quelle_klasse = Number(e.target.value) || null;
                c.student_ids = [];
                liste.innerHTML = '';
                if (!c.quelle_klasse) return;
                const s = await getJSON(`/api/stammdaten/schulklassen/${c.quelle_klasse}/schueler`);
                c.schueler = s;
                if (!s.length) {
                  liste.appendChild(el('p', { class: 'muted' },
                    'Diese Klasse hat noch keine Schüler.'));
                  return;
                }
                s.forEach((st) => {
                  const cb = el('input', {
                    type: 'checkbox',
                    onChange: (ev) => {
                      if (ev.target.checked) c.student_ids.push(st.id);
                      else c.student_ids = c.student_ids.filter((x) => x !== st.id);
                    },
                  });
                  liste.appendChild(el('label', {
                    class: 'sd-check',
                    style: 'border:1px solid var(--border);border-radius:8px;padding:6px 10px',
                  }, [cb, ' ' + st.name]));
                });
              },
            }, [el('option', { value: '' }, '— Klasse wählen —')].concat(
              klassen.map((k) => el('option', { value: String(k.id) }, k.name))));
            body.appendChild(feld('Klasse', sel));
            const liste = el('div', { class: 'chip-row', style: 'margin-top:10px' });
            body.appendChild(liste);
          },
          validate(c) {
            if (c.art === 'kombi' && c.schulklasse_ids.length < 2) {
              return 'Wähle mindestens zwei Klassen zum Zusammenlegen.';
            }
            if (c.art === 'gruppe' && !c.student_ids.length) {
              return 'Wähle mindestens einen Schüler für die Teilgruppe.';
            }
            return null;
          },
        },
        {
          key: 'key',
          label: 'Schlüssel',
          render(c, body) {
            const namen = c.art === 'kombi'
              ? c.alleKlassen.filter((k) => c.schulklasse_ids.includes(k.id)).map((k) => k.name)
              : [(c.alleKlassen.find((k) => k.id === c.quelle_klasse) || {}).name || ''];

            if (!c.klassen_key) {
              // Vorbelegung: die Untis-Schreibweise für Kombis nutzt '|' als Trenner.
              c.klassen_key = c.art === 'kombi' ? namen.join('|') : `${namen[0]} Gruppe`;
            }
            if (!c.display_name) {
              c.display_name = c.art === 'kombi'
                ? namen.join(' + ') : `${namen[0]} (Teilgruppe)`;
            }

            const name = el('input', {
              value: c.display_name, onInput: (e) => { c.display_name = e.target.value; },
            });
            const key = el('input', {
              value: c.klassen_key, onInput: (e) => { c.klassen_key = e.target.value; },
            });
            const status = el('div', { class: 'muted', style: 'margin-top:4px' });

            // Live prüfen: ein vergebener Schlüssel würde die Gruppe an fremde Notizen hängen.
            async function pruefe() {
              const k = c.klassen_key.trim();
              if (!k) { status.textContent = ''; return; }
              try {
                const r = await getJSON(`/api/stammdaten/key-frei?key=${encodeURIComponent(k)}`);
                status.textContent = r.frei ? '✓ Schlüssel ist frei' : '✗ Diesen Schlüssel gibt es schon';
                status.style.color = r.frei ? 'var(--gruen)' : 'var(--pink)';
              } catch (_) { status.textContent = ''; }
            }
            key.addEventListener('blur', pruefe);
            pruefe();

            body.appendChild(feld('Anzeigename', name, 'So steht die Gruppe im Stundenplan.'));
            body.appendChild(feld('Stundenplan-Schlüssel', key));
            body.appendChild(status);
            body.appendChild(el('p', { class: 'flash flash-warn', style: 'display:block;margin-top:12px' },
              'Der Schlüssel ist nach dem Anlegen unveränderlich: An ihm hängen die Stundennotizen '
              + 'dieser Gruppe. Legst du eine bestehende Untis-Kombination nach, muss er exakt stimmen.'));
          },
          validate(c) {
            if (!c.klassen_key.trim()) return 'Der Stundenplan-Schlüssel fehlt.';
            return null;
          },
        },
        {
          key: 'pruefen',
          label: 'Prüfen',
          render(c, body) {
            const namen = c.art === 'kombi'
              ? c.alleKlassen.filter((k) => c.schulklasse_ids.includes(k.id)).map((k) => k.name)
              : c.schueler.filter((s) => c.student_ids.includes(s.id)).map((s) => s.name);
            body.appendChild(el('p', {}, 'Das wird angelegt:'));
            body.appendChild(el('ul', { class: 'drs-facts' }, [
              el('li', {}, [el('strong', {}, 'Lerngruppe: '), c.display_name]),
              el('li', {}, [
                el('strong', {}, c.art === 'kombi' ? 'Klassen: ' : 'Schüler: '),
                namen.join(', '),
              ]),
              el('li', {}, [el('strong', {}, 'Schlüssel: '), c.klassen_key]),
            ]));
          },
        },
      ],
      async onFinish(c) {
        await postJSON('/api/stammdaten/lerngruppe', {
          art: c.art,
          jahrgang_id: c.jahrgang_id,
          klassen_key: c.klassen_key.trim(),
          display_name: c.display_name.trim(),
          schulklasse_ids: c.schulklasse_ids,
          student_ids: c.student_ids,
        });
        location.reload();
      },
    });
  }

  // ---------- Detail-Modals ----------

  function jahrgangModal(jid) {
    getJSON(`/api/stammdaten/jahrgang/${jid}`).then((j) => {
      const name = el('input', { value: j.name });
      const kuerzel = el('input', { value: j.kuerzel });
      const aktiv = el('input', { type: 'checkbox', checked: j.active });
      const body = el('div', {}, [
        feld('Name', name),
        feld('Kürzel', kuerzel),
        el('label', { class: 'sd-check' }, [aktiv, ' aktiv']),
        el('p', { class: 'muted', style: 'margin-top:.6rem' },
          'Stillgelegt heißt: Der Jahrgang verschwindet mit allen Klassen und Lerngruppen aus '
          + 'den Auswahllisten. Alte Stunden und Notizen bleiben unverändert sichtbar.'),
      ]);
      modal({
        title: j.name,
        body,
        actions: [
          {
            label: 'Löschen',
            kind: 'danger',
            onClick: (close) => {
              close();
              loeschenBestaetigen({
                titel: `„${j.name}“ löschen?`,
                fakten: j.impact,
                url: `/api/stammdaten/jahrgang/${jid}/delete`,
                stilllegen: () => postJSON(`/api/stammdaten/jahrgang/${jid}/save`, {
                  name: j.name, kuerzel: j.kuerzel, active: false,
                }),
              });
            },
          },
          {
            label: 'Speichern',
            kind: 'primary',
            onClick: async (close) => {
              try {
                await postJSON(`/api/stammdaten/jahrgang/${jid}/save`, {
                  name: name.value, kuerzel: kuerzel.value, active: aktiv.checked,
                });
                close();
                location.reload();
              } catch (e) { toast(e.message); }
            },
          },
        ],
      });
    }).catch((e) => toast(e.message));
  }

  function klasseModal(kid) {
    getJSON(`/api/stammdaten/klasse/${kid}`).then((k) => {
      const name = el('input', { value: k.name });
      const kuerzel = el('input', { value: k.kuerzel });
      const aktiv = el('input', { type: 'checkbox', checked: k.active });
      modal({
        title: k.name,
        body: el('div', {}, [
          feld('Name', name, 'Umbenennen ist gefahrlos — der Stundenplan-Schlüssel hängt an '
            + 'der Lerngruppe, nicht an der Klasse.'),
          feld('Kürzel', kuerzel),
          el('label', { class: 'sd-check' }, [aktiv, ' aktiv']),
        ]),
        actions: [
          {
            label: 'Löschen',
            kind: 'danger',
            onClick: (close) => {
              close();
              loeschenBestaetigen({
                titel: `Klasse „${k.name}“ löschen?`,
                fakten: k.impact,
                url: `/api/stammdaten/klasse/${kid}/delete`,
                stilllegen: () => postJSON(`/api/stammdaten/klasse/${kid}/save`, {
                  name: k.name, kuerzel: k.kuerzel, active: false,
                }),
              });
            },
          },
          {
            label: 'Speichern',
            kind: 'primary',
            onClick: async (close) => {
              try {
                await postJSON(`/api/stammdaten/klasse/${kid}/save`, {
                  name: name.value, kuerzel: kuerzel.value, active: aktiv.checked,
                });
                close();
                location.reload();
              } catch (e) { toast(e.message); }
            },
          },
        ],
      });
    }).catch((e) => toast(e.message));
  }

  function lerngruppeModal(lgid) {
    getJSON(`/api/stammdaten/lerngruppe/${lgid}`).then((g) => {
      const name = el('input', { value: g.display_name });
      const kuerzel = el('input', { value: g.kuerzel });
      const aktiv = el('input', { type: 'checkbox', checked: g.active });
      const art = { klasse: 'Klasse', kombi: 'zusammengelegt', gruppe: 'Teilgruppe' }[g.art];
      modal({
        title: g.display_name || g.klassen_key,
        body: el('div', {}, [
          feld('Anzeigename', name),
          feld('Kürzel', kuerzel),
          el('label', { class: 'sd-check' }, [aktiv, ' aktiv']),
          el('p', { class: 'muted', style: 'margin-top:.8rem' },
            `${art}${g.klassen.length ? ' · ' + g.klassen.join(', ') : ''}`),
          el('p', { class: 'muted' }, [
            'Stundenplan-Schlüssel: ', el('code', {}, g.klassen_key),
            ' — unveränderlich, denn daran hängen die Stundennotizen.',
          ]),
        ]),
        actions: [
          {
            label: 'Löschen',
            kind: 'danger',
            onClick: (close) => {
              close();
              loeschenBestaetigen({
                titel: `Lerngruppe „${g.display_name || g.klassen_key}“ löschen?`,
                fakten: g.impact,
                url: `/api/stammdaten/lerngruppe/${lgid}/delete`,
                warnung: 'Endgültig löschen entfernt die Lerngruppe samt ihrer Stunden im '
                  + 'Grundstundenplan. Deine Stundennotizen bleiben erhalten — sie hängen am '
                  + `Schlüssel „${g.klassen_key}“, nicht an der Gruppe. Legst du später wieder `
                  + 'eine Gruppe mit genau diesem Schlüssel an, sind sie sofort wieder da.',
                stilllegen: () => postJSON(`/api/stammdaten/lerngruppe/${lgid}/save`, {
                  display_name: g.display_name, kuerzel: g.kuerzel, active: false,
                }),
              });
            },
          },
          {
            label: 'Speichern',
            kind: 'primary',
            onClick: async (close) => {
              try {
                await postJSON(`/api/stammdaten/lerngruppe/${lgid}/save`, {
                  display_name: name.value, kuerzel: kuerzel.value, active: aktiv.checked,
                });
                close();
                location.reload();
              } catch (e) { toast(e.message); }
            },
          },
        ],
      });
    }).catch((e) => toast(e.message));
  }

  /* Zeigt vor dem Löschen, was am Objekt hängt, und bietet Stilllegen als
   * gleichwertigen Ausweg an. `warnung` sagt konkret, was das endgültige Löschen
   * mitreißt — beim Lerngruppen- und Fach-Katalog ist das nicht offensichtlich. */
  function loeschenBestaetigen({ titel, fakten, url, stilllegen, warnung }) {
    const haengt = (fakten || []).some((f) => f.wert);
    confirmDanger({
      title: titel,
      text: haengt
        ? 'Daran hängt noch etwas:'
        : 'Daran hängt nichts mehr — Löschen ist gefahrlos.',
      facts: (fakten || []).filter((f) => f.wert),
      warnung: haengt ? warnung : null,
      hinweis: haengt
        ? 'Stilllegen blendet den Eintrag überall aus, lässt aber alles Bestehende in Ruhe.'
        : null,
      safe: 'Stilllegen',
      onSafe: async (close) => {
        try { await stilllegen(); close(); location.reload(); } catch (e) { toast(e.message); }
      },
      danger: 'Endgültig löschen',
      onDanger: async (close) => {
        try {
          await postJSON(url, {});
          close();
          location.reload();
        } catch (e) { toast(e.message); }
      },
    });
  }

  window.DRSStammdaten = {
    jahrgangWizard, lerngruppeWizard,
    jahrgangModal, klasseModal, lerngruppeModal, fachModal,
    klasseAnlegen, fachZuordnen, klassenVorschlag,
    katalogFachModal, katalogFachAnlegen,
  };
})();
