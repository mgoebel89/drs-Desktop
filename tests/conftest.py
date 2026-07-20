"""Test-Fixtures: eine frische In-Memory-DB pro Test, plus ein minimaler
manueller Stundenplan (eine Reihe Klasse+Fach, Mo–Fr je ein Block)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models as m


@pytest.fixture()
def db():
    # StaticPool + check_same_thread=False: eine geteilte In-Memory-Verbindung,
    # damit auch der TestClient-Requestthread dieselbe DB sieht.
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def plan(db):
    """Baut einen minimalen Plan und gibt Kontext zurück.

    Reihe: Klasse 'MT' / Fach 'BBU', jeden Wochentag ein Block um 08:00.
    Woche liegt im August 2026 (keine RLP-Feiertage)."""
    user = m.User(username="t", password_hash="x")
    db.add(user)
    db.flush()

    db.add(m.TtSlot(user_id=user.id, position=0, name="1./2.",
                    start_time="08:00", end_time="09:30"))
    kl = m.TtKlasse(user_id=user.id, klassen_key="MT", display_name="MT",
                    art="klasse")
    fa = m.TtFach(user_id=user.id, subjects_key="BBU", display_name="BBU")
    db.add_all([kl, fa])
    db.flush()

    ver = m.TtVersion(user_id=user.id, name="v1", valid_from="2026-01-01")
    db.add(ver)
    db.flush()
    for wd in range(5):  # Mo..Fr
        db.add(m.TtRow(version_id=ver.id, weekday=wd, block_start="08:00",
                       klasse_id=kl.id, fach_id=fa.id, rhythm="all"))
    db.add(m.TtSchoolyear(user_id=user.id, name="2026/27",
                          first_day="2026-08-01", last_day="2027-07-31"))
    db.flush()

    # Mo–Fr der Woche 2026-08-03
    days = {f"B{i+1}": (date(2026, 8, 3) + timedelta(days=i)).isoformat()
            for i in range(5)}
    return {"user": user, "kk": "MT", "sk": "BBU", "bs": "08:00", "days": days}


@pytest.fixture()
def stamm(db):
    """Vollständige Stammdaten: Jahrgang → Klasse → 3 Schüler, dazu die
    1:1-Lerngruppe der Klasse (art='klasse') plus eine zweite Klasse."""
    user = m.User(username="s", password_hash="x")
    db.add(user)
    db.flush()

    jg = m.TtJahrgang(user_id=user.id, name="BSMT 26")
    db.add(jg)
    db.flush()

    kl_a = m.TtSchulklasse(user_id=user.id, jahrgang_id=jg.id, name="BSMT 26 a")
    kl_b = m.TtSchulklasse(user_id=user.id, jahrgang_id=jg.id, name="BSMT 26 b")
    db.add_all([kl_a, kl_b])
    db.flush()

    # 1:1-Lerngruppen, wie die Stammdaten sie automatisch anlegen
    lg_a = m.TtKlasse(user_id=user.id, klassen_key="BSMT26a",
                      display_name="BSMT 26 a", art="klasse", jahrgang_id=jg.id)
    lg_b = m.TtKlasse(user_id=user.id, klassen_key="BSMT26b",
                      display_name="BSMT 26 b", art="klasse", jahrgang_id=jg.id)
    db.add_all([lg_a, lg_b])
    db.flush()
    db.add(m.TtLerngruppeKlasse(lerngruppe_id=lg_a.id, schulklasse_id=kl_a.id))
    db.add(m.TtLerngruppeKlasse(lerngruppe_id=lg_b.id, schulklasse_id=kl_b.id))

    schueler = []
    for nn, vn in [("Ahrens", "Ada"), ("Bloch", "Ben"), ("Curt", "Cem")]:
        s = m.Student(owner_user_id=user.id, klassen_key="BSMT26a",
                      schulklasse_id=kl_a.id, jahrgang_id=jg.id,
                      nachname=nn, vorname=vn, active=True)
        db.add(s)
        schueler.append(s)
    db.flush()
    db.commit()
    return {"user": user, "jahrgang": jg, "klasse_a": kl_a, "klasse_b": kl_b,
            "lg_a": lg_a, "lg_b": lg_b, "schueler": schueler}
