/* Unterrichtsbesuche — Erfassung vom Handy.
 *
 * Unten die Kategorie-Knöpfe, darüber der Verlauf, oben die aktuelle Phase.
 * Ein Tipp auf einen Knopf öffnet ein Blatt von unten; Speichern schickt den
 * Eintrag SOFORT an den Server. Schlägt das fehl, bleibt das Blatt mit dem
 * Text offen — eine Notiz geht nie stillschweigend verloren.
 *
 * Die Uhrzeit kommt vom Gerät (der Container läuft in UTC).
 * Fotos werden vor dem Hochladen auf max. 1600 px verkleinert: spart Zeit
 * über das VPN und reicht für den Ausdruck.
 */
(function () {
  'use strict';
  if (!window.DRS || !window.UB || !window.UBC) return;
  const { el, modal, toast, confirmDanger, postJSON } = DRS;
  const { piktogramm, jetzt, sortiere, nachId, hell, verlauf, chipWahl } = UBC;

  const B = window.UB.besuch;
  const KATALOG = window.UB.katalog;
  const ICONS = window.UB.icons;
  const WERTUNGEN = window.UB.wertungen;
  const KAT = nachId(KATALOG.kategorien);
  const PHASEN = nachId(KATALOG.phasen);
  let EINTRAEGE = B.eintraege || [];

  const listeEl = document.getElementById('ubeListe');
  const verlaufEl = document.getElementById('ubeVerlauf');

  // ── Zeichnen ────────────────────────────────────────────────────────

  function aktuellePhase() {
    let p = null;
    EINTRAEGE.forEach(function (e) { if (e.art === 'phase') p = e; });
    return p;
  }

  function zeichne(scrollZuId) {
    sortiere(EINTRAEGE);
    verlauf(verlaufEl, EINTRAEGE, {
      katalog: KATALOG, icons: ICONS, wertungen: WERTUNGEN, schwerpunkte: B.schwerpunkte,
      leertext: 'Tippe unten auf „Eintrag“, um etwas festzuhalten — eingeordnet wird danach. '
        + 'Oben setzt du die Unterrichtsphase.',
      onClick: function (e) { if (e.art === 'phase') phasenBlatt(e); else eintragBlatt(e, null); },
    });
    const p = aktuellePhase();
    document.getElementById('ubePhaseName').textContent =
      p ? (PHASEN[p.phase_id] ? PHASEN[p.phase_id].name : 'Phase') + ' seit ' + p.zeit : 'Phase setzen';
    if (scrollZuId) {
      const node = verlaufEl.querySelector('[data-id="' + scrollZuId + '"]');
      if (node) node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  function zeichneInfo() {
    const box = document.getElementById('ubeInfo');
    const teile = [];
    if (B.lernziele) teile.push(el('div', {}, [el('strong', {}, 'Lernziele: '), B.lernziele]));
    if (B.schwerpunkte.length) {
      teile.push(el('div', { style: 'margin-top:.3rem' }, [el('strong', {}, 'Beratungsschwerpunkte'),
        el('ol', {}, B.schwerpunkte.map(function (s) { return el('li', {}, s.text); }))]));
    }
    if (!teile.length) return;
    box.appendChild(el('details', { class: 'ube-info', style: 'margin-top:.5rem' }, [
      el('summary', { style: 'cursor:pointer;font-weight:600;color:var(--blau)' },
        'Lernziele & Beratungsschwerpunkte'),
      el('div', { style: 'margin-top:.4rem;white-space:pre-wrap' }, teile),
    ]));
  }

  function zeichneKnoepfe() {
    const fuss = document.getElementById('ubeFuss');
    fuss.textContent = '';
    // Schnellweg fürs Tafelbild: erst das Foto, dann einordnen
    const schnellKamera = fotoWaehler(true, function (blob) { eintragBlatt(null, blob); });
    fuss.appendChild(el('button', { type: 'button', class: 'ube-neu',
      onClick: function () { eintragBlatt(null, null); } },
    [piktogramm(ICONS, 'plus', 26, 2.2), el('span', {}, 'Eintrag')]));
    fuss.appendChild(el('button', { type: 'button', class: 'ube-foto-schnell', 'aria-label': 'Foto aufnehmen',
      onClick: function () { schnellKamera.click(); } },
    [piktogramm(ICONS, 'kamera', 24, 2), el('span', {}, 'Foto')]));
  }

  // ── Blatt (von unten; mit `oben: true` von oben) ────────────────────

  function blatt(opts) {
    const fuss = el('div', { class: 'ube-blatt-fuss' });
    const overlay = el('div', { class: 'ube-blatt-overlay' + (opts.oben ? ' oben' : '') });
    function close() {
      overlay.remove();
      if (opts.onClose) opts.onClose();
      document.removeEventListener('keydown', onKey);
    }
    function onKey(ev) { if (ev.key === 'Escape') (opts.onCancel || close)(); }
    const box = el('div', { class: 'ube-blatt', role: 'dialog', 'aria-modal': 'true' }, [
      el('div', { class: 'ube-blatt-kopf' }, [].concat(opts.kopf || [], opts.oben ? [] : [
        el('button', { type: 'button', class: 'drs-x', 'aria-label': 'Schließen',
          onClick: function () { (opts.onCancel || close)(); } }, '×'),
      ])),
      el('div', { class: 'ube-blatt-inhalt' }, opts.inhalt),
      (opts.fuss || []).length ? fuss : null,
    ]);
    (opts.fuss || []).forEach(function (n) { fuss.appendChild(n); });
    overlay.appendChild(box);
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    return { close: close, overlay: overlay };
  }

  function seg(optionen, wert, onWahl, faerben) {
    const box = el('div', { class: 'ube-seg' });
    function mal() {
      box.textContent = '';
      optionen.forEach(function (o) {
        const aktiv = o.wert === wert;
        const b = el('button', { type: 'button', class: aktiv ? 'aktiv' : '',
          onClick: function () { wert = o.wert; onWahl(o.wert); mal(); } },
        [o.icon ? piktogramm(ICONS, o.icon, 18) : null, el('span', {}, o.label)]);
        if (aktiv && o.farbe) {
          b.style.borderColor = o.farbe;
          b.style.color = faerben ? '#fff' : o.farbe;
          b.style.background = faerben ? o.farbe : hell(o.farbe, 0.1);
        }
        box.appendChild(b);
      });
    }
    mal();
    return box;
  }

  // fetch wirft bei fehlendem Netz einen TypeError („Failed to fetch") —
  // das soll im Klassenraum niemand übersetzen müssen.
  function fehlertext(err) {
    if (!err || err instanceof TypeError || !err.message) return 'keine Verbindung zum Server';
    return err.message;
  }

  function feldReihe(label, inhalt) {
    return el('div', { class: 'ube-reihe' }, [el('span', { class: 'drs-field-label' }, label), inhalt]);
  }

  // ── Fotos ───────────────────────────────────────────────────────────

  async function verkleinere(datei) {
    const MAX = 1600;
    let bild;
    try {
      bild = await createImageBitmap(datei, { imageOrientation: 'from-image' });
    } catch (_) {
      bild = await new Promise(function (ok, fehl) {
        const i = new Image();
        i.onload = function () { ok(i); };
        i.onerror = fehl;
        i.src = URL.createObjectURL(datei);
      });
    }
    const w = bild.width, h = bild.height;
    const f = Math.min(1, MAX / Math.max(w, h));
    const c = document.createElement('canvas');
    c.width = Math.round(w * f);
    c.height = Math.round(h * f);
    c.getContext('2d').drawImage(bild, 0, 0, c.width, c.height);
    return new Promise(function (ok) { c.toBlob(ok, 'image/jpeg', 0.82); });
  }

  async function ladeFotoHoch(eid, blob) {
    const fd = new FormData();
    fd.append('file', blob, 'foto.jpg');
    const r = await fetch('/api/ub/eintraege/' + eid + '/foto', { method: 'POST', body: fd });
    let d = null;
    try { d = await r.json(); } catch (_) { /* kein JSON */ }
    if (!r.ok) throw new Error((d && d.detail) || 'Foto-Upload fehlgeschlagen');
    return d.eintrag;
  }

  // ── Eintrag anlegen / bearbeiten ────────────────────────────────────

  // Foto-Auswahl: zwei getrennte Wege, weil iPhone und Android ohne
  // `capture` unterschiedlich fragen. `capture="environment"` öffnet auf
  // beiden direkt die Rückkamera; ohne `capture` kommt die Galerie.
  function fotoWaehler(mitKamera, onDatei) {
    const input = el('input', { type: 'file', accept: 'image/*', style: 'display:none' });
    if (mitKamera) input.setAttribute('capture', 'environment');
    input.addEventListener('change', async function () {
      const f = input.files && input.files[0];
      input.value = '';
      if (!f) return;
      try {
        onDatei(await verkleinere(f));
      } catch (_) {
        toast('Das Foto konnte nicht gelesen werden (Format?). Bitte als JPEG aufnehmen.', 4500);
      }
    });
    document.body.appendChild(input);   // iOS öffnet nur Inputs, die im DOM hängen
    return input;
  }

  // ── Eintrag anlegen / bearbeiten ────────────────────────────────────
  //
  // Erst schreiben, dann einordnen: Text oben, darunter „Was ist es?"
  // (Kategorie, PFLICHT, keine Vorbelegung — Ereignisse kommen in beliebiger
  // Folge) und „Wozu?" (Beratungsschwerpunkt, optional). Das Blatt kommt von
  // OBEN, damit Text und Knöpfe über der Handytastatur sichtbar bleiben;
  // Speichern sitzt deshalb im Kopf.

  function eintragBlatt(e, startFoto) {
    const neu = !e;
    const d = {
      kategorie_id: neu ? null : e.kategorie_id,
      kriterium_id: neu ? null : e.kriterium_id,
      wertung: neu ? '' : (e.wertung || ''),
      fotoNeu: startFoto || null, fotoWeg: false,
    };
    let busy = false;

    const zeit = el('input', { type: 'time', value: neu ? jetzt() : (e.zeit || ''), 'aria-label': 'Uhrzeit' });
    const text = el('textarea', { placeholder: 'Was passiert gerade?', rows: '3' });
    text.value = neu ? '' : (e.text || '');

    // Was ist es? — Kategorie
    const kats = KATALOG.kategorien.filter(function (k) { return k.active || k.id === d.kategorie_id; });
    const katReihe = feldReihe('Was ist es?', chipWahl(
      kats.map(function (k) { return { id: k.id, name: k.name, icon: k.icon, farbe: k.farbe }; }),
      d.kategorie_id ? [d.kategorie_id] : [], false,
      function (w) { d.kategorie_id = w[0] || null; katReihe.classList.remove('fehlt'); }, ICONS));

    // Wozu? — Beratungsschwerpunkt: die gewählten des Besuchs vorn, der Rest hinter „weitere"
    const gewaehlt = B.schwerpunkte.map(function (s) { return s.id; });
    const alle = KATALOG.kriterien.filter(function (k) { return k.active || k.id === d.kriterium_id; });
    const vorn = alle.filter(function (k) { return gewaehlt.indexOf(k.id) >= 0; });
    const rest = alle.filter(function (k) { return gewaehlt.indexOf(k.id) < 0; });
    let restOffen = !vorn.length || !!(d.kriterium_id && gewaehlt.indexOf(d.kriterium_id) < 0);
    const wozuBox = el('div');
    function malWozu() {
      wozuBox.textContent = '';
      const zeigen = restOffen ? vorn.concat(rest) : vorn;
      if (!alle.length) {
        wozuBox.appendChild(el('span', { class: 'muted' }, 'Keine Beratungsschwerpunkte angelegt.'));
        return;
      }
      wozuBox.appendChild(chipWahl(zeigen.map(function (k) { return { id: k.id, name: k.name }; }),
        d.kriterium_id ? [d.kriterium_id] : [], false,
        function (w) { d.kriterium_id = w[0] || null; }));
      if (vorn.length && rest.length) {
        wozuBox.appendChild(el('button', { type: 'button', class: 'ub-weitere',
          onClick: function () { restOffen = !restOffen; malWozu(); } },
        restOffen ? 'weniger ▴' : 'weitere (' + rest.length + ') ▾'));
      }
    }
    malWozu();

    const wKeys = Object.keys(WERTUNGEN).sort(function (a, b) { return WERTUNGEN[a].pos - WERTUNGEN[b].pos; });
    const wertung = seg([{ wert: '', label: 'Keine' }].concat(wKeys.map(function (k) {
      return { wert: k, label: WERTUNGEN[k].label, icon: WERTUNGEN[k].icon, farbe: WERTUNGEN[k].farbe };
    })), d.wertung, function (v) { d.wertung = v; });

    // Foto
    const fotoBox = el('div', { class: 'ube-foto-box' });
    let vorschauUrl = d.fotoNeu ? URL.createObjectURL(d.fotoNeu) : (neu ? '' : (e.foto || ''));
    function nimmFoto(blob) {
      d.fotoNeu = blob; d.fotoWeg = false;
      vorschauUrl = URL.createObjectURL(blob);
      malFoto();
    }
    const kamera = fotoWaehler(true, nimmFoto);
    const galerie = fotoWaehler(false, nimmFoto);
    function malFoto() {
      fotoBox.textContent = '';
      if (vorschauUrl) fotoBox.appendChild(el('img', { src: vorschauUrl, alt: 'Foto' }));
      fotoBox.appendChild(el('button', { type: 'button', class: 'btn-sec',
        onClick: function () { kamera.click(); } },
      [piktogramm(ICONS, 'kamera', 18), vorschauUrl ? ' Neu aufnehmen' : ' Kamera']));
      fotoBox.appendChild(el('button', { type: 'button', class: 'btn-sec',
        onClick: function () { galerie.click(); } }, [piktogramm(ICONS, 'bild', 18), ' Galerie']));
      if (vorschauUrl) {
        fotoBox.appendChild(el('button', { type: 'button', class: 'btn-ghost btn-sm',
          onClick: function () { d.fotoNeu = null; d.fotoWeg = true; vorschauUrl = ''; malFoto(); } }, 'Entfernen'));
      }
    }
    malFoto();

    const inhalt = [
      text,
      katReihe,
      feldReihe('Wozu? (Beratungsschwerpunkt)', wozuBox),
      feldReihe('Wertung', wertung),
      feldReihe('Foto', fotoBox),
    ];
    if (!neu) {
      inhalt.push(el('div', { style: 'margin-top:1.2rem;padding-top:.8rem;border-top:1px solid var(--border)' }, [
        el('button', { type: 'button', class: 'btn-danger', onClick: loeschen }, 'Eintrag löschen')]));
    }

    const speichernBtn = el('button', { type: 'button', class: 'btn', onClick: speichern }, 'Speichern');
    const bl = blatt({
      oben: true,
      kopf: [
        el('button', { type: 'button', class: 'btn-ghost', onClick: abbrechen }, 'Abbrechen'),
        el('h3', {}, neu ? 'Neu' : 'Eintrag'),
        zeit,
        speichernBtn,
      ],
      inhalt: inhalt,
      onCancel: abbrechen,
      onClose: function () { kamera.remove(); galerie.remove(); },
    });
    // Im selben Tipp fokussieren — nur dann öffnet iOS die Tastatur.
    // Kommt der Eintrag über die Kamera, bleibt die Tastatur zu.
    if (neu && !startFoto) text.focus();

    function geaendert() {
      if (neu) return !!(text.value.trim() || d.fotoNeu || d.kategorie_id || d.kriterium_id);
      return text.value.trim() !== (e.text || '') || !!d.fotoNeu || d.fotoWeg
        || d.kategorie_id !== e.kategorie_id || d.kriterium_id !== e.kriterium_id
        || d.wertung !== (e.wertung || '');
    }

    function abbrechen() {
      if (!geaendert()) { bl.close(); return; }
      confirmDanger({
        title: 'Änderungen verwerfen?',
        text: 'Was du eingegeben hast, geht verloren.',
        safe: 'Weiter bearbeiten', onSafe: function (c) { c(); },
        danger: 'Verwerfen', onDanger: function (c) { c(); bl.close(); },
      });
    }

    async function speichern() {
      if (busy) return;
      const t = text.value.trim();
      const hatFoto = d.fotoNeu || (!neu && e.foto && !d.fotoWeg);
      if (!d.kategorie_id) {
        katReihe.classList.add('fehlt');
        katReihe.scrollIntoView({ block: 'center', behavior: 'smooth' });
        toast('Bitte wählen: Was ist es?');
        return;
      }
      if (!t && !hatFoto) { toast('Bitte einen Text eingeben oder ein Foto anhängen.'); return; }
      const daten = {
        kategorie_id: d.kategorie_id, kriterium_id: d.kriterium_id,
        zeit: zeit.value || jetzt(), text: t, wertung: d.wertung,
      };
      busy = true;
      speichernBtn.disabled = true;
      speichernBtn.textContent = 'Speichert…';
      let eintrag;
      try {
        if (neu) {
          daten.foto_folgt = !!d.fotoNeu;
          const r = await postJSON('/api/ub/besuche/' + B.id + '/eintraege', daten);
          eintrag = r.eintrag;
          if (r.status) B.status = r.status;
          EINTRAEGE.push(eintrag);
        } else {
          const r = await postJSON('/api/ub/eintraege/' + e.id + '/save', daten);
          eintrag = r.eintrag;
          Object.assign(e, eintrag);
        }
      } catch (err) {
        // Nichts gespeichert: Blatt bleibt offen, alles bleibt stehen.
        busy = false;
        speichernBtn.disabled = false;
        speichernBtn.textContent = 'Speichern';
        toast('Nicht gespeichert: ' + fehlertext(err) + ' — bitte erneut tippen.', 4500);
        return;
      }
      bl.close();
      zeichne(eintrag.id);
      // Der Text ist sicher; das Foto kommt hinterher.
      try {
        let neuStand = null;
        if (d.fotoNeu) {
          toast('Foto wird hochgeladen …');
          neuStand = await ladeFotoHoch(eintrag.id, d.fotoNeu);
        } else if (d.fotoWeg && !neu) {
          neuStand = (await postJSON('/api/ub/eintraege/' + eintrag.id + '/foto/delete', {})).eintrag;
        }
        if (neuStand) {
          const ziel = EINTRAEGE.find(function (x) { return x.id === eintrag.id; });
          if (ziel) Object.assign(ziel, neuStand);
          zeichne(eintrag.id);
        }
        toast('Gespeichert.');
      } catch (err) {
        toast('Eintrag gespeichert, aber das Foto nicht: ' + fehlertext(err), 5000);
      }
    }

    function loeschen() {
      confirmDanger({
        title: 'Eintrag löschen?',
        text: e.foto ? 'Der Eintrag und sein Foto werden entfernt.' : 'Der Eintrag wird entfernt.',
        danger: 'Löschen',
        onDanger: async function (c) {
          try {
            await postJSON('/api/ub/eintraege/' + e.id + '/delete', {});
            EINTRAEGE = EINTRAEGE.filter(function (x) { return x.id !== e.id; });
            EINTRAEGE.forEach(function (x) { if (x.bezug_id === e.id) x.bezug_id = null; });
            c();
            bl.close();
            zeichne();
            toast('Gelöscht.');
          } catch (err) { toast(fehlertext(err)); }
        },
      });
    }
  }

  // ── Phase setzen / bearbeiten ───────────────────────────────────────

  function phasenBlatt(marker) {
    const neu = !marker;
    const zeit = el('input', { type: 'time', value: neu ? jetzt() : (marker.zeit || ''), 'aria-label': 'Uhrzeit' });
    const aktiv = aktuellePhase();
    let gewaehlt = neu ? null : marker.phase_id;
    let busy = false;
    const grid = el('div', { class: 'ube-phasen' });
    const phasen = KATALOG.phasen.filter(function (p) { return p.active || (!neu && p.id === marker.phase_id); });

    function mal() {
      grid.textContent = '';
      phasen.forEach(function (p) {
        const ist = neu ? (aktiv && aktiv.phase_id === p.id) : gewaehlt === p.id;
        grid.appendChild(el('button', { type: 'button', class: ist ? 'aktiv' : '',
          onClick: function () {
            if (neu) { setze(p.id); return; }   // neu: ein Tipp genügt
            gewaehlt = p.id; mal();
          } }, p.name));
      });
      if (!phasen.length) {
        grid.appendChild(el('a', { href: '/unterrichtsbesuche/einstellungen' }, 'Noch keine Phasen angelegt'));
      }
    }
    mal();

    async function setze(pid) {
      if (busy) return;
      busy = true;
      try {
        if (neu) {
          const r = await postJSON('/api/ub/besuche/' + B.id + '/eintraege',
            { art: 'phase', phase_id: pid, zeit: zeit.value || jetzt() });
          if (r.status) B.status = r.status;
          EINTRAEGE.push(r.eintrag);
          bl.close();
          zeichne(r.eintrag.id);
          toast((PHASEN[pid] || {}).name + ' ab ' + r.eintrag.zeit);
        } else {
          const r = await postJSON('/api/ub/eintraege/' + marker.id + '/save',
            { phase_id: pid, zeit: zeit.value });
          Object.assign(marker, r.eintrag);
          bl.close();
          zeichne(marker.id);
          toast('Gespeichert.');
        }
      } catch (err) {
        busy = false;
        toast('Nicht gespeichert: ' + fehlertext(err), 4500);
      }
    }

    const fuss = [];
    if (!neu) {
      fuss.push(el('button', { type: 'button', class: 'btn-danger', onClick: function () {
        confirmDanger({
          title: 'Phasenwechsel löschen?',
          text: 'Die Einträge danach gehören dann zur vorherigen Phase.',
          danger: 'Löschen',
          onDanger: async function (c) {
            try {
              await postJSON('/api/ub/eintraege/' + marker.id + '/delete', {});
              EINTRAEGE = EINTRAEGE.filter(function (x) { return x.id !== marker.id; });
              c(); bl.close(); zeichne();
            } catch (err) { toast(err.message); }
          },
        });
      } }, 'Löschen'));
    }
    fuss.push(el('span', { class: 'spacer' }));
    fuss.push(el('button', { type: 'button', class: 'btn-sec', onClick: function () { bl.close(); } }, 'Abbrechen'));
    if (!neu) {
      fuss.push(el('button', { type: 'button', class: 'btn', onClick: function () { setze(gewaehlt); } }, 'Speichern'));
    }

    const bl = blatt({
      kopf: [el('h3', {}, neu ? 'Neue Phase beginnt' : 'Phasenwechsel bearbeiten'), zeit],
      inhalt: [el('p', { class: 'muted', style: 'margin:0 0 .6rem;font-size:13px' },
        neu ? 'Tippe die Phase an, die jetzt beginnt.' : 'Phase oder Uhrzeit korrigieren.'), grid],
      fuss: fuss,
    });
  }

  // ── Menü ────────────────────────────────────────────────────────────

  function menue() {
    const abgeschlossen = B.status === 'abgeschlossen';
    const m = modal({
      title: 'Besuch',
      body: el('div', { style: 'display:flex;flex-direction:column;gap:.6rem' }, [
        el('a', { class: 'btn-sec', href: '/unterrichtsbesuche/' + B.id + '/protokoll.pdf', target: '_blank' },
          'Protokoll als PDF öffnen'),
        el('button', { type: 'button', class: 'btn-sec', onClick: async function () {
          try {
            const r = await postJSON('/api/ub/besuche/' + B.id + '/save',
              { status: abgeschlossen ? 'laufend' : 'abgeschlossen' });
            B.status = r.besuch.status;
            m.close();
            if (B.status === 'abgeschlossen') location.href = '/unterrichtsbesuche/' + B.id;
            else toast('Wieder geöffnet.');
          } catch (e) { toast(e.message); }
        } }, abgeschlossen ? 'Besuch wieder öffnen' : 'Besuch abschließen'),
        el('a', { class: 'btn-sec', href: '/unterrichtsbesuche/' + B.id }, 'Details & Kopfdaten'),
        el('a', { class: 'btn-ghost', href: '/unterrichtsbesuche' }, 'Zur Übersicht'),
      ]),
    });
  }

  // ── Bildschirm wach halten ──────────────────────────────────────────
  // Geht nur über HTTPS; über HTTP tut es still nichts.
  let sperre = null;
  async function wachHalten() {
    try {
      if ('wakeLock' in navigator && document.visibilityState === 'visible') {
        sperre = await navigator.wakeLock.request('screen');
      }
    } catch (_) { sperre = null; }
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') wachHalten();
  });

  function uhr() {
    document.getElementById('ubeUhr').textContent = jetzt();
  }

  document.getElementById('ubePhase').addEventListener('click', function () { phasenBlatt(null); });
  document.getElementById('ubeMenue').addEventListener('click', menue);
  zeichneInfo();
  zeichneKnoepfe();
  zeichne();
  listeEl.scrollTop = listeEl.scrollHeight;
  uhr();
  setInterval(uhr, 15000);
  wachHalten();
})();
