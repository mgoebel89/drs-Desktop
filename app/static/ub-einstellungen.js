/* Unterrichtsbesuche — Einstellungen: Kategorien, Phasen, Kriterien.
 *
 * Jede Liste ist sortierbar (Pfeile statt Ziehen — geht auf dem Handy
 * zuverlässig) und jede Zeile öffnet ein Modal. Löschen nur, solange kein
 * Eintrag daran hängt; sonst bleibt Stilllegen.
 */
(function () {
  'use strict';
  if (!window.DRS || !window.UB || !window.UBC) return;
  const { el, feld, modal, toast, confirmDanger, postJSON } = DRS;
  const { piktogramm, hell } = UBC;

  const DATEN = window.UB.daten;
  const ICONS = window.UB.icons;
  const FARBEN = window.UB.farben;
  const SPALTEN = window.UB.spalten;
  const TITEL = { kategorien: 'Kategorie', phasen: 'Phase', kriterien: 'Beratungsschwerpunkt' };
  const NEU_TITEL = { kategorien: 'Neue Kategorie', phasen: 'Neue Phase', kriterien: 'Neuer Beratungsschwerpunkt' };

  function kreis(o) {
    const k = el('span', { class: 'ube-kreis', style: 'background:' + hell(o.farbe, 0.14) + ';color:' + o.farbe });
    k.appendChild(piktogramm(ICONS, o.icon, 20));
    return k;
  }

  function zeichne(art) {
    const box = document.getElementById('ube-' + art);
    box.textContent = '';
    const liste = DATEN[art];
    if (!liste.length) {
      box.appendChild(el('p', { class: 'muted' }, 'Noch nichts angelegt.'));
      return;
    }
    liste.forEach(function (o, i) {
      const zusatz = [];
      if (art === 'kategorien') zusatz.push(o.spalte === 'kommentar' ? 'Kommentar' : 'Verlauf');
      if (o.nutzung) zusatz.push(o.nutzung + '× benutzt');
      if (!o.active) zusatz.push('stillgelegt');
      box.appendChild(el('div', { class: 'ube-zeile' + (o.active ? '' : ' still') }, [
        art === 'kategorien' ? kreis(o) : null,
        el('span', { class: 'ube-name', onClick: function () { bearbeiten(art, o); } },
          [o.name, zusatz.length ? el('small', {}, zusatz.join(' · ')) : null]),
        el('button', { type: 'button', class: 'ube-pfeil', 'aria-label': 'Nach oben',
          disabled: i === 0, onClick: function () { verschiebe(art, i, -1); } }, '▲'),
        el('button', { type: 'button', class: 'ube-pfeil', 'aria-label': 'Nach unten',
          disabled: i === liste.length - 1, onClick: function () { verschiebe(art, i, 1); } }, '▼'),
      ]));
    });
  }

  async function verschiebe(art, i, richtung) {
    const liste = DATEN[art];
    const j = i + richtung;
    const tmp = liste[i]; liste[i] = liste[j]; liste[j] = tmp;
    zeichne(art);
    try {
      await postJSON('/api/ub/einstellungen/' + art + '/reihenfolge',
        { ids: liste.map(function (o) { return o.id; }) });
    } catch (e) { toast(e.message); }
  }

  // Formular — für Kategorien mit Piktogramm, Farbe und Spalte.
  function formular(art, o) {
    const entwurf = { name: o.name || '', icon: o.icon || 'auge',
      farbe: o.farbe || FARBEN[0][0], spalte: o.spalte || 'verlauf',
      active: o.active !== false };
    const name = el('input', { type: 'text', value: entwurf.name, maxlength: '80' });
    name.addEventListener('input', function () { entwurf.name = name.value; malVorschau(); });
    const knoten = [feld('Name', name)];

    const vorschau = el('span', { class: 'ube-vorschau' });
    function malVorschau() {
      vorschau.textContent = '';
      vorschau.style.background = entwurf.farbe;
      vorschau.appendChild(piktogramm(ICONS, entwurf.icon, 24, 2));
      vorschau.appendChild(document.createTextNode(entwurf.name || 'Vorschau'));
    }

    if (art === 'kategorien') {
      const icons = el('div', { class: 'ube-icons' });
      function malIcons() {
        icons.textContent = '';
        Object.keys(ICONS).forEach(function (k) {
          icons.appendChild(el('button', { type: 'button', title: ICONS[k].label,
            class: entwurf.icon === k ? 'aktiv' : '',
            onClick: function () { entwurf.icon = k; malIcons(); malVorschau(); } },
          piktogramm(ICONS, k, 22)));
        });
      }
      const farben = el('div', { class: 'ube-farben' });
      function malFarben() {
        farben.textContent = '';
        FARBEN.forEach(function (f) {
          farben.appendChild(el('button', { type: 'button', title: f[1],
            class: entwurf.farbe === f[0] ? 'aktiv' : '', style: 'background:' + f[0],
            onClick: function () { entwurf.farbe = f[0]; malFarben(); malVorschau(); } }));
        });
      }
      const spalte = el('select', {}, Object.keys(SPALTEN).map(function (k) {
        return el('option', { value: k }, SPALTEN[k]);
      }));
      spalte.value = entwurf.spalte;
      spalte.addEventListener('change', function () { entwurf.spalte = spalte.value; });
      malIcons(); malFarben(); malVorschau();
      knoten.push(feld('Piktogramm', icons), feld('Farbe', farben),
        feld('Spalte im zweispaltigen Protokoll', spalte,
          'Verlauf = was passiert (links), Kommentar = deine Ideen und Anmerkungen dazu (rechts).'),
        el('div', { class: 'drs-field' }, [el('span', { class: 'drs-field-label' }, 'So sieht der Knopf aus'), vorschau]));
    }
    return { knoten: knoten, entwurf: entwurf };
  }

  function neu(art) {
    const f = formular(art, {});
    modal({
      title: NEU_TITEL[art],
      body: el('div', {}, f.knoten),
      actions: [
        { label: 'Abbrechen', kind: 'sec', onClick: function (c) { c(); } },
        { label: 'Anlegen', kind: 'primary', onClick: async function (c) {
          if (!f.entwurf.name.trim()) { toast('Bitte einen Namen eintragen.'); return; }
          try {
            const r = await postJSON('/api/ub/einstellungen/' + art, f.entwurf);
            DATEN[art].push(r.obj);
            zeichne(art);
            c();
            toast('Angelegt.');
          } catch (e) { toast(e.message); }
        } },
      ],
    });
  }

  async function speichere(art, o, daten, meldung) {
    try {
      const r = await postJSON('/api/ub/einstellungen/' + art + '/' + o.id + '/save', daten);
      Object.assign(o, r.obj);
      zeichne(art);
      toast(meldung || 'Gespeichert.');
      return true;
    } catch (e) { toast(e.message); return false; }
  }

  function entfernen(art, o) {
    const benutzt = o.nutzung > 0;
    confirmDanger({
      title: o.name + ' entfernen?',
      facts: [{ wert: o.nutzung || 0, label: art === 'kriterien' ? 'Verwendungen (Einträge oder Auswahl in Besuchen)' : 'Einträge verwenden das' }],
      text: benutzt
        ? 'Weil Einträge daran hängen, geht nur Stilllegen. Es verschwindet dann aus der Auswahl, '
          + 'alte Protokolle bleiben unverändert.'
        : 'Noch nirgends verwendet — Löschen ist gefahrlos möglich.',
      safe: 'Stilllegen',
      onSafe: async function (c) { c(); await speichere(art, o, { active: false }, 'Stillgelegt.'); },
      danger: benutzt ? null : 'Löschen',
      onDanger: benutzt ? null : async function (c) {
        try {
          await postJSON('/api/ub/einstellungen/' + art + '/' + o.id + '/delete', {});
          DATEN[art] = DATEN[art].filter(function (x) { return x.id !== o.id; });
          zeichne(art);
          c();
          toast('Gelöscht.');
        } catch (e) { toast(e.message); }
      },
    });
  }

  function bearbeiten(art, o) {
    const f = formular(art, o);
    modal({
      title: TITEL[art] + ' bearbeiten',
      body: el('div', {}, f.knoten),
      actions: [
        o.active
          ? { label: 'Stilllegen / Löschen', kind: 'sec', onClick: function (c) { c(); entfernen(art, o); } }
          : { label: 'Reaktivieren', kind: 'sec', onClick: async function (c) {
              if (await speichere(art, o, { active: true }, 'Wieder aktiv.')) c();
            } },
        { label: 'Abbrechen', kind: 'sec', onClick: function (c) { c(); } },
        { label: 'Speichern', kind: 'primary', onClick: async function (c) {
          if (!f.entwurf.name.trim()) { toast('Bitte einen Namen eintragen.'); return; }
          const d = Object.assign({}, f.entwurf);
          delete d.active;
          if (art !== 'kategorien') { delete d.icon; delete d.farbe; delete d.spalte; }
          if (await speichere(art, o, d)) c();
        } },
      ],
    });
  }

  document.querySelectorAll('[data-neu]').forEach(function (b) {
    b.addEventListener('click', function () { neu(b.dataset.neu); });
  });
  Object.keys(TITEL).forEach(zeichne);
})();
