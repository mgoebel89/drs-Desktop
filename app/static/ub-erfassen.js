/* Unterrichtsbesuche — Erfassung vom Handy.
 *
 * Unten „+ Eintrag" und der Foto-Schnellknopf, darüber der Verlauf, oben die
 * aktuelle Phase. Die Blätter (Eintrag, Phase) kommen aus ub-eintrag.js —
 * dieselben wie auf der Detailseite am PC.
 *
 * Die Uhrzeit kommt vom Gerät (der Container läuft in UTC).
 */
(function () {
  'use strict';
  if (!window.DRS || !window.UB || !window.UBC || !window.UBC.editor) return;
  const { el, modal, toast, postJSON } = DRS;
  const { piktogramm, jetzt, sortiere, nachId, verlauf, fmtDatum } = UBC;

  const B = window.UB.besuch;
  const KATALOG = window.UB.katalog;
  const ICONS = window.UB.icons;
  const WERTUNGEN = window.UB.wertungen;
  const PHASEN = nachId(KATALOG.phasen);
  const Z = { eintraege: B.eintraege || [] };

  const listeEl = document.getElementById('ubeListe');
  const verlaufEl = document.getElementById('ubeVerlauf');

  const ed = UBC.editor({
    besuch: B, katalog: KATALOG, icons: ICONS, wertungen: WERTUNGEN,
    zustand: Z, zeichne: zeichne,
  });

  function zeichne(scrollZuId) {
    sortiere(Z.eintraege);
    verlauf(verlaufEl, Z.eintraege, {
      katalog: KATALOG, icons: ICONS, wertungen: WERTUNGEN, schwerpunkte: B.schwerpunkte,
      leertext: 'Tippe unten auf „Eintrag“, um etwas festzuhalten — eingeordnet wird danach. '
        + 'Oben setzt du die Unterrichtsphase.',
      onClick: function (e) { if (e.art === 'phase') ed.phasenBlatt(e); else ed.eintragBlatt(e, null); },
    });
    const p = ed.aktuellePhase();
    document.getElementById('ubePhaseName').textContent =
      p ? (PHASEN[p.phase_id] ? PHASEN[p.phase_id].name : 'Phase') + ' seit ' + p.zeit : 'Phase setzen';
    if (scrollZuId) {
      const node = verlaufEl.querySelector('[data-id="' + scrollZuId + '"]');
      if (node) node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  function zeichneInfo() {
    const box = document.getElementById('ubeInfo');
    // Vereinbarungen vom letzten Mal: offen, damit man sie vor der Stunde sieht
    if (B.vorige) {
      box.appendChild(el('details', { class: 'ube-info ube-vorige', open: true, style: 'margin-top:.5rem' }, [
        el('summary', {}, 'Vereinbarungen vom ' + fmtDatum(B.vorige.datum)),
        el('div', { style: 'margin-top:.3rem;white-space:pre-wrap' }, B.vorige.vereinbarungen),
      ]));
    }
    const teile = [];
    if (B.lernziele) teile.push(el('div', {}, [el('strong', {}, 'Lernziele: '), B.lernziele]));
    if (B.schwerpunkte.length) {
      teile.push(el('div', { style: 'margin-top:.3rem' }, [el('strong', {}, 'Beratungsschwerpunkte'),
        el('ol', {}, B.schwerpunkte.map(function (s) { return el('li', {}, s.text); }))]));
    }
    if (!teile.length) return;
    box.appendChild(el('details', { class: 'ube-info', style: 'margin-top:.5rem' }, [
      el('summary', {}, 'Lernziele & Beratungsschwerpunkte'),
      el('div', { style: 'margin-top:.4rem;white-space:pre-wrap' }, teile),
    ]));
  }

  function zeichneKnoepfe() {
    const fuss = document.getElementById('ubeFuss');
    fuss.textContent = '';
    // Schnellweg fürs Tafelbild: erst das Foto, dann einordnen
    const schnellKamera = ed.fotoWaehler(true, function (blob) { ed.eintragBlatt(null, blob); });
    fuss.appendChild(el('button', { type: 'button', class: 'ube-neu',
      onClick: function () { ed.eintragBlatt(null, null); } },
    [piktogramm(ICONS, 'plus', 26, 2.2), el('span', {}, 'Eintrag')]));
    // Schnellweg für Handschrift/Skizze: erst zeichnen, dann einordnen
    fuss.appendChild(el('button', { type: 'button', class: 'ube-foto-schnell', 'aria-label': 'Skizze zeichnen',
      onClick: async function () {
        const r = await UBC.zeichnen({ hintergrund: null, skizze: null });
        if (r && !r.loeschen) ed.eintragBlatt(null, null, r);
      } },
    [piktogramm(ICONS, 'stift', 24, 2), el('span', {}, 'Skizze')]));
    fuss.appendChild(el('button', { type: 'button', class: 'ube-foto-schnell', 'aria-label': 'Foto aufnehmen',
      onClick: function () { schnellKamera.click(); } },
    [piktogramm(ICONS, 'kamera', 24, 2), el('span', {}, 'Foto')]));
  }

  // ── Menü ────────────────────────────────────────────────────────────

  function menue() {
    const abgeschlossen = B.status === 'abgeschlossen';
    const m = modal({
      title: 'Besuch',
      body: el('div', { style: 'display:flex;flex-direction:column;gap:.6rem' }, [
        el('button', { type: 'button', class: 'btn-sec', onClick: function () {
          m.close();
          UBC.exportDialog(B.id, window.UB.ordnungen, window.UB.standardOrdnung);
        } }, 'Protokoll ausgeben (PDF / ODT)'),
        el('button', { type: 'button', class: 'btn-sec', onClick: async function () {
          try {
            const r = await postJSON('/api/ub/besuche/' + B.id + '/save',
              { status: abgeschlossen ? 'laufend' : 'abgeschlossen' });
            B.status = r.besuch.status;
            m.close();
            if (B.status === 'abgeschlossen') location.href = '/unterrichtsbesuche/' + B.id;
            else toast('Wieder geöffnet.');
          } catch (e) { toast(ed.fehlertext(e)); }
        } }, abgeschlossen ? 'Besuch wieder öffnen' : 'Besuch abschließen'),
        el('a', { class: 'btn-sec', href: '/unterrichtsbesuche/' + B.id }, 'Nachbereitung & Kopfdaten'),
        el('a', { class: 'btn-ghost', href: '/unterrichtsbesuche' }, 'Zur Übersicht'),
      ]),
    });
  }

  // ── Bildschirm wach halten ──────────────────────────────────────────
  // Geht nur über HTTPS; über HTTP tut es still nichts.
  async function wachHalten() {
    try {
      if ('wakeLock' in navigator && document.visibilityState === 'visible') {
        await navigator.wakeLock.request('screen');
      }
    } catch (_) { /* HTTP oder abgelehnt — egal */ }
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') wachHalten();
  });

  function uhr() {
    document.getElementById('ubeUhr').textContent = jetzt();
  }

  document.getElementById('ubePhase').addEventListener('click', function () { ed.phasenBlatt(null); });
  document.getElementById('ubeMenue').addEventListener('click', menue);
  zeichneInfo();
  zeichneKnoepfe();
  zeichne();
  listeEl.scrollTop = listeEl.scrollHeight;
  uhr();
  setInterval(uhr, 15000);
  wachHalten();
})();
