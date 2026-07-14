/* Geteilte UI-Bausteine: Icons, Toast, Modal, Bestätigung, Vollbild-Assistent.
 *
 * Bewusst Vanilla-JS im Namespace DRS (Vorbild: die Gemeindeverwaltung). Die App
 * bleibt server-gerendert; diese Datei liefert nur die Interaktionsschicht —
 * Karten öffnen ein Detail-Modal, Anlegen läuft über einen Assistenten.
 *
 * Grundsatz beim Assistenten: Es wird ERST AM ENDE gespeichert, in einem
 * einzigen Request. Ein Abbruch hinterlässt damit nie ein halbes Objekt.
 */
(function () {
  'use strict';
  const DRS = (window.DRS = window.DRS || {});

  // ---------- DOM-Helfer ----------

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') node.className = v;
      else if (k === 'html') node.innerHTML = v;
      else if (k.startsWith('on') && typeof v === 'function') {
        node.addEventListener(k.slice(2).toLowerCase(), v);
      } else node.setAttribute(k, v === true ? '' : v);
    }
    const list = Array.isArray(children) ? children : (children == null ? [] : [children]);
    for (const c of list) {
      if (c == null || c === false) continue;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return node;
  }

  // Inline-SVG wie in der Seitenleiste: erbt die Textfarbe, bleibt überall scharf.
  const ICONS = {
    jahrgang: '<path d="M22 10 12 5 2 10l10 5 10-5z"/><path d="M6 12v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5"/>',
    lerngruppe: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13A4 4 0 0 1 16 11"/>',
    fach: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    pruefen: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    klasse: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 20V10"/>',
    schueler: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    trash: '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    wand: '<path d="M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8 19 13M15 9h0M17.8 6.2 19 5M3 21l9-9M12.2 6.2 11 5"/>',
  };

  function icon(name, size) {
    const s = size || 20;
    const svg = `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
      stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ''}</svg>`;
    return el('span', { class: 'drs-icon', html: svg, 'aria-hidden': 'true' });
  }

  // Ersetzt <span data-icon="jahrgang"> im server-gerenderten HTML durch das SVG.
  // So bleibt das Template lesbar und die Icons leben an einer Stelle.
  function mountIcons(root) {
    (root || document).querySelectorAll('[data-icon]').forEach((node) => {
      const name = node.dataset.icon;
      if (!ICONS[name]) return;
      node.replaceWith(icon(name, node.dataset.size ? Number(node.dataset.size) : 20));
    });
  }

  // ---------- Toast ----------

  function toast(text, ms) {
    let t = document.getElementById('drsToast');
    if (!t) {
      t = el('div', { id: 'drsToast', class: 'drs-toast' });
      document.body.appendChild(t);
    }
    t.textContent = text;
    t.classList.add('show');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove('show'), ms || 2400);
  }

  // ---------- HTTP ----------

  async function postJSON(url, data) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data || {}),
    });
    let payload = null;
    try { payload = await r.json(); } catch (_) { /* kein JSON */ }
    if (!r.ok) {
      throw new Error((payload && (payload.detail || payload.error)) || 'Serverfehler');
    }
    return payload;
  }

  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error('Serverfehler');
    return r.json();
  }

  // ---------- Modal ----------

  // opts: { title, body (Node), actions: [{label, kind, onClick(close)}], onClose }
  function modal(opts) {
    const overlay = el('div', { class: 'drs-overlay' });
    const foot = el('div', { class: 'drs-modal-foot' });

    function close() {
      overlay.remove();
      document.removeEventListener('keydown', onKey);
      if (opts.onClose) opts.onClose();
    }
    function onKey(e) { if (e.key === 'Escape') close(); }

    for (const a of opts.actions || []) {
      foot.appendChild(el('button', {
        class: a.kind === 'primary' ? 'btn' : (a.kind === 'danger' ? 'btn btn-danger' : 'btn-sec'),
        type: 'button',
        onClick: () => a.onClick(close),
      }, a.label));
    }
    if (!(opts.actions || []).length) {
      foot.appendChild(el('button', { class: 'btn-sec', type: 'button', onClick: close }, 'Schließen'));
    }

    const box = el('div', { class: 'drs-modal' }, [
      el('div', { class: 'drs-modal-head' }, [
        el('h3', {}, opts.title || ''),
        el('button', { class: 'drs-x', type: 'button', 'aria-label': 'Schließen', onClick: close }, '×'),
      ]),
      el('div', { class: 'drs-modal-body' }, opts.body || null),
      foot,
    ]);

    overlay.appendChild(box);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    const first = box.querySelector('input, select, textarea, button');
    if (first) first.focus();
    return { close, box };
  }

  /* Bestätigung mit Auswirkungen.
   * In dieser App wird fast nie hart gelöscht, sondern stillgelegt — deshalb zeigt
   * der Dialog erst, was dranhängt, und bietet das Stilllegen als sicheren Ausweg an.
   * opts: { title, text, facts: [{label, wert}], danger: 'Löschen', safe: 'Stilllegen',
   *         onDanger(close), onSafe(close) }
   */
  function confirmDanger(opts) {
    const body = el('div', {}, [
      opts.text ? el('p', {}, opts.text) : null,
      (opts.facts || []).length
        ? el('ul', { class: 'drs-facts' }, opts.facts.map(f =>
            el('li', {}, [el('strong', {}, String(f.wert)), ' ' + f.label])))
        : null,
      // Was das endgültige Löschen mitreißt — steht bewusst als Warnbox da,
      // nicht als grauer Kleintext.
      opts.warnung
        ? el('p', { class: 'flash flash-warn', style: 'display:block' }, opts.warnung)
        : null,
      opts.hinweis ? el('p', { class: 'muted' }, opts.hinweis) : null,
    ]);
    const actions = [];
    if (opts.safe && opts.onSafe) {
      actions.push({ label: opts.safe, kind: 'sec', onClick: (c) => opts.onSafe(c) });
    }
    if (opts.danger && opts.onDanger) {
      actions.push({ label: opts.danger, kind: 'danger', onClick: (c) => opts.onDanger(c) });
    }
    return modal({ title: opts.title || 'Sicher?', body, actions });
  }

  /* Vollbild-Assistent.
   *
   * steps: [{ key, label, render(ctx, body), validate(ctx) -> null | 'Fehlertext' }]
   * ctx  : frei beschreibbares Objekt, das alle Schritte teilen (der Entwurf).
   * onFinish(ctx) -> Promise. Erst hier wird gespeichert.
   */
  function wizard(opts) {
    const steps = opts.steps || [];
    const ctx = opts.ctx || {};
    let i = 0;
    let busy = false;

    const chips = steps.map((s, n) => el('div', { class: 'wiz-step' }, [
      el('span', { class: 'wiz-num' }, String(n + 1)),
      el('span', { class: 'wiz-label' }, s.label),
    ]));
    const body = el('div', { class: 'wiz-body' });
    const fehler = el('div', { class: 'flash flash-err', style: 'display:none' });
    const hint = el('span', { class: 'wiz-hint' }, 'Es wird erst am Ende gespeichert.');
    const zurueck = el('button', { class: 'btn-sec', type: 'button', onClick: () => go(i - 1) }, '‹ Zurück');
    const weiter = el('button', { class: 'btn', type: 'button', onClick: next }, 'Weiter ›');

    const overlay = el('div', { class: 'drs-overlay wiz-overlay' }, [
      el('div', { class: 'wiz' }, [
        el('div', { class: 'wiz-head' }, [
          el('h3', {}, opts.title || 'Assistent'),
          el('div', { class: 'wiz-steps' }, chips),
          el('button', { class: 'drs-x', type: 'button', 'aria-label': 'Abbrechen', onClick: close }, '×'),
        ]),
        fehler, body,
        el('div', { class: 'wiz-foot' }, [zurueck, hint, weiter]),
      ]),
    ]);

    function close() {
      if (busy) return;
      overlay.remove();
      document.removeEventListener('keydown', onKey);
    }
    function onKey(e) { if (e.key === 'Escape') close(); }

    function zeigeFehler(text) {
      fehler.textContent = text || '';
      fehler.style.display = text ? 'block' : 'none';
    }

    function go(n) {
      if (n < 0 || n >= steps.length) return;
      i = n;
      zeigeFehler('');
      body.innerHTML = '';
      steps[i].render(ctx, body);
      chips.forEach((c, k) => {
        c.classList.toggle('active', k === i);
        c.classList.toggle('done', k < i);
      });
      zurueck.style.visibility = i === 0 ? 'hidden' : 'visible';
      weiter.textContent = i === steps.length - 1 ? (opts.finishLabel || 'Anlegen') : 'Weiter ›';
      hint.textContent = i === steps.length - 1
        ? 'Jetzt wird gespeichert.' : 'Es wird erst am Ende gespeichert.';
    }

    async function next() {
      if (busy) return;
      const problem = steps[i].validate ? steps[i].validate(ctx) : null;
      if (problem) { zeigeFehler(problem); return; }
      if (i < steps.length - 1) { go(i + 1); return; }

      busy = true;
      weiter.disabled = true;
      weiter.textContent = 'Speichert…';
      try {
        await opts.onFinish(ctx);
      } catch (e) {
        busy = false;
        weiter.disabled = false;
        weiter.textContent = opts.finishLabel || 'Anlegen';
        zeigeFehler(e.message || 'Konnte nicht speichern.');
      }
    }

    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    go(0);
    return { close, ctx };
  }

  // ---------- Kleine Formular-Bausteine für die Assistenten ----------

  function feld(label, input, hinweis) {
    return el('label', { class: 'drs-field' }, [
      el('span', { class: 'drs-field-label' }, label),
      input,
      hinweis ? el('span', { class: 'muted' }, hinweis) : null,
    ]);
  }

  // Aufklappbarer "Erweitert"-Bereich — dort wohnt der unveränderliche Schlüssel.
  function erweitert(inhalt) {
    return el('details', { class: 'drs-adv' }, [
      el('summary', {}, 'Erweitert'),
      el('div', { class: 'drs-adv-body' }, inhalt),
    ]);
  }

  Object.assign(DRS, {
    el, icon, mountIcons, toast, modal, confirmDanger, wizard, feld, erweitert,
    postJSON, getJSON,
  });
})();
