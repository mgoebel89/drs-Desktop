/* Unterschrift und Paraphe mit Stift oder Finger zeichnen (Einstellungen).
 *
 *   DRSUnterschrift.oeffnen({ art: 'signature'|'paraphe', titel, nachSpeichern })
 *
 * Ablauf: Vollbild-Zeichenfläche → „Fertig" → Vorschau des zugeschnittenen
 * Bildes, so wie es ins PDF kommt → „Übernehmen" lädt es über dieselbe Route
 * hoch wie eine Datei (/profile/signature bzw. /profile/paraphe). Erst dann
 * wird eine vorhandene Unterschrift ersetzt.
 *
 * Das Bild ist ein PNG mit TRANSPARENTEM Hintergrund, eng auf die Schrift
 * zugeschnitten — sonst läge im PDF ein weißer Kasten über der Linie.
 *
 * Stift-Logik wie bei den Unterrichtsbesuchen (ub-zeichnen.js): Sobald ein
 * Stift gemeldet wird, zeichnet nur noch der Stift; die aufgelegte Hand
 * hinterlässt dann keine Striche. Der Andruck steuert die Strichstärke.
 * Gesten-Regel aus dem Projekt: genau EIN Ende-Pfad an pointerup UND
 * pointercancel; pointerdown mit preventDefault + setPointerCapture.
 */
