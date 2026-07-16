/* Aufgaben: Umschalter Liste ↔ Kanban-Board, Drag & Drop, Edit-Karte.
 *
 * Das Board liest EINE Vikunja-Kanban-View (Buckets + Tasks) über die eigenen
 * /api/vikunja/*-Endpoints. Verschoben wird per Pointer-Events (dasselbe Muster
 * wie die Schüler-Wischzuordnung — ein Code für Maus, Finger und Stift). Ein
 * Klick ohne Ziehen öffnet die Edit-Karte (Titel/Fällig/Priorität/Beschreibung
 * + Labels). Erledigt-Bucket: Vikunja hakt beim Reinschieben automatisch ab.
 */
(function () {
  'use strict';
  if (!window.DRS) return;
  const { el, feld, modal, toast, postJSON, getJSON } = DRS;

  const PRIORITY = { 0: '', 1: 'Niedrig', 2: 'Mittel', 3: 'Hoch', 4: 'Dringend', 5: 'DRINGEND!' };

  // ── Helfer ────────────────────────────────────────────────────────────
  function todayStart() { const d = new Date(); d.setHours(0, 0, 0, 0); return d; }
  function fmtDate(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const p = (n) => String(n).padStart(2, '0');
    return p(d.getDate()) + '.' + p(d.getMonth() + 1) + '.' + d.getFullYear();
  }
  function isoToDateInput(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const p = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  }
  function labelBg(hex) {
    const h = (hex || '').trim();
    if (!h) return '#e8eef4';
    return h[0] === '#' ? h : '#' + h;
  }
  function stripTags(html) {
    const tmp = document.createElement('div');
    tmp.innerHTML = html || '';
    return (tmp.textContent || '').replace(/\s+/g, ' ').trim();
  }

  const boardEl = document.getElementById('board');
  const vList = document.getElementById('view-list');
  const vBoard = document.getElementById('view-board');
  let boardLoaded = false;
  let LABELS = [];
  let BUCKETS = [];        // Spalten der Kanban-View, auch für den Anlege-Dialog
  let LERNGRUPPEN = [];

  // ── Umschalter ────────────────────────────────────────────────────────
  const toggle = document.querySelector('.view-toggle');

  // Die Liste ist server-gerendert: Wer im Board etwas ändert oder löscht,
  // macht sie ungültig. Statt sie nachzupflegen holen wir sie beim nächsten
  // Umschalten einmal frisch — Reload nur dann, wenn er wirklich nötig ist.
  let listStale = false;
  function markListStale() { listStale = true; }
  function reloadBoard() {
    boardLoaded = false;
    if (vBoard && !vBoard.hidden) loadBoard();
  }

  function showView(name) {
    if (!vList || !vBoard) return;
    const board = name === 'board';
    if (!board && listStale) { location.reload(); return; }
    vList.hidden = board;
    vBoard.hidden = !board;
    if (toggle) toggle.querySelectorAll('.vt-btn').forEach((b) =>
      b.classList.toggle('active', b.dataset.view === name));
    try { localStorage.setItem('aufgabenView', name); } catch (_) { /* egal */ }
    if (board && !boardLoaded) loadBoard();
  }
  if (toggle) {
    toggle.addEventListener('click', (e) => {
      const b = e.target.closest('.vt-btn');
      if (b) showView(b.dataset.view);
    });
    let initial = 'list';
    try { initial = localStorage.getItem('aufgabenView') || 'list'; } catch (_) { /* egal */ }
    if (location.hash === '#board') initial = 'board';
    showView(initial);
  }

  // ── Board laden + rendern ─────────────────────────────────────────────
  async function loadBoard() {
    if (!boardEl) return;
    boardEl.innerHTML = '<div class="muted" style="padding:1rem">lädt …</div>';
    try {
      const d = await getJSON('/api/vikunja/board');
      if (!d.ok) {
        boardEl.innerHTML = '<div class="flash flash-err" style="display:block">'
          + (d.error || 'Konnte das Board nicht laden.') + '</div>';
        return;
      }
      BUCKETS = d.buckets || [];
      renderBoard(BUCKETS);
      boardLoaded = true;
    } catch (e) {
      boardEl.innerHTML = '<div class="flash flash-err" style="display:block">'
        + 'Board nicht erreichbar.</div>';
    }
  }

  function renderBoard(buckets) {
    boardEl.innerHTML = '';
    if (!buckets.length) {
      boardEl.innerHTML = '<div class="muted" style="padding:1rem">Dieses Projekt hat keine '
        + 'Kanban-Spalten. Leg sie in Vikunja an.</div>';
      return;
    }
    buckets.forEach((b) => {
      const cards = el('div', { class: 'board-cards' });
      (b.tasks || []).forEach((t) => cards.appendChild(cardEl(t, b.id)));
      const col = el('div', {
        class: 'board-col' + (b.is_done_bucket ? ' is-done' : ''),
        'data-bucket': b.id,
      }, [
        el('div', { class: 'board-col-head' }, [
          el('span', { class: 'board-col-title' }, b.title),
          el('span', { class: 'board-col-count' }, String((b.tasks || []).length)),
        ]),
        cards,
      ]);
      boardEl.appendChild(col);
    });
  }

  function cardEl(t, bucketId) {
    const meta = [];
    if (t.due_date) {
      const d = new Date(t.due_date);
      const overdue = !isNaN(d) && d < todayStart();
      meta.push(el('span', { class: 'bc-due' + (overdue ? ' is-overdue' : '') }, fmtDate(t.due_date)));
    }
    if (t.priority >= 3) meta.push(el('span', { class: 'badge bc-prio' }, PRIORITY[t.priority] || ''));
    (t.labels || []).forEach((lb) => meta.push(
      el('span', { class: 'badge bc-label', style: 'background:' + labelBg(lb.hex_color) }, lb.title)));

    const descText = stripTags(t.description || '');
    const card = el('div', {
      class: 'board-card', 'data-id': t.id, 'data-bucket': bucketId,
    }, [
      el('div', { class: 'bc-title' }, t.title),
      descText ? el('div', { class: 'bc-desc' }, descText) : null,
      meta.length ? el('div', { class: 'bc-meta' }, meta) : null,
    ]);
    card._task = t;
    return card;
  }

  function updateCount(col) {
    const c = col.querySelector('.board-col-count');
    const n = col.querySelectorAll('.board-card').length;
    if (c) c.textContent = String(n);
  }

  // ── Drag & Drop (Pointer-Events, ein Code für Maus + Touch) ────────────
  // Dokument-Listener EINMAL registrieren; `drag` ist Modul-Zustand. So sammeln
  // sich beim Neu-Rendern des Boards keine doppelten Listener an.
  let drag = null;

  if (boardEl) {
    boardEl.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 && e.pointerType === 'mouse') return;
      const card = e.target.closest('.board-card');
      if (!card) return;
      drag = {
        card, from: String(card.dataset.bucket),
        x0: e.clientX, y0: e.clientY, moved: false,
        clone: null, over: null, offX: 0, offY: 0,
      };
    });

    document.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x0, dy = e.clientY - drag.y0;
      if (!drag.moved && Math.hypot(dx, dy) < 6) return;
      if (!drag.moved) {
        drag.moved = true;
        const r = drag.card.getBoundingClientRect();
        const c = drag.card.cloneNode(true);
        c.classList.add('drag-ghost');
        c.style.width = r.width + 'px';
        drag.offX = e.clientX - r.left;
        drag.offY = e.clientY - r.top;
        document.body.appendChild(c);
        drag.clone = c;
        drag.card.classList.add('dragging-src');
      }
      drag.clone.style.left = (e.clientX - drag.offX) + 'px';
      drag.clone.style.top = (e.clientY - drag.offY) + 'px';
      // Spalte unter dem Zeiger (der Klon hat pointer-events:none)
      const under = document.elementFromPoint(e.clientX, e.clientY);
      const col = under ? under.closest('.board-col') : null;
      if (drag.over && drag.over !== col) drag.over.classList.remove('drop-target');
      drag.over = col;
      if (col) col.classList.add('drop-target');
    });

    document.addEventListener('pointerup', () => {
      if (!drag) return;
      const d = drag; drag = null;
      if (!d.moved) { openEdit(d.card._task); return; }   // Klick → Edit-Karte
      if (d.clone) d.clone.remove();
      d.card.classList.remove('dragging-src');
      if (d.over) d.over.classList.remove('drop-target');
      const toBucket = d.over ? String(d.over.dataset.bucket) : null;
      if (!toBucket || toBucket === d.from) return;
      // Optimistisch verschieben, bei Fehler neu laden.
      const fromCol = boardEl.querySelector('.board-col[data-bucket="' + d.from + '"]');
      const cards = d.over.querySelector('.board-cards');
      cards.appendChild(d.card);
      d.card.dataset.bucket = toBucket;
      updateCount(d.over);
      if (fromCol) updateCount(fromCol);
      postJSON('/api/vikunja/tasks/' + d.card.dataset.id + '/move', {
        bucket_id: Number(toBucket),
      }).then(() => {
        // Ins „Erledigt"-Bucket zu schieben hakt in Vikunja ab — dann stimmt
        // die offene Liste nicht mehr.
        markListStale();
      }).catch((err) => {
        toast('Verschieben fehlgeschlagen: ' + err.message);
        loadBoard();
      });
    });
  }

  // ── Edit-Karte ────────────────────────────────────────────────────────
  async function openEdit(t) {
    const title = el('input', { value: t.title, maxlength: '250' });
    const due = el('input', { type: 'date', value: t.due_date ? isoToDateInput(t.due_date) : '' });
    const prio = el('select', {}, Object.entries(PRIORITY).map(([v, l]) =>
      el('option', { value: v }, l || '— keine —')));
    prio.value = String(t.priority || 0);
    const desc = el('textarea', { rows: '4' }, stripTags(t.description || ''));

    // Labels: aktuelle als Chips (sofort setzen/entfernen), Auswahl zum Ergänzen
    let dirty = false;
    const current = (t.labels || []).slice();
    const chips = el('div', { class: 'lbl-chips' });
    function renderChips() {
      chips.innerHTML = '';
      if (!current.length) chips.appendChild(el('span', { class: 'muted', style: 'font-size:12px' }, 'keine'));
      current.forEach((lb) => chips.appendChild(el('span', {
        class: 'badge lbl-chip', style: 'background:' + labelBg(lb.hex_color),
      }, [
        lb.title || '(Label)',
        el('button', {
          type: 'button', class: 'lbl-x', title: 'entfernen',
          onClick: async () => {
            try {
              await postJSON('/api/vikunja/tasks/' + t.id + '/labels/' + lb.id + '/delete', {});
              const i = current.findIndex((x) => x.id === lb.id);
              if (i >= 0) current.splice(i, 1);
              renderChips(); dirty = true;
            } catch (e) { toast(e.message); }
          },
        }, '×'),
      ])));
    }
    renderChips();

    if (!LABELS.length) {
      try { const d = await getJSON('/api/vikunja/labels'); if (d.ok) LABELS = d.labels || []; }
      catch (_) { /* ohne Labelliste geht der Rest trotzdem */ }
    }
    const addSel = el('select', {}, [
      el('option', { value: '' }, '+ Label hinzufügen …'),
      ...LABELS.map((l) => el('option', { value: l.id }, l.title)),
    ]);
    addSel.addEventListener('change', async () => {
      const id = Number(addSel.value);
      addSel.value = '';
      if (!id || current.some((x) => x.id === id)) return;
      const lb = LABELS.find((x) => x.id === id);
      if (!lb) return;
      try {
        await postJSON('/api/vikunja/tasks/' + t.id + '/labels', { label_id: id });
        current.push(lb); renderChips(); dirty = true;
      } catch (e) { toast(e.message); }
    });

    const body = el('div', {}, [
      feld('Titel', title),
      feld('Fällig am', due),
      feld('Priorität', prio),
      feld('Beschreibung', desc),
      feld('Labels', el('div', {}, [chips, addSel])),
    ]);

    modal({
      title: 'Aufgabe bearbeiten',
      body,
      onClose: () => { if (dirty) reloadBoard(); },  // reine Label-Änderungen nachziehen
      actions: [
        {
          label: 'Löschen', kind: 'danger',
          onClick: (close) => {
            if (!confirm('Aufgabe „' + t.title + '“ in Vikunja löschen?')) return;
            postJSON('/api/vikunja/tasks/' + t.id + '/delete', {})
              .then(() => { dirty = false; close(); reloadBoard(); markListStale(); })
              .catch((e) => toast(e.message));
          },
        },
        {
          label: 'Speichern', kind: 'primary',
          onClick: async (close) => {
            if (!title.value.trim()) { toast('Titel fehlt.'); return; }
            try {
              await postJSON('/api/vikunja/tasks/' + t.id + '/update', {
                title: title.value, due_date: due.value,
                priority: Number(prio.value), description: desc.value,
              });
              dirty = false; close(); reloadBoard(); markListStale();
            } catch (e) { toast(e.message); }
          },
        },
      ],
    });
  }

  // ── Anlege-Dialog ─────────────────────────────────────────────────────
  // Ein Objekt mit ein paar Feldern → Modal, kein Vollbild-Assistent. Gespeichert
  // wird in EINEM Request nach außen; dass Vikunja intern Bucket und Labels
  // nachgezogen bekommt, ist Sache des Backends.
  async function openCreate() {
    // Alles, was die Auswahlfelder brauchen, VOR dem Öffnen laden — ein
    // nachlaufendes getJSON() lässt die Dropdowns leer.
    if (!BUCKETS.length) {
      try { const d = await getJSON('/api/vikunja/board'); if (d.ok) BUCKETS = d.buckets || []; }
      catch (_) { /* ohne Spaltenliste legen wir in die Standardspalte */ }
    }
    if (!LABELS.length) {
      try { const d = await getJSON('/api/vikunja/labels'); if (d.ok) LABELS = d.labels || []; }
      catch (_) { /* Labels sind optional */ }
    }
    if (!LERNGRUPPEN.length) {
      try { const d = await getJSON('/api/vikunja/lerngruppen'); if (d.ok) LERNGRUPPEN = d.lerngruppen || []; }
      catch (_) { /* ohne Lerngruppen bleibt der Picker leer */ }
    }

    const title = el('input', { maxlength: '250', placeholder: 'z. B. Klausur BSMT 22b korrigieren' });
    const due = el('input', { type: 'date' });
    const prio = el('select', {}, Object.entries(PRIORITY).map(([v, l]) =>
      el('option', { value: v }, l || '— keine —')));
    const desc = el('textarea', { rows: '4', placeholder: 'Notizen, Kontext, Checkliste …' });
    const bucketSel = el('select', {}, [
      el('option', { value: '' }, '— Standardspalte —'),
      ...BUCKETS.map((b) => el('option', { value: b.id }, b.title)),
    ]);
    const klasseSel = el('select', {}, [
      el('option', { value: '' }, '— keine —'),
      ...LERNGRUPPEN.map((l) => el('option', { value: l.name }, l.name)),
    ]);

    // Labels vor dem Anlegen nur vormerken — die Aufgabe gibt es ja noch nicht.
    const pending = [];
    const chips = el('div', { class: 'lbl-chips' });
    function renderChips() {
      chips.innerHTML = '';
      if (!pending.length) chips.appendChild(el('span', { class: 'muted', style: 'font-size:12px' }, 'keine'));
      pending.forEach((lb) => chips.appendChild(el('span', {
        class: 'badge lbl-chip', style: 'background:' + labelBg(lb.hex_color),
      }, [
        lb.title || '(Label)',
        el('button', {
          type: 'button', class: 'lbl-x', title: 'entfernen',
          onClick: () => {
            const i = pending.findIndex((x) => x.id === lb.id);
            if (i >= 0) pending.splice(i, 1);
            renderChips();
          },
        }, '×'),
      ])));
    }
    renderChips();
    const addSel = el('select', { class: 'lbl-add' }, [
      el('option', { value: '' }, '+ Label hinzufügen …'),
      ...LABELS.map((l) => el('option', { value: l.id }, l.title)),
    ]);
    addSel.addEventListener('change', () => {
      const id = Number(addSel.value);
      addSel.value = '';
      const lb = LABELS.find((x) => x.id === id);
      if (!lb || pending.some((x) => x.id === id)) return;
      pending.push(lb); renderChips();
    });

    const body = el('div', {}, [
      feld('Titel', title),
      feld('Fällig am', due, 'leer = ohne Fälligkeit'),
      feld('Klasse', klasseSel, 'wird in Vikunja als Label „Klasse: …“ gesetzt'),
      feld('Spalte', bucketSel),
      feld('Priorität', prio),
      feld('Beschreibung', desc),
      feld('Labels', el('div', {}, [chips, addSel])),
    ]);

    modal({
      title: 'Neue Aufgabe',
      body,
      actions: [
        { label: 'Abbrechen', onClick: (close) => close() },
        {
          label: 'Anlegen', kind: 'primary',
          onClick: async (close) => {
            if (!title.value.trim()) { toast('Titel fehlt.'); return; }
            const bucketId = bucketSel.value ? Number(bucketSel.value) : null;
            try {
              const d = await postJSON('/api/vikunja/tasks', {
                title: title.value, due_date: due.value,
                priority: Number(prio.value), description: desc.value,
                bucket_id: bucketId, klasse: klasseSel.value,
                label_ids: pending.map((l) => l.id),
              });
              close();
              toast('Aufgabe angelegt.');
              afterCreate(d.task || {}, bucketId);
            } catch (e) { toast(e.message); }
          },
        },
      ],
    });
    title.focus();
  }

  // Frisch angelegte Aufgabe in beide Ansichten einsetzen, ohne Reload.
  function afterCreate(task, bucketId) {
    insertListItem(task);
    if (!boardLoaded) return;              // Board lädt beim Umschalten ohnehin frisch
    const col = bucketId
      ? boardEl.querySelector('.board-col[data-bucket="' + bucketId + '"]') : null;
    if (!col) { reloadBoard(); return; }   // Standardspalte kennt nur Vikunja
    col.querySelector('.board-cards').appendChild(cardEl(task, bucketId));
    updateCount(col);
  }

  function listItemEl(t) {
    const meta = [];
    if (t.due_date) {
      const d = new Date(t.due_date);
      const overdue = !isNaN(d) && d < todayStart();
      meta.push(el('span', {
        class: 'task-due' + (overdue ? ' is-overdue' : ''), 'data-due': t.due_date,
      }, fmtDate(t.due_date)));
    } else {
      meta.push(el('span', { class: 'muted' }, 'ohne Fälligkeit'));
    }
    if (t.priority >= 3) meta.push(el('span', { class: 'badge task-prio' }, PRIORITY[t.priority] || ''));
    (t.labels || []).forEach((lb) => meta.push(el('span', {
      class: 'badge task-label', style: 'background:' + labelBg(lb.hex_color),
    }, lb.title)));

    return el('li', { class: 'task-item', 'data-id': t.id }, [
      el('input', { type: 'checkbox', class: 'task-check', title: 'Als erledigt markieren' }),
      el('div', { class: 'task-main' }, [
        el('strong', {}, t.title),
        el('div', { class: 'task-meta' }, meta),
      ]),
      el('button', {
        class: 'btn-sec task-del', title: 'Aufgabe löschen',
        style: 'padding:3px 8px;font-size:11px;color:var(--pink);border-color:var(--pink)',
      }, '✕'),
    ]);
  }

  function insertListItem(t) {
    const list = document.getElementById('taskList');
    if (!list || !t.id) return;
    const empty = list.querySelector('.task-empty');
    if (empty) empty.remove();
    // Einsortieren wie der Server: fällige zuerst, undatierte ans Ende.
    const rank = (due) => (due ? '0' + due : '1');
    const r = rank(t.due_date);
    const ref = Array.from(list.querySelectorAll('.task-item')).find((it) => {
      const d = it.querySelector('.task-due');
      return rank(d ? d.dataset.due : '') > r;
    }) || null;
    list.insertBefore(listItemEl(t), ref);
    const count = document.getElementById('taskCount');
    if (count) count.textContent = '(' + list.querySelectorAll('.task-item').length + ')';
  }

  const newBtn = document.getElementById('newTaskBtn');
  if (newBtn) newBtn.addEventListener('click', () => openCreate());
})();
