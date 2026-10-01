/* Unterrichtsbesuche — Zeichenfläche für Handschrift und Skizzen.
 *
 *   const r = await UBC.zeichnen({ hintergrund: url|Blob|null, skizze: {…}|null });
 *   r === null              → abgebrochen, nichts ändern
 *   r.loeschen === true     → alle Striche entfernt
 *   r = { daten, bild }     → daten = Striche (JSON, zum Weiterzeichnen),
 *                             bild  = gerendertes Bild (Blob) für Verlauf/Protokoll
 *
 * Stift oder Finger: Sobald einmal ein Stift (Apple Pencil, S-Pen) gemeldet
 * wird, zeichnet NUR noch der Stift — die aufgelegte Hand hinterlässt dann
 * keine Striche. Die Wahl merkt sich das Gerät (localStorage) und lässt sich
 * in der Leiste umschalten. Auf Handys ohne Stift zeichnet der Finger.
 *
 * Gesten-Regel aus dem Projekt: genau EIN Ende-Pfad, an pointerup UND
 * pointercancel gehängt; pointerdown mit preventDefault + setPointerCapture.
 * Sonst bleibt bei einer vom Browser übernommenen Geste ein Strich „kleben".
 *
 * Koordinaten liegen im Bildraster (Breite × Höhe des Hintergrunds bzw.
 * 1600 × 1200 / hochkant 1200 × 1600), nicht in Bildschirmpixeln — so passt eine Skizze auf jedem
 * Gerät wieder genau aufs Foto.
 */