(function () {
  'use strict';
  const US = (window.DRSUnterschrift = window.DRSUnterschrift || {});

  const FARBEN = [{ name: 'Schwarz', wert: '#1a1a1a' }, { name: 'Blau', wert: '#0b3d91' }];
  const BREITE = 1600;          // internes Raster: lange Seite der Fläche
  const STRICH = 5.5;           // Grundstärke bei mittlerem Andruck
  const RAND = 12;              // Luft um die Schrift im zugeschnittenen Bild
  const MAX_BILD = 1200;        // breiter wird das gespeicherte Bild nie

  function merke(schluessel, wert) {
    try {
      if (wert === undefined) return localStorage.getItem(schluessel);
      localStorage.setItem(schluessel, wert);
    } catch (_) { /* privater Modus — dann eben ohne Gedächtnis */ }
    return null;
  }

  // Fester gedrückt = dicker, wie beim Füller. Finger/Maus melden keinen
  // Andruck → gleichmäßige Linie.
  function dicke(p) { return STRICH * (p > 0 ? 0.35 + p * 1.3 : 1); }

  function zeichneStrich(ctx, s, faktor) {
    ctx.strokeStyle = s.f;
    ctx.fillStyle = s.f;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    if (s.p.length === 1) {
      const a = s.p[0];
      ctx.beginPath();
      ctx.arc(a[0] * faktor, a[1] * faktor, dicke(a[2]) * faktor / 2, 0, Math.PI * 2);
      ctx.fill();
      return;
    }
    for (let i = 1; i < s.p.length; i++) {
      const a = s.p[i - 1], b = s.p[i];
      ctx.lineWidth = dicke((a[2] + b[2]) / 2) * faktor;
      ctx.beginPath();
      ctx.moveTo(a[0] * faktor, a[1] * faktor);
      ctx.lineTo(b[0] * faktor, b[1] * faktor);
      ctx.stroke();
    }
  }

  /* Rendert die Striche transparent und eng zugeschnitten → Promise<Blob>. */
  function alsBild(striche) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    striche.forEach((s) => s.p.forEach((pt) => {
      const r = dicke(pt[2]) / 2;
      x0 = Math.min(x0, pt[0] - r); y0 = Math.min(y0, pt[1] - r);
      x1 = Math.max(x1, pt[0] + r); y1 = Math.max(y1, pt[1] + r);
    }));
    x0 -= RAND; y0 -= RAND; x1 += RAND; y1 += RAND;
    const faktor = Math.min(1, MAX_BILD / (x1 - x0));
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.ceil((x1 - x0) * faktor));
    c.height = Math.max(1, Math.ceil((y1 - y0) * faktor));
    const ctx = c.getContext('2d');
    ctx.translate(-x0 * faktor, -y0 * faktor);
    striche.forEach((s) => zeichneStrich(ctx, s, faktor));
    return new Promise((ok) => c.toBlob(ok, 'image/png'));
  }

  /* Vollbild-Zeichenfläche → Promise<striche[] | null>. */
  function zeichnen(titel, vorher) {
    const { el, confirmDanger } = window.DRS;
    // Fläche folgt dem Bildschirm (iPad quer → breit), Raster fest ab Öffnen
    const quer = window.innerWidth >= window.innerHeight;
    const w = BREITE;
    const h = Math.round(BREITE * (quer ? 0.42 : 0.75));
    let striche = vorher ? vorher.slice() : [];
    const verlauf = [];
    let farbe = merke('drs.unterschriftFarbe') || FARBEN[0].wert;
    let nurStift = merke('drs.nurStift') === '1';

    return new Promise((fertig) => {
      const canvas = el('canvas', { class: 'usz-canvas', width: String(w), height: String(h) });
      const ctx = canvas.getContext('2d');
      const linie = el('div', { class: 'usz-linie' });
      const blatt = el('div', { class: 'usz-blatt' }, [canvas, linie]);
      const buehne = el('div', { class: 'usz-buehne' }, blatt);
      const leiste = el('div', { class: 'usz-leiste' });
      const overlay = el('div', { class: 'usz', role: 'dialog', 'aria-label': titel },
        [leiste, el('div', { class: 'usz-hinweis' }, titel + ' — auf der Linie schreiben'), buehne]);

      function alles() {
        ctx.clearRect(0, 0, w, h);
        striche.forEach((s) => zeichneStrich(ctx, s, 1));
      }

      function einpassen() {
        const r = buehne.getBoundingClientRect();
        const f = Math.min((r.width - 24) / w, (r.height - 24) / h);
        blatt.style.width = Math.floor(w * f) + 'px';
        blatt.style.height = Math.floor(h * f) + 'px';
      }

      // ── Eingabe ───────────────────────────────────────────────────
      let aktiv = null;   // { id, s }

      function lage(ev) {
        const r = canvas.getBoundingClientRect();
        return [
          Math.round((ev.clientX - r.left) * w / r.width * 10) / 10,
          Math.round((ev.clientY - r.top) * h / r.height * 10) / 10,
          Math.round((ev.pointerType === 'pen' ? ev.pressure : 0) * 100) / 100,
        ];
      }

      canvas.addEventListener('pointerdown', (ev) => {
        if (ev.pointerType === 'pen' && !nurStift) {
          nurStift = true;            // Stift erkannt → Handballen ab jetzt ignorieren
          merke('drs.nurStift', '1');
          malLeiste();
        }
        if (nurStift && ev.pointerType !== 'pen') return;
        if (ev.button > 0 || aktiv) return;
        ev.preventDefault();
        try { canvas.setPointerCapture(ev.pointerId); } catch (_) { /* Zeiger schon weg */ }
        verlauf.push(striche.slice());
        const s = { f: farbe, p: [lage(ev)] };
        striche.push(s);
        aktiv = { id: ev.pointerId, s };
        zeichneStrich(ctx, s, 1);
      });

      canvas.addEventListener('pointermove', (ev) => {
        if (!aktiv || ev.pointerId !== aktiv.id) return;
        ev.preventDefault();
        const liste = ev.getCoalescedEvents ? ev.getCoalescedEvents() : [];
        (liste.length ? liste : [ev]).forEach((e2) => {
          const pt = lage(e2);
          const s = aktiv.s;
          const letzter = s.p[s.p.length - 1];
          if (Math.abs(letzter[0] - pt[0]) + Math.abs(letzter[1] - pt[1]) < 0.8) return;
          s.p.push(pt);
          zeichneStrich(ctx, { f: s.f, p: [letzter, pt] }, 1);
        });
      });

      function ende(ev) {
        if (!aktiv || (ev && ev.pointerId !== aktiv.id)) return;
        aktiv = null;
      }
      canvas.addEventListener('pointerup', ende);
      canvas.addEventListener('pointercancel', ende);
      canvas.addEventListener('lostpointercapture', ende);

      // ── Leiste ────────────────────────────────────────────────────
      function knopf(inhalt, an, titelText, klick) {
        return el('button', { type: 'button', class: 'usz-k' + (an ? ' an' : ''), title: titelText,
          'aria-label': titelText, 'aria-pressed': an ? 'true' : 'false', onClick: klick }, inhalt);
      }

      function malLeiste() {
        leiste.textContent = '';
        leiste.appendChild(el('button', { type: 'button', class: 'btn-ghost', onClick: abbrechen }, 'Abbrechen'));
        const werkzeuge = el('div', { class: 'usz-werkzeuge' });
        FARBEN.forEach((f) => {
          werkzeuge.appendChild(knopf([el('span', { class: 'usz-farbe', style: 'background:' + f.wert }), f.name],
            farbe === f.wert, 'Tinte ' + f.name, () => {
              farbe = f.wert;
              merke('drs.unterschriftFarbe', f.wert);
              // Eine Unterschrift hat eine Farbe — bereits Geschriebenes zieht mit
              striche.forEach((s) => { s.f = f.wert; });
              alles();
              malLeiste();
            }));
        });
        werkzeuge.appendChild(el('span', { class: 'usz-trenner' }));
        werkzeuge.appendChild(knopf('↶', false, 'Rückgängig', () => {
          if (!verlauf.length) return;
          striche = verlauf.pop();
          alles();
        }));
        werkzeuge.appendChild(knopf('Leeren', false, 'Alles löschen', () => {
          if (!striche.length) return;
          verlauf.push(striche.slice());
          striche = [];
          alles();
        }));
        werkzeuge.appendChild(el('span', { class: 'usz-trenner' }));
        werkzeuge.appendChild(knopf(nurStift ? '✎ Nur Stift' : '☝ Finger', nurStift,
          nurStift ? 'Nur der Stift zeichnet — tippen, damit auch der Finger zeichnet'
            : 'Finger zeichnet — tippen für „nur Stift"',
          () => { nurStift = !nurStift; merke('drs.nurStift', nurStift ? '1' : '0'); malLeiste(); }));
        leiste.appendChild(werkzeuge);
        leiste.appendChild(el('button', { type: 'button', class: 'btn', onClick: fertigKlick }, 'Fertig'));
      }

      // ── Abschluss ─────────────────────────────────────────────────
      function schliessen(ergebnis) {
        window.removeEventListener('resize', einpassen);
        document.removeEventListener('keydown', taste);
        overlay.remove();
        fertig(ergebnis);
      }

      function abbrechen() {
        if (!striche.length) { schliessen(null); return; }
        confirmDanger({
          title: 'Zeichnung verwerfen?',
          text: 'Die Unterschrift wird nicht gespeichert.',
          safe: 'Weiter zeichnen', onSafe: (c) => c(),
          danger: 'Verwerfen', onDanger: (c) => { c(); schliessen(null); },
        });
      }

      function fertigKlick() {
        if (!striche.length) { window.DRS.toast('Bitte erst unterschreiben.'); return; }
        schliessen(striche);
      }

      function taste(ev) { if (ev.key === 'Escape') abbrechen(); }

      malLeiste();
      document.body.appendChild(overlay);
      einpassen();
      alles();
      window.addEventListener('resize', einpassen);
      document.addEventListener('keydown', taste);
    });
  }

  US.oeffnen = async function (opt) {
    const { el, modal, toast } = window.DRS;
    const titel = opt.titel || (opt.art === 'paraphe' ? 'Paraphe' : 'Unterschrift');
    let striche = null;

    for (;;) {
      striche = await zeichnen(titel, striche);
      if (!striche) return;
      const blob = await alsBild(striche);
      const url = URL.createObjectURL(blob);

      // Vorschau: so, wie es im PDF über der Linie erscheint
      const wahl = await new Promise((weiter) => {
        let entschieden = false;
        const dlg = modal({
          title: titel + ' übernehmen?',
          body: el('div', {}, [
            el('p', { class: 'muted' }, 'So erscheint sie auf den PDFs — '
              + (opt.art === 'paraphe' ? 'auf der Lehrer-Zusammenfassung.' : 'über der Unterschriftslinie.')),
            el('div', { class: 'usz-vorschau' }, [
              el('img', { src: url, alt: titel, class: opt.art === 'paraphe' ? 'usz-v-paraphe' : 'usz-v-sig' }),
              el('div', { class: 'usz-v-linie' }),
            ]),
          ]),
          actions: [
            { label: 'Übernehmen', kind: 'primary', onClick: (c) => { entschieden = true; c(); weiter('ok'); } },
            { label: 'Weiter zeichnen', kind: 'sec', onClick: (c) => { entschieden = true; c(); weiter('neu'); } },
          ],
          onClose: () => { if (!entschieden) weiter('abbruch'); },
        });
        return dlg;
      });
      URL.revokeObjectURL(url);
      if (wahl === 'abbruch') return;
      if (wahl === 'neu') continue;

      const fd = new FormData();
      fd.append('file', blob, (opt.art === 'paraphe' ? 'paraphe' : 'unterschrift') + '.png');
      try {
        const r = await fetch('/profile/' + (opt.art === 'paraphe' ? 'paraphe' : 'signature'),
          { method: 'POST', body: fd });
        if (!r.ok) {
          let msg = 'Speichern fehlgeschlagen.';
          try { msg = (await r.json()).detail || msg; } catch (_) { /* kein JSON */ }
          throw new Error(msg);
        }
      } catch (e) {
        toast(e.message || 'Speichern fehlgeschlagen.');
        continue;   // zurück zur Zeichnung, nichts geht verloren
      }
      toast(titel + ' gespeichert.');
      if (opt.nachSpeichern) opt.nachSpeichern();
      return;
    }
  };
})();
