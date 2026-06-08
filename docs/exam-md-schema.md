# Schema: Prüfungs-Markdown

Eine Prüfung (Klassenarbeit, Test, Bewertung) lässt sich als **.md-Datei**
exportieren und importieren. Das Format dient zwei Zwecken:

- **Brücke zur Offline-Feedback-App** (USB-Stick-Workflow ohne Server).
- **Pflege/Versionierung in Obsidian** parallel zur Server-Datenbank.

Pfad-Konvention: irgendwo im Vault oder auf dem USB-Stick, z. B.
`{slug(titel)}_{datum}.md`.

---

## Aufbau

```markdown
---
title: Klassenarbeit Hydraulik
datum: 2026-06-15
klasse: MTA22
lernsituation: hydraulik-grundlagen
lernfeld: LF07
lehrer: M. Goebel
notenskala: mss_noten          # oder: mss_punkte
eingabemodus: numeric          # oder: stages
schema_version: 1
---

# Klassenarbeit Hydraulik

## Schüler
| Nachname    | Vorname | Email             | Moodle-ID |
|-------------|---------|-------------------|-----------|
| Mustermann  | Max     | max@drs.de        | 12345     |
| Beispiel    | Lisa    | lisa@drs.de       | 67890     |

## Feedbackpunkte
| Punkt        | Max |
|--------------|-----|
| Aufgabe 1    | 10  |
| Aufgabe 2    | 15  |

## Bewertungsstufen
*(Nur bei eingabemodus: stages — pro Feedbackpunkt eine Untertabelle)*

### Aufgabe 1
| Stufe          | Punkte |
|----------------|--------|
| voll erfüllt   | 10     |
| überwiegend    | 7.5    |
| teilweise      | 4      |
| nicht erfüllt  | 0      |

## Bewertungen
| Nachname   | Vorname | Aufgabe 1    | Aufgabe 2 | Kommentar |
|------------|---------|--------------|-----------|-----------|
| Mustermann | Max     | überwiegend  | 13        | gut       |
| Beispiel   | Lisa    | voll erfüllt | 14        |           |
```

---

## Regeln

### Pflichtfelder im Frontmatter

| Feld           | Beispiel        | Beschreibung |
|---|---|---|
| `title`        | "KA Hydraulik" | Anzeigename der Prüfung |
| `datum`        | `2026-06-15`   | ISO-Format YYYY-MM-DD |
| `klasse`       | `MTA22`        | Identisch zu Schüler-`klassen_key` |
| `notenskala`   | `mss_noten`    | aktuell: `mss_noten` oder `mss_punkte` |
| `eingabemodus` | `numeric`      | `numeric` oder `stages` |
| `schema_version` | `1`          | Aktuelles Schema |

Optional: `lernsituation` (slug), `lernfeld`, `lehrer`.

### Sektionen

- **`## Schüler`** — Pflicht. Spalten *Nachname* und *Vorname* werden
  erkannt; *Email* und *Moodle-ID* sind optional.
- **`## Feedbackpunkte`** — Pflicht. Spalten *Punkt* und *Max*.
- **`## Bewertungsstufen`** — nur bei `eingabemodus: stages`. Pro
  Feedbackpunkt eine `###`-Untertabelle mit dessen Stufen.
- **`## Bewertungen`** — optional. Spalten *Nachname*, *Vorname*, dann
  pro Feedbackpunkt eine Spalte (Header-Name muss zum Punkt-Namen passen)
  und am Ende *Kommentar*.

### Bewertungen — Zell-Werte

In der `## Bewertungen`-Tabelle sind **beide Notationen erlaubt**:

- **Numerisch**: `7.5`, `13`, `0` — direkt als Punktwert geschrieben.
- **Stufen-Label**: `voll erfüllt`, `überwiegend`, `nein` — Parser
  matched gegen das `label` der Stufen-Tabelle des Punktes und nimmt
  den passenden `points`-Wert.

Damit funktioniert dieselbe MD sowohl für Lehrer, die im Stufen-Modus
bewerten möchten, als auch für nachträgliche manuelle Korrekturen mit
Zahlen.

### Toleranzen beim Parser

- Zusätzliche Spalten werden ignoriert.
- Kommas statt Punkte in Zahlen werden akzeptiert (`7,5` → `7.5`).
- Reihenfolge der Sektionen ist beliebig.
- Fehlende Schüler in der DB werden beim Import **automatisch in der
  Klasse der Prüfung angelegt**.

---

## Workflow USB-Stick / Offline

1. Im DRS-System auf `/exams/{id}` → Export-Tab → **MD herunterladen**.
2. MD auf den USB-Stick mit der Offline-Feedback-App kopieren.
3. Im Klassenraum offline bewerten (Phase 12 in der App).
4. MD mit ergänzten Bewertungen wieder mitnehmen.
5. Im DRS-System auf `/exams/{id}` → Export-Tab →
   **MD hochladen + Bewertungen importieren**.

Bestehende Bewertungen werden überschrieben, neue Schüler aus der MD
werden in der Klasse angelegt.

---

## Workflow Obsidian

Du kannst die MD direkt in deinem Obsidian-Vault pflegen. Bei jedem
Re-Import wandern die Bewertungen ins DRS-System. Praktisch, wenn du
während der Korrektur Notizen oder weitere Felder ergänzen möchtest —
zusätzliche Felder werden vom Parser ignoriert.
