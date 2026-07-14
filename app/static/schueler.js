/* Schüler: Liste, Detail-Modal, Versetzen, Import-Assistent, Wisch-Zuordnung.
 *
 * Zwei Regeln, die hier drinstecken:
 * - **Versetzen statt neu anlegen.** Die student.id bleibt, deshalb überleben alle
 *   Bewertungen den Klassenwechsel. Löschen ist der einzige Weg, der sie mitnimmt.
 * - **Die Wisch-Zuordnung speichert SOFORT**, Karte für Karte — anders als die
 *   Assistenten, die erst am Ende schreiben. Bei 30 Karten wäre ein
 *   versehentlicher Reload sonst eine Katastrophe.
 */
(function () {
  'use strict';
  const { el, feld, wizard, modal, confirmDanger, toast, postJSON, getJSON } = DRS;

  // ---------- Liste: Auswahl, Detail, Versetzen ----------

  function mountListe(opts) {
    const ziele = (opts || {}).ziele || [];
    const picks = () => [...document.querySelectorAll('.stu-pick:checked')];
    const btnVersetzen = document.getElementById('btnVersetzen');
    const info = document.getElementById('auswahlInfo');
    const alle = document.getElementById('alleWaehlen');

    function sync() {
      const n = picks().length;
      if (btnVersetzen) btnVersetzen.disabled = n === 0;
      if (info) info.textContent = n ? `${n} ausgewählt` : '';
    }

    document.querySelectorAll('.stu-pick').forEach((cb) => cb.addEventListener('change', sync));
    if (alle) {
      alle.addEventListener('change', () => {
        document.querySelectorAll('.stu-pick').forEach((cb) => { cb.checked = alle.checked; });
        sync();
      });
    }
    document.querySelectorAll('[data-schueler]').forEach((b) => {
      b.addEventListener('click', () => detail(b.dataset.schueler));
    });
    if (btnVersetzen) {
      btnVersetzen.addEventListener('click', () => {
        versetzen(picks().map((cb) => Number(cb.value)), ziele);
      });
    }
    sync();
  }

  function detail(sid) {
    getJSON(`/api/schueler/${sid}`).then((s) => {
      const nachname = el('input', { value: s.nachname });
      const vorname = el('input', { value: s.vorname });
      const email = el('input', { value: s.email, type: 'email' });
      const aktiv = el('input', { type: 'checkbox', checked: s.active });

      const body = el('div', {}, [
        feld('Nachname', nachname),
        feld('Vorname', vorname),
        feld('E-Mail', email),
        el('label', { class: 'sd-check' }, [aktiv, ' aktiv']),

        el('p', { class: 'muted', style: 'margin-top:1rem' }, [
          el('strong', {}, 'Klasse: '), s.klasse || 'noch keiner zugeordnet',
        ]),
        el('p', { class: 'muted' }, [
          el('strong', {}, 'Lerngruppen: '),
          s.lerngruppen.length ? s.lerngruppen.join(', ') : '—',
        ]),

        s.historie.length
          ? el('div', { style: 'margin-top:1rem' }, [
              el('strong', { style: 'font-size:13px' }, 'Klassenwechsel'),
              el('ul', { class: 'drs-facts' }, s.historie.map((h) => el('li', {}, [
                `${h.von || '—'} → ${h.nach}`,
                el('span', { class: 'muted' },
                  ` · ${h.datum}${h.grund ? ' · ' + h.grund : ''}`),
              ]))),
            ])
          : null,
      ]);

      modal({
        title: `${s.nachname}${s.vorname ? ', ' + s.vorname : ''}`,
        body,
        actions: [
          {
            label: 'Löschen',
            kind: 'danger',
            onClick: (close) => {
              close();
              confirmDanger({
                title: `${s.nachname} löschen?`,
                text: 'Damit gehen auch alle Bewertungen dieses Schülers verloren.',
                warnung: 'Wenn er nur die Klasse wechselt, nimm „Versetzen" — dabei bleiben alle '
                  + 'Prüfungen und Bewertungen erhalten.',
                danger: 'Endgültig löschen',
                onDanger: async (c) => {
                  try {
                    await postJSON(`/api/schueler/${sid}/delete`, {});
                    c();
                    location.reload();
                  } catch (e) { toast(e.message); }
                },
              });
            },
          },
          {
            label: 'Speichern',
            kind: 'primary',
            onClick: async (close) => {
              try {
                await postJSON(`/api/schueler/${sid}/save`, {
                  nachname: nachname.value, vorname: vorname.value,
                  email: email.value, active: aktiv.checked,
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

  function anlegen(kid) {
    const nachname = el('input', { autofocus: true });
    const vorname = el('input', {});
    const email = el('input', { type: 'email' });
    modal({
      title: 'Schüler hinzufügen',
      body: el('div', {}, [
        feld('Nachname', nachname),
        feld('Vorname', vorname),
        feld('E-Mail (optional)', email),
      ]),
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: (c) => c() },
        {
          label: 'Anlegen',
          kind: 'primary',
          onClick: async (close) => {
            try {
              await postJSON('/api/schueler', {
                schulklasse_id: Number(kid), nachname: nachname.value,
                vorname: vorname.value, email: email.value,
              });
              close();
              location.reload();
            } catch (e) { toast(e.message); }
          },
        },
      ],
    });
  }

  function versetzen(ids, ziele) {
    if (!ids.length) return;
    if (!ziele.length) {
      toast('Es gibt keine andere Klasse, in die du versetzen könntest.');
      return;
    }
    const sel = el('select', {}, ziele.map((z) =>
      el('option', { value: String(z.id) }, z.name)));
    const grund = el('input', { placeholder: 'z. B. Wechsel zum Halbjahr' });
    modal({
      title: `${ids.length} Schüler versetzen`,
      body: el('div', {}, [
        feld('In welche Klasse?', sel),
        feld('Grund (optional)', grund),
        el('p', { class: 'muted', style: 'margin-top:.6rem' },
          'Alle bisherigen Prüfungen und Bewertungen bleiben erhalten — der Schüler behält seine '
          + 'Identität, nur seine Klasse ändert sich. Alte Prüfungen führen ihn weiterhin unter '
          + 'der damaligen Klasse, das ist so gewollt.'),
      ]),
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: (c) => c() },
        {
          label: 'Versetzen',
          kind: 'primary',
          onClick: async (close) => {
            try {
              const r = await postJSON('/api/schueler/versetzen', {
                student_ids: ids, nach_klasse_id: Number(sel.value), grund: grund.value,
              });
              close();
              toast(`${r.anzahl} versetzt.`);
              location.reload();
            } catch (e) { toast(e.message); }
          },
        },
      ],
    });
  }

  // ---------- Assistent: Schüler importieren ----------

  function importWizard(jid) {
    const ctx = { datei: null, eintraege: [], format: '', jahrgang_id: Number(jid) };

    wizard({
      title: 'Schüler importieren',
      finishLabel: 'In den Pool übernehmen',
      ctx,
      steps: [
        {
          key: 'datei',
          label: 'Datei',
          render(c, body) {
            const input = el('input', {
              type: 'file', accept: '.csv,text/csv,text/plain',
              onChange: async (e) => {
                const f = e.target.files[0];
                if (!f) return;
                status.textContent = 'Lese die Datei …';
                const fd = new FormData();
                fd.append('file', f);
                try {
                  const r = await fetch('/api/schueler/import/vorschau',
                                        { method: 'POST', body: fd });
                  const d = await r.json();
                  if (!r.ok) throw new Error(d.detail || 'Konnte die Datei nicht lesen.');
                  c.eintraege = d.eintraege;
                  c.format = d.format;
                  status.textContent = `${d.eintraege.length} Schüler erkannt.`;
                  status.style.color = 'var(--gruen)';
                } catch (err) {
                  c.eintraege = [];
                  status.textContent = err.message;
                  status.style.color = 'var(--pink)';
                }
              },
            });
            const status = el('div', { class: 'muted', style: 'margin-top:6px' });
            body.appendChild(feld('Teilnehmerliste aus Moodle (CSV)', input,
              'Der Export aus Moodle passt direkt. Es wird noch nichts gespeichert — '
              + 'im nächsten Schritt siehst du erst, was erkannt wurde.'));
            body.appendChild(status);
          },
          validate(c) {
            if (!c.eintraege.length) return 'Wähle eine Datei, aus der Schüler erkannt werden.';
            return null;
          },
        },
        {
          key: 'vorschau',
          label: 'Vorschau',
          render(c, body) {
            body.appendChild(el('p', {}, [
              el('strong', {}, `${c.eintraege.length} Schüler erkannt`),
              el('span', { class: 'muted' }, ` (Format: ${c.format})`),
            ]));
            body.appendChild(el('p', { class: 'muted' },
              'Sie landen zunächst ohne Klasse im Pool des Jahrgangs. Im nächsten Schritt '
              + 'verteilst du sie per Wischen auf die Klassen. Wer schon im Jahrgang steht, '
              + 'wird übersprungen.'));
            const liste = el('div', {
              style: 'max-height:280px;overflow:auto;border:1px solid var(--border);'
                + 'border-radius:8px;margin-top:10px',
            });
            c.eintraege.forEach((e) => {
              liste.appendChild(el('div', {
                style: 'padding:7px 10px;border-bottom:1px solid var(--border)',
              }, [
                el('strong', {}, `${e.nachname}${e.vorname ? ', ' + e.vorname : ''}`),
                e.email ? el('span', { class: 'muted' }, ' · ' + e.email) : null,
              ]));
            });
            body.appendChild(liste);
          },
        },
      ],
      async onFinish(c) {
        const r = await postJSON('/api/schueler/import', {
          jahrgang_id: c.jahrgang_id, eintraege: c.eintraege,
        });
        location.href = r.url;
      },
    });
  }

  // ---------- Wisch-Zuordnung ----------

  /* Pointer Events statt Touch Events: derselbe Code trägt Finger, Stift und Maus.
   * Gespeichert wird pro Karte sofort; „Rückgängig" schickt den Schüler zurück in
   * den Pool und legt die Karte wieder oben auf. */
  function zuordnung(cfg) {
    const stapel = document.getElementById('stapel');
    const status = document.getElementById('zuStatus');
    const undo = document.getElementById('btnUndo');
    const klassen = cfg.klassen;
    const offen = cfg.pool.slice();
    const historie = [];
    // Sperre gegen Doppelauslösung: `weg()` speichert asynchron, und die alte
    // Karte bleibt für die Wegflug-Animation noch 160 ms im DOM. Ohne diese
    // Sperre konnte ein zweiter Pointer-/Klick-Event denselben Stapel ein
    // zweites Mal abräumen — im Test wurden dadurch aus einem Klick sieben
    // Zuordnungen.
    let busy = false;

    // Swipe belegt die zwei ersten Klassen (mehr Richtungen gibt eine Geste nicht
    // her); alle weiteren gehen über die Knöpfe darunter.
    const links = klassen[0] || null;
    const rechts = klassen[1] || null;

    document.querySelectorAll('.zu-ziel').forEach((b) => {
      b.addEventListener('click', () => {
        const k = klassen.find((x) => x.id === Number(b.dataset.klasse));
        if (k) weg(k, k === rechts ? 1 : -1);
      });
    });
    undo.addEventListener('click', zurueck);

    function stand() {
      status.textContent = offen.length
        ? `noch ${offen.length}`
        : 'alle zugeordnet 🎉';
      undo.disabled = !historie.length;
    }

    function zeichne() {
      stapel.innerHTML = '';
      if (!offen.length) {
        stapel.appendChild(el('div', { class: 'zu-karte', style: 'cursor:default' }, [
          el('div', { class: 'zu-name' }, 'Fertig'),
          el('div', { class: 'zu-rest' }, 'Alle Schüler dieses Jahrgangs sind zugeordnet.'),
        ]));
        stand();
        return;
      }
      const s = offen[0];
      const karte = el('div', { class: 'zu-karte' }, [
        links ? el('div', { class: 'zu-marke links' }, '‹ ' + links.name) : null,
        rechts ? el('div', { class: 'zu-marke rechts' }, rechts.name + ' ›') : null,
        el('div', { class: 'zu-name' }, s.name),
        el('div', { class: 'zu-rest' },
          klassen.length > 2
            ? 'wischen für die ersten beiden Klassen — sonst unten tippen'
            : 'nach links oder rechts wischen'),
      ]);
      stapel.appendChild(karte);
      greifen(karte);
      stand();
    }

    function greifen(karte) {
      const mLinks = karte.querySelector('.zu-marke.links');
      const mRechts = karte.querySelector('.zu-marke.rechts');
      let x0 = 0, dx = 0, aktiv = false;

      karte.addEventListener('pointerdown', (e) => {
        if (busy || karte.dataset.weg) return;
        aktiv = true;
        x0 = e.clientX;
        karte.setPointerCapture(e.pointerId);
        karte.style.transition = 'none';
      });
      karte.addEventListener('pointermove', (e) => {
        if (!aktiv) return;
        dx = e.clientX - x0;
        karte.style.transform = `translateX(${dx}px) rotate(${dx / 22}deg)`;
        if (mRechts) mRechts.style.opacity = dx > 20 ? Math.min(1, dx / 90) : 0;
        if (mLinks) mLinks.style.opacity = dx < -20 ? Math.min(1, -dx / 90) : 0;
      });
      function los(e) {
        if (!aktiv) return;
        aktiv = false;
        try { karte.releasePointerCapture(e.pointerId); } catch (_) { /* egal */ }
        karte.style.transition = 'transform .18s ease';
        const ziel = dx > 90 ? rechts : (dx < -90 ? links : null);
        const richtung = dx > 0 ? 1 : -1;
        dx = 0;
        if (ziel) {
          weg(ziel, richtung);
        } else {
          karte.style.transform = '';
          if (mRechts) mRechts.style.opacity = 0;
          if (mLinks) mLinks.style.opacity = 0;
        }
      }
      karte.addEventListener('pointerup', los);
      karte.addEventListener('pointercancel', los);
    }

    async function weg(klasse, richtung) {
      if (busy) return;
      const s = offen[0];
      if (!s) return;
      busy = true;

      const karte = stapel.querySelector('.zu-karte');
      if (karte) {
        // Als verbraucht markieren: die Karte fliegt noch 160 ms weg, darf in
        // dieser Zeit aber keine Geste mehr annehmen.
        karte.dataset.weg = '1';
        karte.style.pointerEvents = 'none';
        karte.classList.add('weg');
        karte.style.transform =
          `translateX(${richtung * 460}px) rotate(${richtung * 18}deg)`;
      }
      offen.shift();
      historie.push({ schueler: s, klasse });

      try {
        // Sofort speichern — nicht erst am Ende.
        await postJSON(`/api/schueler/${s.id}/zuordnen`, { schulklasse_id: klasse.id });
      } catch (e) {
        toast('Konnte nicht speichern: ' + e.message);
        offen.unshift(s);
        historie.pop();
      }
      setTimeout(() => { busy = false; zeichne(); }, 160);
    }

    async function zurueck() {
      if (busy) return;
      const letzte = historie[historie.length - 1];
      if (!letzte) return;
      busy = true;
      try {
        await postJSON(`/api/schueler/${letzte.schueler.id}/zuordnen`,
                       { schulklasse_id: null });
        historie.pop();
        offen.unshift(letzte.schueler);
        toast(`${letzte.schueler.name} zurück in den Pool.`);
        zeichne();
      } catch (e) {
        toast(e.message);
      } finally {
        busy = false;
      }
    }

    zeichne();
  }

  window.DRSSchueler = { mountListe, detail, anlegen, versetzen, importWizard, zuordnung };
})();
