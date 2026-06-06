"""Material-Typ-Katalog + Prompt-Builder für den Wizard.

Jeder Material-Typ hat zwei Prompt-Templates:
- `fobizz_template`: kurz, weil der Fobizz-Agent den DRS-Systemprompt
  bereits aus `docs/fobizz-agent-systemprompt.md` kennt.
- `claude_template`: self-contained für Claude.ai (Pro-Abo), enthält die
  didaktische Rolle und Format-Vorgaben im Prompt selbst.

Beide Templates erwarten die Platzhalter:
- {ls_display_name}
- {ls_klasse}
- {ls_lernfeld}
- {content_md}        — Inhalts-MD-Body ohne Frontmatter und ohne Output-Sektion
- {extras}            — freitext vom Lehrer („Niveau HBFS, ohne Differenzierung")

Der Lehrer-Wizard ruft `build_prompts(...)` auf, bekommt beide fertigen
Prompts zurück und zeigt sie in Tabs an.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MaterialType:
    key: str
    label: str
    icon: str
    description: str
    fobizz_template: str
    claude_template: str


# ── gemeinsame Bausteine ──────────────────────────────────────────────────

_CLAUDE_ROLLE = """Du bist didaktischer Planungsassistent für einen Lehrer an
der David-Roentgen-Schule Neuwied (BBS Gewerbe + Technik), Fachrichtung
Mechatronik. Du planst lernfeldorientiert für SuS im dualen System,
Berufsfachschule, Höhere Berufsfachschule und Fachoberschule. Schreibst
in deutschem Markdown. Aufgaben im Imperativ, Lernziele operationalisiert,
keine Floskeln, lieber konkret als vollständig. Verwende „SuS" für
Schülerinnen und Schüler. Formeln in LaTeX, SI-Einheiten korrekt, Quellen
nennen wenn bekannt. Wenn dir Fakten fehlen, kennzeichne die Lücke statt
zu halluzinieren."""

_KONTEXT_BLOCK = """**Klasse:** {ls_klasse}
**Lernfeld:** {ls_lernfeld}
**Lernsituation:** {ls_display_name}

**Inhalts-Markdown (vom Lehrer in Obsidian gepflegt):**

```markdown
{content_md}
```

**Zusätzliche Hinweise vom Lehrer:** {extras}"""


def _make(key: str, label: str, icon: str, description: str,
          fobizz_auftrag: str, claude_auftrag: str) -> MaterialType:
    fobizz_template = (
        f"Bitte erzeuge zur folgenden Lernsituation: **{label}**.\n\n"
        + _KONTEXT_BLOCK + "\n\n"
        + fobizz_auftrag
    )
    claude_template = (
        _CLAUDE_ROLLE + "\n\n"
        + f"**Aufgabe:** Erzeuge **{label}** zur unten beschriebenen Lernsituation.\n\n"
        + _KONTEXT_BLOCK + "\n\n"
        + claude_auftrag
    )
    return MaterialType(key, label, icon, description, fobizz_template, claude_template)


# ── Katalog ──────────────────────────────────────────────────────────────

_FORMAT_ARBEITSBLATT = """Antworte als Markdown-Arbeitsblatt mit:

1. **Kopf**: Titel, Klasse, Lernfeld, geschätzte Bearbeitungszeit.
2. **Lernziel-Hinweis** in 1 Satz für die SuS.
3. **Aufgaben** durchnummeriert, jede mit:
   - klarer Auftragsformulierung im Imperativ
   - Sozialform (Einzel/Partner/Gruppe)
   - benötigtes Material
   - Erwartungshorizont (für den Lehrer, klar abgetrennt)
   - Differenzierung: 1 Hilfestellung + 1 Zusatzaufgabe
4. Mindestens 3 Aufgaben, max. 6. Realistisch für eine Doppelstunde."""

_FORMAT_LOESUNG = """Antworte als Markdown-Lösungsblatt:

1. **Hinweis**: bezieht sich auf das zuletzt erzeugte Arbeitsblatt (siehe
   Output-Sektion der Inhalts-MD, falls vorhanden — sonst bittest du um
   nachträgliches Anhängen des Arbeitsblatts).
2. Pro Aufgabe: Musterlösung mit kurzer Erläuterung des Lösungswegs.
3. Bewertungshinweise: typische Fehler, Punkte-Verteilung.
4. Differenzierungslösungen separat ausweisen."""

_FORMAT_TAFELBILD = """Antworte als Markdown mit:

1. **Tafelbild-Skizze** als Mermaid-Diagramm (`graph` oder `flowchart`)
   ODER als ASCII-Zeichnung, wenn ein Schaltplan/Schnitt erforderlich ist.
2. **Hefteintrag** als zusammenhängender Text, den die SuS abschreiben
   können — kurz, prüfungsrelevant, mit Kernformeln.
3. **Lehrerhinweise** (Was schreibt der Lehrer wann an die Tafel?)."""

_FORMAT_QUIZ = """Antworte als Markdown-Quiz:

1. **Multiple-Choice-Fragen** (5–8 Stück) mit je 4 Antwortoptionen,
   richtige Antwort markiert mit ✓.
2. **Kurzantwort-Fragen** (2–4 Stück) mit Erwartungshorizont.
3. **Auswertungs-Schlüssel** am Ende: Punkte pro Frage, Notenvorschlag.
4. Schwierigkeitsstufen kennzeichnen: 🟢 leicht / 🟡 mittel / 🔴 schwer."""

_FORMAT_HAUSAUFGABE = """Antworte als Markdown mit 1–3 Hausaufgaben:

