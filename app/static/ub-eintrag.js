/* Unterrichtsbesuche — der Eintrags-Editor (Blatt für Eintrag und Phase).
 *
 * Gemeinsam genutzt von der Handy-Erfassung und der Detailseite (Nachbereitung
 * am PC). Wer ihn nutzt, übergibt den Zustand:
 *
 *   const ed = UBC.editor({
 *     besuch, katalog, icons, wertungen,
 *     zustand: { eintraege: [...] },   // wird vom Editor verändert
 *     zeichne: function (scrollZuId) { … },
 *   });
 *   ed.eintragBlatt(eintragOderNull, startFotoBlob)
 *   ed.phasenBlatt(markerOderNull)
 *   ed.fotoWaehler(mitKamera, onBlob)
 *
 * Grundsätze (von Matthias so entschieden):
 * - Erst schreiben, dann einordnen. Kategorie ist PFLICHT und wird NIE
 *   vorbelegt — Ereignisse kommen in beliebiger Folge.
 * - Jeder Eintrag wird sofort gespeichert; schlägt das fehl, bleibt das Blatt
 *   mit allem offen.
 * - Das Eintragsblatt kommt von OBEN, damit es über der Handytastatur bleibt.
 */
(function () {
  'use strict';
  const UBC = (window.UBC = window.UBC || {});

  UBC.editor = function (opt) {
    const { el, toast, confirmDanger, postJSON } = window.DRS;
    const { piktogramm, jetzt, nachId, hell, chipWahl } = UBC;
    const B = opt.besuch;
    const KATALOG = opt.katalog;
    const ICONS = opt.icons;
    const WERTUNGEN = opt.wertungen;
    const KAT = nachId(KATALOG.kategorien);
    const PHASEN = nachId(KATALOG.phasen);
    const Z = opt.zustand;

    function aktuellePhase() {
      let p = null;
      Z.eintraege.forEach(function (e) { if (e.art === 'phase') p = e; });
      return p;
    }

    // ── Blatt (von unten; mit `oben: true` von oben) ──────────────────

    function blatt(o) {
      const fuss = el('div', { class: 'ube-blatt-fuss' });
      const overlay = el('div', { class: 'ube-blatt-overlay' + (o.oben ? ' oben' : '') });
      function close() {
        overlay.remove();
        if (o.onClose) o.onClose();
        document.removeEventListener('keydown', onKey);
      }
      function onKey(ev) { if (ev.key === 'Escape') (o.onCancel || close)(); }
      const box = el('div', { class: 'ube-blatt', role: 'dialog', 'aria-modal': 'true' }, [
        el('div', { class: 'ube-blatt-kopf' }, [].concat(o.kopf || [], o.oben ? [] : [
          el('button', { type: 'button', class: 'drs-x', 'aria-label': 'Schließen',
            onClick: function () { (o.onCancel || close)(); } }, '×'),
        ])),
        el('div', { class: 'ube-blatt-inhalt' }, o.inhalt),
        (o.fuss || []).length ? fuss : null,
      ]);
      (o.fuss || []).forEach(function (n) { fuss.appendChild(n); });
      overlay.appendChild(box);
      document.addEventListener('keydown', onKey);
      document.body.appendChild(overlay);
      return { close: close, overlay: overlay };
    }

    function seg(optionen, wert, onWahl) {
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
            b.style.color = o.farbe;
            b.style.background = hell(o.farbe, 0.1);
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

    function kurz(t, n) {
      t = String(t || '').replace(/\s+/g, ' ').trim();
      return t.length > n ? t.slice(0, n - 1) + '…' : t;
    }

    // ── Fotos ─────────────────────────────────────────────────────────

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

    async function ladeSkizzeHoch(eid, sk) {
      const fd = new FormData();
      fd.append('file', sk.bild, sk.bild.type === 'image/jpeg' ? 'skizze.jpg' : 'skizze.png');
      fd.append('striche', JSON.stringify(sk.daten));
      const r = await fetch('/api/ub/eintraege/' + eid + '/skizze', { method: 'POST', body: fd });
      let d = null;
      try { d = await r.json(); } catch (_) { /* kein JSON */ }
      if (!r.ok) throw new Error((d && d.detail) || 'Skizze konnte nicht gespeichert werden');
      return d.eintrag;
    }

    // Zwei getrennte Wege, weil iPhone und Android ohne `capture`
    // unterschiedlich fragen. `capture="environment"` öffnet auf beiden direkt
    // die Rückkamera; ohne `capture` kommt die Galerie.
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

    // ── Eintrag anlegen / bearbeiten ──────────────────────────────────

    function eintragBlatt(e, startFoto, startSkizze) {
      const neu = !e;
      const d = {
        kategorie_id: neu ? null : e.kategorie_id,
        kriterium_id: neu ? null : e.kriterium_id,
        bezug_id: neu ? null : (e.bezug_id || null),
        wertung: neu ? '' : (e.wertung || ''),
        fotoNeu: startFoto || null, fotoWeg: false,
        skizzeNeu: startSkizze || null, skizzeWeg: false,
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
        function (w) { d.kategorie_id = w[0] || null; katReihe.classList.remove('fehlt'); malBezug(); }, ICONS));

      // Bezieht sich auf … — nur für Kommentar-Kategorien (Idee, Anmerkung …)
      const bezugReihe = feldReihe('Bezieht sich auf', el('div'));
      let bezugAlle = false;
      function istKommentar() {
        const k = KAT[d.kategorie_id];
        return !!(k && k.spalte === 'kommentar');
      }
      function malBezug() {
        const box = bezugReihe.lastChild;
        box.textContent = '';
        if (!istKommentar()) { bezugReihe.style.display = 'none'; return; }
        bezugReihe.style.display = '';
        // Verlaufs-Einträge (Spalte „verlauf"), jüngste zuerst
        const ziele = Z.eintraege.filter(function (x) {
          const k = KAT[x.kategorie_id];
          return x.art === 'eintrag' && (!e || x.id !== e.id) && (!k || k.spalte !== 'kommentar');
        }).slice().reverse();
        if (!ziele.length) {
          box.appendChild(el('span', { class: 'muted' }, 'Noch keine Beobachtung, auf die sich das beziehen kann.'));
          return;
        }
        const idx = ziele.findIndex(function (x) { return x.id === d.bezug_id; });
        if (idx >= 5) bezugAlle = true;
        const zeigen = bezugAlle ? ziele : ziele.slice(0, 5);
        box.appendChild(chipWahl(zeigen.map(function (x) {
          return { id: x.id, name: (x.zeit ? x.zeit + ' · ' : '') + kurz(x.text || 'Foto', 38) };
        }), d.bezug_id ? [d.bezug_id] : [], false, function (w) { d.bezug_id = w[0] || null; }));
        if (ziele.length > 5) {
          box.appendChild(el('button', { type: 'button', class: 'ub-weitere',
            onClick: function () { bezugAlle = !bezugAlle; malBezug(); } },
          bezugAlle ? 'weniger ▴' : 'ältere (' + (ziele.length - 5) + ') ▾'));
        }
      }

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

      // Foto & Skizze — eine Zeile, weil beides „das Bild zum Eintrag" ist
      const fotoBox = el('div', { class: 'ube-foto-box' });
      function hatFotoJetzt() { return !!d.fotoNeu || (!neu && !!e.foto && !d.fotoWeg); }
      function hatSkizzeJetzt() { return !!d.skizzeNeu || (!neu && !!e.skizze && !d.skizzeWeg); }
      function vorschau() {
        if (d.skizzeNeu) return URL.createObjectURL(d.skizzeNeu.bild);
        if (d.fotoNeu) return URL.createObjectURL(d.fotoNeu);
        if (!neu && e.skizze && !d.skizzeWeg) return e.skizze;
        if (!neu && e.foto && !d.fotoWeg) return e.foto;
        return '';
      }
      function nimmFoto(blob) {
        // Eine auf dem alten Foto gezeichnete Skizze passt nicht mehr zum neuen
        if (d.skizzeNeu && d.skizzeNeu.daten.hintergrund === 'foto') d.skizzeNeu = null;
        d.fotoNeu = blob; d.fotoWeg = false;
        malFoto();
      }
      const kamera = fotoWaehler(true, nimmFoto);
      const galerie = fotoWaehler(false, nimmFoto);
      async function zeichnen() {
        let alt = d.skizzeNeu ? d.skizzeNeu.daten : null;
        if (!alt && !neu && e.skizze && !d.skizzeWeg) {
          try {
            alt = (await window.DRS.getJSON('/api/ub/eintraege/' + e.id + '/skizze')).skizze;
          } catch (err) { toast('Skizze konnte nicht geladen werden: ' + fehlertext(err)); return; }
        }
        // Hintergrund ist das Foto — außer eine bestehende Skizze war ein leeres Blatt
        let hg = null;
        if (!(alt && alt.hintergrund === 'leer')) {
          hg = d.fotoNeu || (!neu && e.foto && !d.fotoWeg ? e.foto : null);
        }
        if (alt && alt.hintergrund === 'foto' && !hg) alt = null;   // Foto inzwischen weg
        const r = await UBC.zeichnen({ hintergrund: hg, skizze: alt });
        if (!r) return;
        if (r.loeschen) { d.skizzeNeu = null; d.skizzeWeg = true; } else { d.skizzeNeu = r; d.skizzeWeg = false; }
        malFoto();
      }
      function malFoto() {
        fotoBox.textContent = '';
        const url = vorschau();
        if (url) fotoBox.appendChild(el('img', { src: url, alt: 'Bild zum Eintrag' }));
        fotoBox.appendChild(el('button', { type: 'button', class: 'btn-sec',
          onClick: function () { kamera.click(); } },
        [piktogramm(ICONS, 'kamera', 18), hatFotoJetzt() ? ' Neues Foto' : ' Kamera']));
        fotoBox.appendChild(el('button', { type: 'button', class: 'btn-sec',
          onClick: function () { galerie.click(); } }, [piktogramm(ICONS, 'bild', 18), ' Galerie']));
        fotoBox.appendChild(el('button', { type: 'button', class: 'btn-sec', onClick: zeichnen },
          [piktogramm(ICONS, 'stift', 18),
            hatSkizzeJetzt() ? ' Skizze bearbeiten' : (hatFotoJetzt() ? ' Auf Foto zeichnen' : ' Zeichnen')]));
        if (url) {
          fotoBox.appendChild(el('button', { type: 'button', class: 'btn-ghost btn-sm',
            onClick: function () {
              d.fotoNeu = null; d.fotoWeg = true; d.skizzeNeu = null; d.skizzeWeg = true; malFoto();
            } }, 'Entfernen'));
        }
      }
      malFoto();

      const inhalt = [
        text,
        katReihe,
        bezugReihe,
        feldReihe('Wozu? (Beratungsschwerpunkt)', wozuBox),
        feldReihe('Wertung', wertung),
        feldReihe('Foto / Skizze', fotoBox),
      ];
      malBezug();
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
      // Kommt der Eintrag über Kamera oder Skizze, bleibt die Tastatur zu.
      if (neu && !startFoto && !startSkizze) text.focus();

      function geaendert() {
        if (neu) return !!(text.value.trim() || d.fotoNeu || d.skizzeNeu || d.kategorie_id || d.kriterium_id);
        return text.value.trim() !== (e.text || '') || !!d.fotoNeu || d.fotoWeg
          || !!d.skizzeNeu || d.skizzeWeg
          || d.kategorie_id !== e.kategorie_id || d.kriterium_id !== e.kriterium_id
          || d.wertung !== (e.wertung || '') || d.bezug_id !== (e.bezug_id || null)
          || zeit.value !== (e.zeit || '');
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
        if (!d.kategorie_id) {
          katReihe.classList.add('fehlt');
          katReihe.scrollIntoView({ block: 'center', behavior: 'smooth' });
          toast('Bitte wählen: Was ist es?');
          return;
        }
        if (!t && !hatFotoJetzt() && !hatSkizzeJetzt()) {
          toast('Bitte einen Text eingeben, ein Foto anhängen oder etwas zeichnen.');
          return;
        }
        const daten = {
          kategorie_id: d.kategorie_id, kriterium_id: d.kriterium_id,
          bezug_id: istKommentar() ? d.bezug_id : null,
          zeit: zeit.value || jetzt(), text: t, wertung: d.wertung,
        };
        busy = true;
        speichernBtn.disabled = true;
        speichernBtn.textContent = 'Speichert…';
        let eintrag;
        try {
          if (neu) {
            daten.foto_folgt = !!(d.fotoNeu || d.skizzeNeu);
            const r = await postJSON('/api/ub/besuche/' + B.id + '/eintraege', daten);
            eintrag = r.eintrag;
            if (r.status) B.status = r.status;
            Z.eintraege.push(eintrag);
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
        opt.zeichne(eintrag.id);
        // Der Text ist sicher; das Foto kommt hinterher.
        try {
          // Reihenfolge zählt: erst das Foto (der Server verwirft dabei eine
          // Skizze, die auf dem alten Foto lag), dann die neue Skizze.
          let neuStand = null;
          if (d.fotoNeu) {
            toast('Bild wird hochgeladen …');
            neuStand = await ladeFotoHoch(eintrag.id, d.fotoNeu);
          } else if (d.fotoWeg && !neu && e.foto) {
            neuStand = (await postJSON('/api/ub/eintraege/' + eintrag.id + '/foto/delete', {})).eintrag;
          }
          if (d.skizzeNeu) {
            neuStand = await ladeSkizzeHoch(eintrag.id, d.skizzeNeu);
          } else if (d.skizzeWeg && !neu && e.skizze) {
            neuStand = (await postJSON('/api/ub/eintraege/' + eintrag.id + '/skizze/delete', {})).eintrag;
          }
          if (neuStand) {
            const ziel = Z.eintraege.find(function (x) { return x.id === eintrag.id; });
            if (ziel) Object.assign(ziel, neuStand);
            opt.zeichne(eintrag.id);
          }
          toast('Gespeichert.');
        } catch (err) {
          toast('Eintrag gespeichert, aber das Bild nicht: ' + fehlertext(err), 5000);
        }
      }

      function loeschen() {
        confirmDanger({
          title: 'Eintrag löschen?',
          text: (e.foto || e.skizze) ? 'Der Eintrag und sein Bild werden entfernt.' : 'Der Eintrag wird entfernt.',
          danger: 'Löschen',
          onDanger: async function (c) {
            try {
              await postJSON('/api/ub/eintraege/' + e.id + '/delete', {});
              Z.eintraege = Z.eintraege.filter(function (x) { return x.id !== e.id; });
              Z.eintraege.forEach(function (x) { if (x.bezug_id === e.id) x.bezug_id = null; });
              c();
              bl.close();
              opt.zeichne();
              toast('Gelöscht.');
            } catch (err) { toast(fehlertext(err)); }
          },
        });
      }
    }

    // ── Phase setzen / bearbeiten ─────────────────────────────────────

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
            Z.eintraege.push(r.eintrag);
            bl.close();
            opt.zeichne(r.eintrag.id);
            toast((PHASEN[pid] || {}).name + ' ab ' + r.eintrag.zeit);
          } else {
            const r = await postJSON('/api/ub/eintraege/' + marker.id + '/save',
              { phase_id: pid, zeit: zeit.value });
            Object.assign(marker, r.eintrag);
            bl.close();
            opt.zeichne(marker.id);
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
                Z.eintraege = Z.eintraege.filter(function (x) { return x.id !== marker.id; });
                c(); bl.close(); opt.zeichne();
              } catch (err) { toast(fehlertext(err)); }
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

    return { eintragBlatt, phasenBlatt, fotoWaehler, aktuellePhase, fehlertext };
  };

  /* Export-Dialog: Format, Ordnung, Fotos. Vorbelegt mit der Standard-Ordnung
   * aus den Einstellungen. ODT kommt als Download, PDF öffnet im neuen Tab. */
  UBC.exportDialog = function (besuchId, ordnungen, standard) {
    const { el, modal } = window.DRS;
    let format = 'pdf';
    let ordnung = standard || 'chronologisch';
    const fotos = el('input', { type: 'checkbox', checked: true });
    function radios(name, optionen, wert, setze) {
      return el('div', { class: 'ub-radios' }, Object.keys(optionen).map(function (k) {
        const r = el('input', { type: 'radio', name: name, value: k, checked: k === wert });
        r.addEventListener('change', function () { if (r.checked) setze(k); });
        return el('label', {}, [r, ' ' + optionen[k] + (name === 'ubOrd' && k === standard ? ' (Standard)' : '')]);
      }));
    }
    modal({
      title: 'Protokoll ausgeben',
      body: el('div', {}, [
        el('div', { class: 'drs-field' }, [el('span', { class: 'drs-field-label' }, 'Format'),
          radios('ubFmt', { pdf: 'PDF (zum Lesen und Drucken)', odt: 'ODT (zum Weiterbearbeiten in LibreOffice/Word)' },
            format, function (v) { format = v; })]),
        el('div', { class: 'drs-field' }, [el('span', { class: 'drs-field-label' }, 'Ordnung'),
          radios('ubOrd', ordnungen, ordnung, function (v) { ordnung = v; })]),
        el('label', { class: 'sd-check' }, [fotos, ' Fotos einbinden']),
      ]),
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: function (c) { c(); } },
        { label: 'Ausgeben', kind: 'primary', onClick: function (c) {
          const url = '/unterrichtsbesuche/' + besuchId + '/protokoll.' + format
            + '?ordnung=' + encodeURIComponent(ordnung) + '&fotos=' + (fotos.checked ? 1 : 0);
          if (format === 'pdf') window.open(url, '_blank');
          else location.href = url;
          c();
        } },
      ],
    });
  };
})();
