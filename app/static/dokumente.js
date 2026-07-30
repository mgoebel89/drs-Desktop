/* Dokumente: Kachelgalerie auf Paperless, Detail-Overlay, Upload-Assistent.
 *
 * Der Browser kennt weder die Paperless-Adresse noch den Token — alles läuft
 * über /api/dokumente/*. Vorschau und Thumbnails kommen über /dokumente/<id>/
 * datei/<art> ebenfalls aus dem eigenen Server.
 *
 * Zwei Regeln aus früheren Fehlern stecken hier drin:
 * - Nachladende Listen bekommen einen Sequenzzähler; wer schnell tippt, löst
 *   mehrere Abrufe aus, und ohne Zähler rendern alle Antworten in denselben
 *   Container (doppelte Einträge).
 * - Dieses Skript läuft im scripts-Block, also NACH drs.js — sonst wäre
 *   window.DRS beim Verdrahten noch nicht da und kein Knopf täte etwas.
 */
(function () {
  'use strict';
  if (!window.DRS) return;
  const { el, feld, modal, wizard, toast, postJSON, getJSON } = DRS;

  const resultEl = document.getElementById('docResult');
  const chipsEl = document.getElementById('docChips');
  const searchEl = document.getElementById('docSearch');
  const orderEl = document.getElementById('docOrder');
  const moreBtn = document.getElementById('docMore');
  const layoutToggle = document.querySelector('.view-toggle');

  let STAMM = { tags: [], storage_paths: [], correspondents: [], document_types: [] };
  const byId = { tags: new Map(), correspondents: new Map(), document_types: new Map() };

  const state = { query: '', tags: [], ordering: '-created', page: 1, items: [], layout: 'tiles' };
  let seq = 0;

  try { state.layout = localStorage.getItem('docLayout') || 'tiles'; } catch (_) { /* egal */ }

  // ── Helfer ────────────────────────────────────────────────────────────
  function tagColor(hex) {
    const h = (hex || '').trim();
    if (!h) return '#e8eef4';
    return h[0] === '#' ? h : '#' + h;
  }
  // Schrift schwarz oder weiß, je nach Helligkeit der Tag-Farbe.
  function readableOn(hex) {
    const h = tagColor(hex).slice(1);
    if (h.length < 6) return '#111';
    const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#111' : '#fff';
  }
  function fmtDate(iso) {
    if (!iso) return '';
    const p = iso.split('-');
    return p.length === 3 ? p[2] + '.' + p[1] + '.' + p[0] : iso;
  }
  function nameOf(map, id) { const it = map.get(id); return it ? it.name : ''; }

  function tagChipsFor(doc) {
    return el('div', { class: 'doc-tags' }, (doc.tags || []).map((tid) => {
      const t = byId.tags.get(tid);
      if (!t) return null;
      return el('span', {
        class: 'doc-tag',
        style: 'background:' + tagColor(t.color) + ';color:' + readableOn(t.color),
      }, t.name);
    }).filter(Boolean));
  }

  // ── Stammlisten + Filterchips ─────────────────────────────────────────
  async function loadStamm() {
    try {
      const d = await getJSON('/api/dokumente/stammlisten');
      if (!d.ok) return;
      STAMM = d;
      byId.tags = new Map((d.tags || []).map((t) => [t.id, t]));
      byId.correspondents = new Map((d.correspondents || []).map((c) => [c.id, c]));
      byId.document_types = new Map((d.document_types || []).map((t) => [t.id, t]));
      renderChips();
    } catch (_) { /* Filterchips sind Komfort, kein Muss */ }
  }

  function renderChips() {
    if (!chipsEl) return;
    chipsEl.innerHTML = '';
    (STAMM.tags || []).forEach((t) => {
      const aktiv = state.tags.includes(t.id);
      chipsEl.appendChild(el('button', {
        type: 'button', class: 'doc-chip' + (aktiv ? ' active' : ''),
        onClick: () => {
          state.tags = aktiv ? state.tags.filter((x) => x !== t.id) : state.tags.concat([t.id]);
          renderChips();
          neuLaden();
        },
      }, t.name));
    });
  }

  // ── Liste laden ───────────────────────────────────────────────────────
  function params() {
    const p = new URLSearchParams();
    if (state.query) p.set('query', state.query);
    if (state.tags.length) p.set('tags', state.tags.join(','));
    p.set('ordering', state.ordering);
    p.set('page', String(state.page));
    return p.toString();
  }

  async function laden(anhaengen) {
    const my = ++seq;
    if (!anhaengen) resultEl.innerHTML = '<p class="muted" style="margin-top:1.2rem">lädt …</p>';
    let d;
    try {
      d = await getJSON('/api/dokumente/liste?' + params());
    } catch (_) {
      if (my === seq) resultEl.innerHTML = '<div class="flash flash-err" style="display:block">'
        + 'Paperless ist nicht erreichbar.</div>';
      return;
    }
    if (my !== seq) return;                     // eine neuere Anfrage hat übernommen
    if (!d.ok) {
      resultEl.innerHTML = '<div class="flash flash-err" style="display:block">'
        + (d.error || 'Konnte die Dokumente nicht laden.') + '</div>';
      return;
    }
    state.items = anhaengen ? state.items.concat(d.results || []) : (d.results || []);
    if (moreBtn) moreBtn.hidden = !d.has_next;
    render();
  }

  function neuLaden() { state.page = 1; laden(false); }

  function render() {
    resultEl.innerHTML = '';
    if (!state.items.length) {
      resultEl.appendChild(el('p', { class: 'muted', style: 'margin-top:1.2rem' },
        'Keine Dokumente gefunden.'));
      return;
    }
    if (state.layout === 'list') {
      const box = el('div', { style: 'margin-top:1rem' }, state.items.map(listRow));
      resultEl.appendChild(box);
    } else {
      resultEl.appendChild(el('div', { class: 'doc-gallery' }, state.items.map(tile)));
    }
  }

  function metaZeile(doc) {
    const teile = [];
    const k = nameOf(byId.correspondents, doc.correspondent);
    if (k) teile.push(k);
    if (doc.created) teile.push(fmtDate(doc.created));
    return teile.join(' · ');
  }

  function tile(doc) {
    const img = el('img', {
      src: '/dokumente/' + doc.id + '/datei/thumb', alt: '', loading: 'lazy',
    });
    // Kein Thumbnail (z. B. reine Textdatei) → Symbol statt kaputtes Bild.
    img.addEventListener('error', () => { img.replaceWith(document.createTextNode('📄')); });
    return el('button', { type: 'button', class: 'doc-tile', onClick: () => openDetail(doc.id) }, [
      el('div', { class: 'doc-thumb' }, img),
      el('div', { class: 'doc-tile-body' }, [
        el('div', { class: 'doc-tile-title' }, doc.title || '(ohne Titel)'),
        el('div', { class: 'doc-tile-meta' }, metaZeile(doc)),
        tagChipsFor(doc),
      ]),
    ]);
  }

  function listRow(doc) {
    return el('button', { type: 'button', class: 'doc-listrow', onClick: () => openDetail(doc.id) }, [
      el('span', {}, '📄'),
      el('span', { class: 'doc-tile-title' }, doc.title || '(ohne Titel)'),
      tagChipsFor(doc),
      el('span', { class: 'doc-tile-meta', style: 'white-space:nowrap' }, metaZeile(doc)),
    ]);
  }

  // ── Detail-Overlay ────────────────────────────────────────────────────
  async function openDetail(docId) {
    let doc;
    try {
      const d = await getJSON('/api/dokumente/' + docId);
      if (!d.ok) { toast(d.error || 'Dokument nicht ladbar.'); return; }
      doc = d.doc;
    } catch (_) { toast('Dokument nicht ladbar.'); return; }

    const titel = el('input', { value: doc.title || '' });
    const datum = el('input', { type: 'date', value: doc.created || '' });
    const korr = auswahl(STAMM.correspondents, doc.correspondent);
    const typ = auswahl(STAMM.document_types, doc.document_type);
    const tagBox = el('div', { class: 'doc-chips' });
    let tags = (doc.tags || []).slice();

    function renderTagWahl() {
      tagBox.innerHTML = '';
      (STAMM.tags || []).forEach((t) => {
        const aktiv = tags.includes(t.id);
        tagBox.appendChild(el('button', {
          type: 'button', class: 'doc-chip' + (aktiv ? ' active' : ''),
          onClick: () => {
            tags = aktiv ? tags.filter((x) => x !== t.id) : tags.concat([t.id]);
            renderTagWahl();
          },
        }, t.name));
      });
    }
    renderTagWahl();

    const notizen = el('ul', { class: 'doc-notes', style: 'list-style:none;padding:0;margin:.4rem 0' });
    const notizFeld = el('textarea', { rows: '2', placeholder: 'Notiz hinzufügen …' });

    function zeigeNotizen(liste) {
      notizen.innerHTML = '';
      if (!liste.length) {
        notizen.appendChild(el('li', { class: 'muted' }, 'Noch keine Notiz.'));
        return;
      }
      liste.forEach((n) => notizen.appendChild(el('li', {}, [
        el('span', { style: 'flex:1' }, n.note || ''),
        el('button', {
          type: 'button', class: 'btn-sec', style: 'padding:2px 8px',
          onClick: async () => {
            const d = await postJSON('/api/dokumente/' + docId + '/notizen/' + n.id + '/delete', {});
            zeigeNotizen(d.notes || []);
          },
        }, '✕'),
      ])));
    }
    zeigeNotizen(doc.notes || []);

    const body = el('div', { class: 'doc-detail' }, [
      el('div', {}, [
        el('div', { class: 'doc-preview' }, [
          el('embed', { src: '/dokumente/' + docId + '/datei/preview', type: 'application/pdf' }),
        ]),
        el('p', { style: 'margin-top:.6rem' }, [
          el('a', { class: 'btn-sec', href: '/dokumente/' + docId + '/datei/download' },
            '⬇ Original herunterladen'),
        ]),
      ]),
      el('div', {}, [
        feld('Titel', titel),
        feld('Dokumentdatum', datum),
        feld('Korrespondent', korr),
        feld('Dokumenttyp', typ),
        el('div', { class: 'drs-field' }, [
          el('span', { class: 'drs-field-label' }, 'Tags'), tagBox,
        ]),
        el('h4', { style: 'margin:1rem 0 .2rem' }, 'Notizen'),
        notizen,
        notizFeld,
        el('button', {
          type: 'button', class: 'btn-sec', style: 'margin-top:.3rem',
          onClick: async () => {
            const text = notizFeld.value.trim();
            if (!text) return;
            try {
              const d = await postJSON('/api/dokumente/' + docId + '/notizen', { note: text });
              notizFeld.value = '';
              zeigeNotizen(d.notes || []);
            } catch (e) { toast(e.message); }
          },
        }, '+ Notiz speichern'),
      ]),
    ]);

    modal({
      title: doc.title || 'Dokument',
      body: body,
      actions: [
        { label: 'Schließen', kind: 'sec', onClick: (close) => close() },
        {
          label: 'Speichern', kind: 'primary', onClick: async (close) => {
            try {
              await postJSON('/api/dokumente/' + docId + '/save', {
                title: titel.value.trim(),
                created_date: datum.value || null,
                correspondent: korr.value ? Number(korr.value) : null,
                document_type: typ.value ? Number(typ.value) : null,
                tags: tags,
              });
              toast('Gespeichert.');
              close();
              neuLaden();
            } catch (e) { toast(e.message); }
          },
        },
      ],
    });
  }

  function auswahl(liste, wert) {
    const sel = el('select', {}, [el('option', { value: '' }, '— keine —')]
      .concat((liste || []).map((it) => el('option', { value: it.id }, it.name))));
    sel.value = wert ? String(wert) : '';
    return sel;
  }

  // ── Upload-Assistent ──────────────────────────────────────────────────
  function openUpload() {
    const ctx = { file: null, title: '', created: '', correspondent: '', document_type: '', tags: [] };
    let wz = null;

    wz = wizard({
      title: 'Dokument hochladen',
      finishLabel: 'Hochladen',
      ctx: ctx,
      steps: [
        {
          label: 'Datei',
          render(c, host) {
            const input = el('input', { type: 'file', style: 'display:none' });
            const zone = el('div', { class: 'dropzone' },
              c.file ? '📄 ' + c.file.name : 'Datei hierher ziehen oder klicken zum Auswählen');
            const info = el('p', { class: 'muted' });

            function uebernehmen(f) {
              if (!f) return;
              c.file = f;
              // Der Titel ist fast immer der Dateiname ohne Endung — vorbelegen
              // spart den häufigsten Tippvorgang.
              if (!c.title) c.title = f.name.replace(/\.[^.]+$/, '');
              zone.textContent = '📄 ' + f.name;
              info.textContent = Math.round(f.size / 1024) + ' KB';
            }

            zone.addEventListener('click', () => input.click());
            input.addEventListener('change', () => uebernehmen(input.files[0]));
            ['dragenter', 'dragover'].forEach((ev) => zone.addEventListener(ev, (e) => {
              e.preventDefault(); zone.classList.add('over');
            }));
            ['dragleave', 'drop'].forEach((ev) => zone.addEventListener(ev, (e) => {
              e.preventDefault(); zone.classList.remove('over');
            }));
            zone.addEventListener('drop', (e) => uebernehmen(e.dataTransfer.files[0]));

            host.appendChild(zone);
            host.appendChild(input);
            host.appendChild(info);
            host.appendChild(el('p', { class: 'muted' },
              'Der in deinem Profil gewählte Tag und Speicherpfad werden automatisch gesetzt.'));
          },
          validate(c) { return c.file ? null : 'Bitte zuerst eine Datei wählen.'; },
        },
        {
          label: 'Eigenschaften',
          render(c, host) {
            const titel = el('input', { value: c.title, onInput: (e) => { c.title = e.target.value; } });
            const datum = el('input', {
              type: 'date', value: c.created, onInput: (e) => { c.created = e.target.value; },
            });
            const korr = auswahl(STAMM.correspondents, c.correspondent);
            korr.addEventListener('change', () => { c.correspondent = korr.value; });
            const typ = auswahl(STAMM.document_types, c.document_type);
            typ.addEventListener('change', () => { c.document_type = typ.value; });

            const tagBox = el('div', { class: 'doc-chips' });
            function renderTags() {
              tagBox.innerHTML = '';
              (STAMM.tags || []).forEach((t) => {
                const aktiv = c.tags.includes(t.id);
                tagBox.appendChild(el('button', {
                  type: 'button', class: 'doc-chip' + (aktiv ? ' active' : ''),
                  onClick: () => {
                    c.tags = aktiv ? c.tags.filter((x) => x !== t.id) : c.tags.concat([t.id]);
                    renderTags();
                  },
                }, t.name));
              });
            }
            renderTags();

            host.appendChild(feld('Titel', titel));
            host.appendChild(feld('Dokumentdatum', datum, 'Leer lassen, wenn Paperless es selbst erkennen soll.'));
            host.appendChild(feld('Korrespondent', korr));
            host.appendChild(feld('Dokumenttyp', typ));
            host.appendChild(el('div', { class: 'drs-field' }, [
              el('span', { class: 'drs-field-label' }, 'Weitere Tags'), tagBox,
            ]));
          },
          validate(c) { return c.title.trim() ? null : 'Bitte einen Titel eingeben.'; },
        },
      ],
      async onFinish(c) {
        const fd = new FormData();
        fd.append('datei', c.file);
        fd.append('title', c.title.trim());
        fd.append('created', c.created || '');
        fd.append('correspondent', c.correspondent || '0');
        fd.append('document_type', c.document_type || '0');
        fd.append('tags', c.tags.join(','));

        const r = await fetch('/api/dokumente/upload', { method: 'POST', body: fd });
        let d = null;
        try { d = await r.json(); } catch (_) { /* kein JSON */ }
        if (!r.ok || !d || !d.ok) {
          throw new Error((d && d.error) || 'Der Upload ist fehlgeschlagen.');
        }
        if (wz) wz.close();
        toast('Hochgeladen — Paperless verarbeitet die Datei …');
        warteAufTask(d.task_id);
      },
    });
  }

  /* Paperless verarbeitet Uploads asynchron (OCR). Wir fragen ein paar Mal
   * nach und laden die Liste neu, sobald das Dokument da ist; danach geben
   * wir auf, statt endlos zu pollen. */
  function warteAufTask(taskId) {
    if (!taskId) { setTimeout(neuLaden, 4000); return; }
    let versuche = 0;
    const timer = setInterval(async () => {
      versuche += 1;
      if (versuche > 20) { clearInterval(timer); neuLaden(); return; }
      try {
        const d = await getJSON('/api/dokumente/task/' + encodeURIComponent(taskId));
        if (!d.ok) return;
        if (d.status === 'SUCCESS') {
          clearInterval(timer);
          toast('Dokument ist in Paperless angekommen.');
          neuLaden();
        } else if (d.status === 'FAILURE') {
          clearInterval(timer);
          toast('Paperless meldet einen Fehler: ' + (d.error || 'unbekannt'), 5000);
        }
      } catch (_) { /* nächster Versuch */ }
    }, 3000);
  }

  // ── Verdrahtung ───────────────────────────────────────────────────────
  let tippTimer = null;
  if (searchEl) searchEl.addEventListener('input', () => {
    clearTimeout(tippTimer);
    tippTimer = setTimeout(() => { state.query = searchEl.value.trim(); neuLaden(); }, 350);
  });
  if (orderEl) orderEl.addEventListener('change', () => {
    state.ordering = orderEl.value; neuLaden();
  });
  if (moreBtn) moreBtn.addEventListener('click', () => { state.page += 1; laden(true); });
  const reloadBtn = document.getElementById('docReload');
  if (reloadBtn) reloadBtn.addEventListener('click', neuLaden);
  const uploadBtn = document.getElementById('uploadBtn');
  if (uploadBtn) uploadBtn.addEventListener('click', openUpload);

  if (layoutToggle) {
    layoutToggle.addEventListener('click', (e) => {
      const b = e.target.closest('.vt-btn');
      if (!b) return;
      state.layout = b.dataset.layout;
      try { localStorage.setItem('docLayout', state.layout); } catch (_) { /* egal */ }
      layoutToggle.querySelectorAll('.vt-btn').forEach((x) =>
        x.classList.toggle('active', x.dataset.layout === state.layout));
      render();
    });
    layoutToggle.querySelectorAll('.vt-btn').forEach((x) =>
      x.classList.toggle('active', x.dataset.layout === state.layout));
  }

  // Stammlisten und erste Seite parallel — ein hängender Abruf soll den
  // anderen nicht aufhalten (12 s Server-Timeout je Aufruf).
  loadStamm();
  laden(false);
})();