(function () {
  'use strict';
  const UBC = (window.UBC = window.UBC || {});

  const FARBEN = ['#1a1a1a', '#00639C', '#C62828', '#2E7D32'];
  const STAERKEN = { fein: 3, mittel: 6, dick: 12 };   // bezogen auf 1600 px lange Seite
  const SPEICHER = 'ub.nurStift';

  function speicher(lesen, wert) {
    try {
      if (lesen) return localStorage.getItem(SPEICHER) === '1';
      localStorage.setItem(SPEICHER, wert ? '1' : '0');
    } catch (_) { /* privater Modus o. ä. — dann eben ohne Gedächtnis */ }
    return false;
  }

  function ladeBild(quelle) {
    return new Promise(function (ok, fehl) {
      if (!quelle) { ok(null); return; }
      const img = new Image();
      img.onload = function () { ok(img); };
      img.onerror = fehl;
      img.src = typeof quelle === 'string' ? quelle : URL.createObjectURL(quelle);
    });
  }

  UBC.zeichnen = async function (opt) {
    const { el, confirmDanger } = window.DRS;
    const alt = opt.skizze || null;
    let bg = null;
    try { bg = await ladeBild(opt.hintergrund); } catch (_) { bg = null; }

    // Leeres Blatt folgt der Haltung des Geräts: iPad hochkant → Hochformat
    const hochkant = window.innerHeight > window.innerWidth;
    const w = alt ? alt.w : (bg ? bg.naturalWidth : (hochkant ? 1200 : 1600));
    const h = alt ? alt.h : (bg ? bg.naturalHeight : (hochkant ? 1600 : 1200));
    const massstab = Math.max(w, h) / 1600;
    let striche = alt ? JSON.parse(JSON.stringify(alt.striche || [])) : [];
    const verlaufStapel = [];
    let farbe = FARBEN[0];
    let staerke = 'mittel';
    let radierer = false;
    let nurStift = speicher(true);
    let geaendert = false;

    return new Promise(function (fertig) {
      const canvas = el('canvas', { class: 'ubz-canvas', width: String(w), height: String(h) });
      const ctx = canvas.getContext('2d');
      const buehne = el('div', { class: 'ubz-buehne' }, canvas);
      const leiste = el('div', { class: 'ubz-leiste' });
      const overlay = el('div', { class: 'ubz', role: 'dialog', 'aria-label': 'Zeichnen' }, [leiste, buehne]);

      // ── Zeichnen ────────────────────────────────────────────────────
      function druck(p) { return p > 0 ? 0.45 + p * 1.1 : 1; }

      function segment(s, a, b) {
        ctx.strokeStyle = s.f;
        ctx.lineWidth = STAERKEN[s.b] * massstab * druck((a[2] + b[2]) / 2);
        ctx.beginPath();
        ctx.moveTo(a[0], a[1]);
        ctx.lineTo(b[0], b[1]);
        ctx.stroke();
      }

      function punkt(s, a) {
        ctx.fillStyle = s.f;
        ctx.beginPath();
        ctx.arc(a[0], a[1], STAERKEN[s.b] * massstab * druck(a[2]) / 2, 0, Math.PI * 2);
        ctx.fill();
      }

      function strich(s) {
        if (s.p.length === 1) { punkt(s, s.p[0]); return; }
        for (let i = 1; i < s.p.length; i++) segment(s, s.p[i - 1], s.p[i]);
      }

      function alles() {
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        if (bg) ctx.drawImage(bg, 0, 0, w, h);
        else { ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, w, h); }
        striche.forEach(strich);
      }

      // Canvas so groß wie möglich in die Bühne einpassen
      function einpassen() {
        const r = buehne.getBoundingClientRect();
        const f = Math.min((r.width - 16) / w, (r.height - 16) / h);
        canvas.style.width = Math.floor(w * f) + 'px';
        canvas.style.height = Math.floor(h * f) + 'px';
      }

      // ── Eingabe ─────────────────────────────────────────────────────
      let aktiv = null;   // { id, s }

      function lage(ev) {
        const r = canvas.getBoundingClientRect();
        return [
          Math.round((ev.clientX - r.left) * w / r.width * 10) / 10,
          Math.round((ev.clientY - r.top) * h / r.height * 10) / 10,
          Math.round((ev.pointerType === 'pen' ? ev.pressure : 0) * 100) / 100,
        ];
      }

      function merken() {
        verlaufStapel.push(striche.slice());
        if (verlaufStapel.length > 80) verlaufStapel.shift();
      }

      // Abstand Punkt–Teilstück: Eine schnell gezogene Gerade hat nur zwei
      // Stützpunkte — wer nur die Punkte prüfte, könnte ihre Mitte nicht radieren.
      function abstand(pt, a, b) {
        const dx = b[0] - a[0], dy = b[1] - a[1];
        const l2 = dx * dx + dy * dy;
        const t = l2 ? Math.max(0, Math.min(1, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / l2)) : 0;
        return Math.hypot(pt[0] - (a[0] + t * dx), pt[1] - (a[1] + t * dy));
      }

      function radiere(pt) {
        const r = 22 * massstab;
        const vorher = striche.length;
        striche = striche.filter(function (s) {
          if (s.p.length === 1) return abstand(pt, s.p[0], s.p[0]) > r;
          for (let i = 1; i < s.p.length; i++) {
            if (abstand(pt, s.p[i - 1], s.p[i]) <= r) return false;
          }
          return true;
        });
        if (striche.length !== vorher) { geaendert = true; alles(); }
      }

      canvas.addEventListener('pointerdown', function (ev) {
        if (ev.pointerType === 'pen' && !nurStift) {
          nurStift = true;            // Stift erkannt → ab jetzt Handballen ignorieren
          speicher(false, true);
          malLeiste();
        }
        if (nurStift && ev.pointerType !== 'pen') return;
        if (ev.button > 0 || aktiv) return;
        ev.preventDefault();
        try { canvas.setPointerCapture(ev.pointerId); } catch (_) { /* Zeiger schon weg */ }
        merken();
        const pt = lage(ev);
        if (radierer) {
          aktiv = { id: ev.pointerId, s: null };
          radiere(pt);
          return;
        }
        const s = { f: farbe, b: staerke, p: [pt] };
        striche.push(s);
        aktiv = { id: ev.pointerId, s: s };
        geaendert = true;
        ctx.lineCap = 'round';
        punkt(s, pt);
      });

      canvas.addEventListener('pointermove', function (ev) {
        if (!aktiv || ev.pointerId !== aktiv.id) return;
        ev.preventDefault();
        const liste = ev.getCoalescedEvents ? ev.getCoalescedEvents() : [ev];
        (liste.length ? liste : [ev]).forEach(function (e2) {
          const pt = lage(e2);
          if (radierer) { radiere(pt); return; }
          const s = aktiv.s;
          const letzter = s.p[s.p.length - 1];
          if (Math.abs(letzter[0] - pt[0]) + Math.abs(letzter[1] - pt[1]) < 0.8) return;
          s.p.push(pt);
          segment(s, letzter, pt);
        });
      });

      function ende(ev) {
        if (!aktiv || (ev && ev.pointerId !== aktiv.id)) return;
        aktiv = null;
      }
      canvas.addEventListener('pointerup', ende);
      canvas.addEventListener('pointercancel', ende);
      canvas.addEventListener('lostpointercapture', ende);

      // ── Leiste ──────────────────────────────────────────────────────
      function knopf(inhalt, an, titel, klick) {
        return el('button', { type: 'button', class: 'ubz-k' + (an ? ' an' : ''), title: titel,
          'aria-label': titel, 'aria-pressed': an ? 'true' : 'false', onClick: klick }, inhalt);
      }

      function malLeiste() {
        leiste.textContent = '';
        leiste.appendChild(el('button', { type: 'button', class: 'ubz-text', onClick: abbrechen }, 'Abbrechen'));
        const werkzeuge = el('div', { class: 'ubz-werkzeuge' });
        FARBEN.forEach(function (f) {
          werkzeuge.appendChild(knopf(el('span', { class: 'ubz-farbe', style: 'background:' + f }),
            !radierer && farbe === f, 'Farbe', function () { farbe = f; radierer = false; malLeiste(); }));
        });
        werkzeuge.appendChild(el('span', { class: 'ubz-trenner' }));
        Object.keys(STAERKEN).forEach(function (k) {
          const d = { fein: 4, mittel: 8, dick: 14 }[k];
          werkzeuge.appendChild(knopf(el('span', { class: 'ubz-punkt', style: 'width:' + d + 'px;height:' + d + 'px' }),
            !radierer && staerke === k, 'Strich ' + k, function () { staerke = k; radierer = false; malLeiste(); }));
        });
        werkzeuge.appendChild(el('span', { class: 'ubz-trenner' }));
        werkzeuge.appendChild(knopf('Radierer', radierer, 'Radierer: ganze Striche entfernen',
          function () { radierer = !radierer; malLeiste(); }));
        werkzeuge.appendChild(knopf('↶', false, 'Rückgängig', function () {
          if (!verlaufStapel.length) return;
          striche = verlaufStapel.pop();
          geaendert = true;
          alles();
        }));
        werkzeuge.appendChild(knopf('Leeren', false, 'Alles löschen', function () {
          if (!striche.length) return;
          merken();
          striche = [];
          geaendert = true;
          alles();
        }));
        werkzeuge.appendChild(el('span', { class: 'ubz-trenner' }));
        werkzeuge.appendChild(knopf(nurStift ? '✎ Nur Stift' : '☝ Finger', nurStift,
          nurStift ? 'Nur der Stift zeichnet — tippen, damit auch der Finger zeichnet'
            : 'Finger zeichnet — tippen für „nur Stift"',
          function () { nurStift = !nurStift; speicher(false, nurStift); malLeiste(); }));
        leiste.appendChild(werkzeuge);
        leiste.appendChild(el('button', { type: 'button', class: 'btn', onClick: uebernehmen }, 'Fertig'));
      }

      // ── Abschluss ───────────────────────────────────────────────────
      function schliessen(ergebnis) {
        window.removeEventListener('resize', einpassen);
        document.removeEventListener('keydown', taste);
        overlay.remove();
        fertig(ergebnis);
      }

      function abbrechen() {
        if (!geaendert) { schliessen(null); return; }
        confirmDanger({
          title: 'Zeichnung verwerfen?',
          text: 'Die Striche seit dem Öffnen gehen verloren.',
          safe: 'Weiter zeichnen', onSafe: function (c) { c(); },
          danger: 'Verwerfen', onDanger: function (c) { c(); schliessen(null); },
        });
      }

      function uebernehmen() {
        if (!geaendert) { schliessen(null); return; }
        if (!striche.length) { schliessen({ loeschen: true }); return; }
        alles();
        // Auf Fotos JPEG (kleiner), leere Blätter PNG (scharfe Linien)
        const typ = bg ? 'image/jpeg' : 'image/png';
        canvas.toBlob(function (blob) {
          schliessen({
            daten: { v: 1, w: w, h: h, hintergrund: bg ? 'foto' : 'leer', striche: striche },
            bild: blob,
          });
        }, typ, 0.86);
      }

      function taste(ev) { if (ev.key === 'Escape') abbrechen(); }

      malLeiste();
      document.body.appendChild(overlay);
      einpassen();
      alles();
      window.addEventListener('resize', einpassen);
      document.addEventListener('keydown', taste);
    });
  };
})();