1. Jede Aufgabe als zusammenhängender Auftrag (kein Aufgabenkatalog).
2. **Bezug zur nächsten Stunde** klar benennen — was bringt die HA in den
   Folgeunterricht ein?
3. Bearbeitungszeit pro Aufgabe angeben.
4. Erwartungshorizont kompakt als Stichpunkte."""

_FORMAT_STATIONEN = """Antworte als Markdown mit 4–6 Lernstationen:

Pro Station:
- **Stations-Nr.** + Titel
- **Auftrag** für die SuS (Imperativ, eindeutig)
- **Material** (was liegt an der Station bereit?)
- **Bearbeitungszeit** (Richtwert in Minuten)
- **Sozialform**
- **Erwartungshorizont** (für den Lehrer)

Am Anfang: **Laufzettel-Vorlage** als Markdown-Tabelle."""

_FORMAT_PROJEKT = """Antworte als Markdown-Projektauftrag:

1. **Auftrag** im Kundensprech (z. B. „Ein Unternehmen plant …").
2. **Rahmenbedingungen**: Zeit, Material, Sozialform, Bewertung.
3. **Meilensteine** mit Datumsplatzhalter.
4. **Bewertungskriterien** als Raster mit Punkten.
5. **Präsentationsform** definieren."""

_FORMAT_LERNLANDKARTE = """Antworte als Markdown mit einer **Lernlandkarte
als Mermaid-Diagramm** (`graph LR` oder `mindmap`), die alle Themen der
Lernsituation abbildet. Knoten sind Themen, Kanten sind Lernpfade.

Danach: **Lernpfad-Vorschläge** als nummerierte Liste (z. B.
„Pfad A: Grundlagen → Anwendung → Vertiefung")."""

_FORMAT_CONCEPTMAP = """Antworte als Markdown mit einer **Concept Map als
Mermaid-Diagramm** (`graph` oder `flowchart`). Knoten sind Begriffe,
Kanten tragen **Relations-Labels** (z. B. „besteht aus", „bewirkt",
„hängt ab von"). Mindestens 10 Knoten, sinnvoll geclustert."""


CATALOG: list[MaterialType] = [
    _make("arbeitsblatt", "Arbeitsblatt", "📝",
          "Aufgaben mit Erwartungshorizont und Differenzierung.",
          _FORMAT_ARBEITSBLATT, _FORMAT_ARBEITSBLATT),
    _make("loesungsblatt", "Lösungsblatt", "✅",
          "Musterlösungen + Bewertungshinweise zum Arbeitsblatt.",
          _FORMAT_LOESUNG, _FORMAT_LOESUNG),
    _make("tafelbild", "Tafelbild", "🪧",
          "Strukturskizze + Hefteintrag für die Sicherung.",
          _FORMAT_TAFELBILD, _FORMAT_TAFELBILD),
    _make("quiz", "Quiz", "❓",
          "MC + Kurzantwort + Schlüssel, mit Schwierigkeitsstufen.",
          _FORMAT_QUIZ, _FORMAT_QUIZ),
    _make("hausaufgabe", "Hausaufgabe", "🏠",
          "1–3 Transferaufgaben mit Anschluss an die Folgestunde.",
          _FORMAT_HAUSAUFGABE, _FORMAT_HAUSAUFGABE),
    _make("stationenlernen", "Stationenlernen", "🧭",
          "4–6 Stationen + Laufzettel + Erwartungshorizont.",
          _FORMAT_STATIONEN, _FORMAT_STATIONEN),
    _make("projektauftrag", "Projektauftrag", "🛠",
          "Auftrag, Meilensteine, Bewertungsraster.",
          _FORMAT_PROJEKT, _FORMAT_PROJEKT),
    _make("lernlandkarte", "Lernlandkarte", "🗺",
          "Themen + Lernpfade als Mermaid-Mindmap.",
          _FORMAT_LERNLANDKARTE, _FORMAT_LERNLANDKARTE),
    _make("conceptmap", "Concept Map", "🕸",
          "Begriffsnetz mit Relations-Labels als Mermaid.",
          _FORMAT_CONCEPTMAP, _FORMAT_CONCEPTMAP),
]

BY_KEY: dict[str, MaterialType] = {m.key: m for m in CATALOG}


def get(key: str) -> MaterialType | None:
    return BY_KEY.get(key)


def build_prompts(
    *,
    ls,                       # LearningSituation
    content_md_body: str,
    material_type_key: str,
    extras: str = "",
) -> dict:
    """Liefert {'fobizz': str, 'claude': str, 'material_type': MaterialType}."""
    mt = BY_KEY.get(material_type_key)
    if not mt:
        raise ValueError(f"Unbekannter Material-Typ: {material_type_key}")
    fmt = {
        "ls_display_name": ls.display_name or "(unbenannt)",
        "ls_klasse": ls.klassen_key or "(nicht gesetzt)",
        "ls_lernfeld": ls.lernfeld or "(nicht gesetzt)",
        "content_md": content_md_body.strip() or "(noch keine Inhalts-MD befüllt)",
        "extras": extras.strip() or "(keine)",
    }
    return {
        "fobizz": mt.fobizz_template.format(**fmt),
        "claude": mt.claude_template.format(**fmt),
        "material_type": mt,
    }
