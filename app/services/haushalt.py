"""Haushalt: Posten, Verbrauch und Restmittel.

Die Schulmittel verteilen sich auf zwei Töpfe:

* **Verwaltungshaushalt** — Anschaffungen bis 999 €, ohne Angebot beschaffbar.
* **Vermögenshaushalt** — ab 1000 €, in der Regel sind Angebote einzuholen.

Beides sind hier `HhPosten` mit unterschiedlicher `art`. Die 1000-€-Grenze
**warnt nur** (sie schlägt den Topf vor und erinnert an Angebote); sie
blockiert nichts, weil Sammelbestellungen und Preisänderungen sonst gegen die
Software arbeiten würden.

**Mittel verfallen zum Jahresende.** Deshalb rechnet hier alles strikt
innerhalb eines Haushaltsjahres: Der Verbrauch eines Postens ist die Summe der
Kosten-Einträge, die auf genau diesen Posten gebucht sind — und ein Posten
gehört zu genau einem Jahr. Einen Übertrag gibt es nicht und darf es nicht
geben, sonst zeigte die Restmittel-Anzeige Geld an, das es nicht mehr gibt.

Beträge liegen in der DB als **Cent (Integer)**; nach außen (JSON, Anzeige)
gehen sie als Euro-Fließkommazahl. Die Umrechnung passiert nur hier.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HhIdee, HhPosten, User, Vorgang, VorgangEintrag

# Ab diesem Betrag gehört eine Anschaffung in den Vermögenshaushalt.
SCHWELLE_CENT = 100_000

ARTEN = ("verwaltung", "vermoegen")
ART_LABEL = {
    "verwaltung": "Verwaltungshaushalt",
    "vermoegen": "Vermögenshaushalt",
}
ART_KURZ = {"verwaltung": "Verwaltung", "vermoegen": "Vermögen"}
ART_HINWEIS = {
    "verwaltung": "Anschaffungen bis 999 € — ohne Angebot beschaffbar.",
    "vermoegen": "Anschaffungen ab 1000 € — in der Regel Angebote einholen.",
}

IDEE_STATUS = ("offen", "beantragt", "bewilligt", "abgelehnt", "verworfen")
PRIO_LABEL = {1: "hoch", 2: "mittel", 3: "niedrig"}


# ── Geld ─────────────────────────────────────────────────────────────────

def to_cent(euro) -> int:
    """Euro (Zahl oder String mit Komma) → Cent. Unlesbares wird zu 0."""
    if euro is None or euro == "":
        return 0
    if isinstance(euro, str):
        euro = euro.strip()
        # Deutsche Schreibweise „1.234,56": Punkt ist Tausendertrenner.
        if "," in euro:
            euro = euro.replace(".", "").replace(",", ".")
    try:
        return int(round(float(euro) * 100))
    except (TypeError, ValueError):
        return 0


def to_euro(cent: int | None) -> float:
    return round((cent or 0) / 100, 2)


def art_fuer(cent: int) -> str:
    """Welcher Topf zu einem Betrag passt — als Vorschlag, nicht als Zwang."""
    return "vermoegen" if (cent or 0) >= SCHWELLE_CENT else "verwaltung"


# ── Posten ───────────────────────────────────────────────────────────────

def posten_des_jahres(db: Session, user: User, jahr: int) -> list[HhPosten]:
    return list(db.scalars(
        select(HhPosten)
        .where(HhPosten.user_id == user.id, HhPosten.jahr == jahr)
        .order_by(HhPosten.art, HhPosten.position, HhPosten.id)
    ).all())


def verbrauch_je_posten(db: Session, user: User,
                        posten_ids: list[int]) -> dict[int, int]:
    """Ist-Verbrauch (Cent) je Posten über alle Vorgänge dieses Nutzers.

    Gezählt werden ausschließlich Kosten-Einträge. Angebote tragen zwar auch
    einen Preis, sind aber noch kein ausgegebenes Geld — sie dürfen die
    Restmittel nicht mindern.
    """
    if not posten_ids:
        return {}
    rows = db.execute(
        select(VorgangEintrag.hh_posten_id, VorgangEintrag.betrag_cent)
        .join(Vorgang, Vorgang.id == VorgangEintrag.vorgang_id)
        .where(Vorgang.user_id == user.id,
               VorgangEintrag.typ == "kosten",
               VorgangEintrag.hh_posten_id.in_(posten_ids))
    ).all()
    out: dict[int, int] = {pid: 0 for pid in posten_ids}
    for pid, cent in rows:
        out[pid] = out.get(pid, 0) + (cent or 0)
    return out


def posten_view(db: Session, user: User, jahr: int) -> dict:
    """Die Jahresansicht: beide Töpfe mit Budget, Verbrauch und Restmitteln."""
    posten = posten_des_jahres(db, user, jahr)
    verbrauch = verbrauch_je_posten(db, user, [p.id for p in posten])

    toepfe: dict[str, dict] = {}
    for art in ARTEN:
        eigene = [p for p in posten if p.art == art]
        zeilen = []
        for p in eigene:
            v = verbrauch.get(p.id, 0)
            zeilen.append({
                "id": p.id,
                "bezeichnung": p.bezeichnung,
                "notiz": p.notiz,
                "budget": to_euro(p.betrag_cent),
                "verbrauch": to_euro(v),
                "rest": to_euro(p.betrag_cent - v),
                "ueberzogen": v > p.betrag_cent,
            })
        summe_b = sum(p.betrag_cent for p in eigene)
        summe_v = sum(verbrauch.get(p.id, 0) for p in eigene)
        toepfe[art] = {
            "label": ART_LABEL[art],
            "hinweis": ART_HINWEIS[art],
            "posten": zeilen,
            "summe_budget": to_euro(summe_b),
            "summe_verbrauch": to_euro(summe_v),
            "summe_rest": to_euro(summe_b - summe_v),
        }
    return {"jahr": jahr, "toepfe": toepfe}


def posten_auswahl(db: Session, user: User, jahr: int) -> list[dict]:
    """Flache Liste für die Posten-Dropdowns an den Kosten-Einträgen."""
    return [{
        "id": p.id,
        "art": p.art,
        "label": f"{ART_KURZ.get(p.art, p.art)} · {p.bezeichnung or '(ohne Namen)'}",
        "bezeichnung": p.bezeichnung,
    } for p in posten_des_jahres(db, user, jahr)]


# ── Jahre ────────────────────────────────────────────────────────────────

def bekannte_jahre(db: Session, user: User) -> list[int]:
    """Alle Jahre, in denen etwas liegt — plus das laufende und das nächste.

    Das nächste Jahr ist immer dabei, weil die Ideenliste genau dorthin
    sammelt.
    """
    jetzt = date.today().year
    jahre = {jetzt, jetzt + 1}
    for j in db.scalars(select(HhPosten.jahr)
                        .where(HhPosten.user_id == user.id)).all():
        if j:
            jahre.add(int(j))
    for j in db.scalars(select(HhIdee.zieljahr)
                        .where(HhIdee.user_id == user.id)).all():
        if j:
            jahre.add(int(j))
    for j in db.scalars(select(Vorgang.haushaltsjahr)
                        .where(Vorgang.user_id == user.id)).all():
        if j:
            jahre.add(int(j))
    return sorted(jahre, reverse=True)


# ── Ideen ────────────────────────────────────────────────────────────────

def ideen_view(db: Session, user: User, zieljahr: int) -> dict:
    ideen = list(db.scalars(
        select(HhIdee)
        .where(HhIdee.user_id == user.id, HhIdee.zieljahr == zieljahr)
        .order_by(HhIdee.prioritaet, HhIdee.id)
    ).all())
    out = []
    summen = {"verwaltung": 0, "vermoegen": 0}
    for i in ideen:
        if i.status not in ("abgelehnt", "verworfen"):
            summen[i.art] = summen.get(i.art, 0) + i.betrag_cent
        out.append({
            "id": i.id,
            "art": i.art,
            "titel": i.titel,
            "betrag": to_euro(i.betrag_cent),
            "begruendung": i.begruendung,
            "prioritaet": i.prioritaet,
            "prio_label": PRIO_LABEL.get(i.prioritaet, "mittel"),
            "status": i.status,
            "vorgang_id": i.vorgang_id,
        })
    return {
        "zieljahr": zieljahr,
        "ideen": out,
        "summe_verwaltung": to_euro(summen.get("verwaltung", 0)),
        "summe_vermoegen": to_euro(summen.get("vermoegen", 0)),
    }
