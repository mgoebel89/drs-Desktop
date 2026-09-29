/* Unterrichtsbesuche — gemeinsame Helfer für alle Seiten des Moduls.
 *
 * Die Piktogramme kommen vom Server (window.UB.icons: name → {label, svg}),
 * gebaut aus denselben Zeichenanweisungen wie im PDF. Hier wird nur die
 * SVG-Hülle drumgelegt.
 *
 * Läuft NACH drs.js (scripts-Block), sonst gibt es window.DRS noch nicht.
 */
(function () {
  'use strict';
  const UBC = (window.UBC = window.UBC || {});

  function piktogramm(icons, name, groesse, strich) {
    const i = icons[name] || icons.auge || { svg: '' };
    const s = groesse || 22;
    const span = document.createElement('span');
    span.className = 'ub-picto';
    span.setAttribute('aria-hidden', 'true');
    span.innerHTML = '<svg viewBox="0 0 24 24" width="' + s + '" height="' + s
      + '" fill="none" stroke="currentColor" stroke-width="' + (strich || 1.8)
      + '" stroke-linecap="round" stroke-linejoin="round">' + i.svg + '</svg>';
    return span;
  }

  function fmtDatum(iso) {
    if (!iso) return 'ohne Datum';
    const p = String(iso).split('-');
    return p.length === 3 ? p[2] + '.' + p[1] + '.' + p[0] : iso;
  }

  function wochentag(iso) {
    if (!iso) return '';
    const d = new Date(iso + 'T12:00:00');
    return ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'][d.getDay()] || '';
  }

  // Uhrzeit vom Gerät — der Server läuft in UTC und kennt die Ortszeit nicht.
  function jetzt() {
    const d = new Date();
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }

  function heute() {
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
      + '-' + String(d.getDate()).padStart(2, '0');
  }

  // Gleiche Ordnung wie der Server: Uhrzeit, dann Anlegereihenfolge.
  function sortiere(liste) {
    return liste.sort(function (a, b) {
      const za = a.zeit || '99:99', zb = b.zeit || '99:99';
      if (za !== zb) return za < zb ? -1 : 1;
      if (a.position !== b.position) return a.position - b.position;
      return a.id - b.id;
    });
  }

  function nachId(liste) {
    const m = {};
    (liste || []).forEach(function (x) { m[x.id] = x; });
    return m;
  }

  // Leichte Hintergrundfarbe aus der Kategoriefarbe (für Kreise und Chips).
  function hell(hex, alpha) {
    const h = (hex || '#00639C').replace('#', '');
    const r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16),
      b = parseInt(h.substr(4, 2), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + (alpha || 0.12) + ')';
  }

  /* Verlauf zeichnen — dieselbe Darstellung auf der Detailseite und in der
   * Erfassung. ctx: { katalog, icons, wertungen, schwerpunkte, onClick? } */
  function verlauf(box, eintraege, ctx) {
    const kat = nachId(ctx.katalog.kategorien);
    const phasen = nachId(ctx.katalog.phasen);
    const krit = nachId(ctx.katalog.kriterien);
    const sp = nachId(ctx.schwerpunkte);
    box.textContent = '';
    box.classList.add('ubv');
    verlauf._alle = eintraege;
    if (!eintraege.length) {
      box.appendChild(el('div', { class: 'ubv-leer' }, ctx.leertext || 'Noch keine Einträge.'));
      return;
    }
    eintraege.forEach(function (e) {
      let node;
      if (e.art === 'phase') {
        const p = phasen[e.phase_id];
        node = el('div', { class: 'ubv-phase' }, [
          el('span', { class: 'ubv-zeit' }, e.zeit || ''),
          el('span', {}, p ? p.name : 'Phase'),
        ]);
      } else {
        const k = kat[e.kategorie_id] || { name: '?', icon: 'auge', farbe: '#5A6B7D' };
        const meta = [el('span', { class: 'ubv-chip', style: 'color:' + k.farbe + ';background:' + hell(k.farbe) }, k.name)];
        if (e.kriterium_id && krit[e.kriterium_id]) {
          // Gewählte Schwerpunkte des Besuchs hervorheben, andere neutral
          meta.push(el('span', { class: 'ubv-chip' + (sp[e.kriterium_id] ? ' ubv-chip-sp' : '') },
            krit[e.kriterium_id].name));
        }
        const w = ctx.wertungen[e.wertung];
        const kreis = el('span', { class: 'ubv-kreis', style: 'background:' + hell(k.farbe, 0.14) + ';color:' + k.farbe });
        kreis.appendChild(piktogramm(ctx.icons, k.icon, 20));
        const wIcon = el('span', { class: 'ubv-wertung', title: w ? w.label : '' });
        if (w) { wIcon.style.color = w.farbe; wIcon.appendChild(piktogramm(ctx.icons, w.icon, 18)); }
        node = el('div', { class: 'ubv-e' }, [
          el('span', { class: 'ubv-zeit' }, e.zeit || ''),
          kreis,
          el('div', {}, [
            e.text ? el('div', { class: 'ubv-text' }, e.text) : null,
            bezugZeile(e),
            el('div', { class: 'ubv-meta' }, meta),
            e.foto ? el('img', { class: 'ubv-foto', src: e.foto, alt: 'Foto', loading: 'lazy' }) : null,
          ]),
          wIcon,
        ]);
      }
      node.dataset.id = e.id;
      if (ctx.onClick) {
        node.classList.add('ubv-klickbar');
        node.addEventListener('click', function () { ctx.onClick(e); });
      }
      box.appendChild(node);
    });
  }

  function el(tag, attrs, kinder) { return window.DRS.el(tag, attrs, kinder); }

  // „↳ zu 08:14 · Arbeitsauftrag …" — worauf sich ein Kommentar bezieht
  function bezugZeile(e) {
    if (!e.bezug_id || !verlauf._alle) return null;
    const r = verlauf._alle.find(function (x) { return x.id === e.bezug_id; });
    if (!r) return null;
    let t = String(r.text || 'Foto').replace(/\s+/g, ' ').trim();
    if (t.length > 45) t = t.slice(0, 44) + '…';
    return el('div', { class: 'ubv-bezug' }, '↳ zu ' + (r.zeit ? r.zeit + ' · ' : '') + t);
  }

  /* Antippbare Auswahl statt Aufklappmenü.
   * optionen: [{id, name, icon?, farbe?}] · gewaehlt: Array von IDs
   * mehrfach=false: ein zweiter Tipp auf den gewählten Knopf hebt die Wahl auf.
   * onChange(gewaehltNeu) */
  function chipWahl(optionen, gewaehlt, mehrfach, onChange, icons) {
    let wahl = (gewaehlt || []).slice();
    const box = el('div', { class: 'ub-chipwahl' });
    function mal() {
      box.textContent = '';
      optionen.forEach(function (o) {
        const an = wahl.indexOf(o.id) >= 0;
        const b = el('button', { type: 'button', class: an ? 'an' : '', 'aria-pressed': an ? 'true' : 'false',
          onClick: function () {
            if (mehrfach) wahl = an ? wahl.filter(function (x) { return x !== o.id; }) : wahl.concat([o.id]);
            else wahl = an ? [] : [o.id];
            mal();
            onChange(wahl.slice());
          } }, [o.icon && icons ? piktogramm(icons, o.icon, 18) : null, el('span', {}, o.name)]);
        if (o.farbe) {
          b.style.borderColor = o.farbe;
          b.style.color = an ? '#fff' : o.farbe;
          b.style.background = an ? o.farbe : hell(o.farbe, 0.08);
        }
        box.appendChild(b);
      });
    }
    mal();
    box.setzen = function (neu) { wahl = neu.slice(); mal(); };
    return box;
  }

  Object.assign(UBC, { piktogramm, fmtDatum, wochentag, jetzt, heute, sortiere, nachId, hell, verlauf, chipWahl });
})();
