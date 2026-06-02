"""Admin-CLI: Bootstrap und Notfall-Operationen."""
import getpass
import json
import sys

import typer

from app.crypto import hash_password
from app.db import SessionLocal
from app.models import User, Worksheet, WorksheetRevision

app = typer.Typer(help="DRS Admin CLI")


@app.command("create-admin")
def create_admin(
    username: str = typer.Option(None, "--username", "-u", prompt="Admin-Benutzername"),
    full_name: str = typer.Option("", "--full-name", "-n", prompt="Vollständiger Name", show_default=False),
    password: str = typer.Option(None, "--password", "-p",
                                 help="Initial-PW (nicht-interaktiv). Wenn weg, wird interaktiv gefragt."),
):
    """Legt den initialen Admin-Account an (oder einen weiteren Admin)."""
    if password:
        pw1 = password
    else:
        pw1 = getpass.getpass("Initial-Passwort: ")
        pw2 = getpass.getpass("Wiederholen: ")
        if pw1 != pw2:
            typer.echo("Passwörter stimmen nicht überein.", err=True)
            sys.exit(1)
    if len(pw1) < 10:
        typer.echo("Passwort muss mindestens 10 Zeichen haben.", err=True)
        sys.exit(1)

    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first():
            typer.echo(f"Benutzer '{username}' existiert bereits.", err=True)
            sys.exit(1)
        u = User(username=username.lower(), full_name=full_name,
                 role="admin", password_hash=hash_password(pw1),
                 must_change_pw=False, active=True)
        db.add(u)
        db.commit()
        typer.echo(f"Admin '{u.username}' angelegt.")
    finally:
        db.close()


@app.command("reset-password")
def reset_password(
    username: str,
    password: str = typer.Option(None, "--password", "-p",
                                 help="Neues PW (nicht-interaktiv). Wenn leer, wird gefragt."),
    no_force_change: bool = typer.Option(False, "--no-force-change",
                                         help="must_change_pw nicht setzen (User behält das PW dauerhaft)."),
):
    """Setzt das Passwort eines Nutzers (CLI-Notfall)."""
    if password:
        pw1 = password
    else:
        pw1 = getpass.getpass("Neues Passwort: ")
        pw2 = getpass.getpass("Wiederholen: ")
        if pw1 != pw2:
            typer.echo("Passwörter stimmen nicht überein.", err=True)
            sys.exit(1)
    if len(pw1) < 10:
        typer.echo("Passwort muss mindestens 10 Zeichen haben.", err=True)
        sys.exit(1)
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username.lower()).first()
        if not u:
            typer.echo(f"Nutzer '{username}' nicht gefunden.", err=True)
            sys.exit(1)
        u.password_hash = hash_password(pw1)
        u.must_change_pw = not no_force_change
        u.failed_attempts = 0
        u.locked_until = None
        db.commit()
        flag = "" if no_force_change else " (must-change beim nächsten Login)"
        typer.echo(f"Passwort für '{u.username}' zurückgesetzt{flag}.")
    finally:
        db.close()


@app.command("list-users")
def list_users():
    db = SessionLocal()
    try:
        for u in db.query(User).order_by(User.username).all():
            typer.echo(f"{u.id:>3}  {u.username:<20} {u.role:<8} active={u.active} must_change_pw={u.must_change_pw}")
    finally:
        db.close()


_SAMPLE_META = {
    "headerLabel": "lernfeld",
    "headerValue": "Lernfeld 3 · Einheit 02 — Stromkreise analysieren",
    "lernsituationTitel": "Auftrag aus dem Betrieb",
    "lernsituationText": (
        "In deinem Ausbildungsbetrieb wird eine neue Maschinensteuerung installiert. "
        "Der Elektromeister bittet dich, die Stromkreise der Anlage zu überprüfen. "
        "Dazu musst du Reihen- und Parallelschaltungen sicher berechnen und dokumentieren können.\n\n"
        "Ein Kollege hat bereits erste Messungen durchgeführt, aber die Ergebnisse passen "
        "nicht zusammen. Deine Aufgabe ist es, die Fehler zu finden und die korrekten "
        "Werte zu ermitteln."
    ),
    "lernsituationBild": "",
}

_SAMPLE_AUFGABEN = [
    {
        "id": 1,
        "text": (
            "Erkläre in eigenen Worten den Unterschied zwischen einer Reihen- und einer "
            "Parallelschaltung. Nenne jeweils ein konkretes Beispiel aus deinem Berufsalltag "
            "(z. B. Kontrolllampen, Steuerstromkreis, Verbraucher in einer Anlage)."
        ),
        "kriterien": (
            "Korrekte Definition beider Schaltarten; je ein praxisnahes Beispiel; "
            "korrekte Verwendung der Fachbegriffe Strom, Spannung und Widerstand."
        ),
        "musterloesungText": (
            "Bei der Reihenschaltung fließt durch alle Bauteile derselbe Strom; die Spannungen "
            "addieren sich. Es gilt $$R\\ges = R_1 + R_2 + \\ldots$$ "
            "Bei der Parallelschaltung liegt an allen Bauteilen dieselbe Spannung an, die "
            "Teilströme addieren sich: $$\\frac{1}{R\\ges} = \\frac{1}{R_1} + \\frac{1}{R_2} + \\ldots$$"
        ),
        "musterloesungBild": "",
        "upload": True,
        "uploadPDF": False,
    },
    {
        "id": 2,
        "text": (
            "Berechne den Gesamtwiderstand der folgenden Reihenschaltung und gib das "
            "Ergebnis in der korrekten SI-Einheit an:\n\n"
            "$$R_1 = 47\\Ohm,\\quad R_2 = 100\\Ohm,\\quad R_3 = 33\\Ohm$$"
        ),
        "kriterien": (
            "Formel korrekt genannt; Rechenweg vollständig und nachvollziehbar; "
            "Ergebnis $R\\ges = 180\\Ohm$ mit Einheit."
        ),
        "musterloesungText": "$$R\\ges = R_1 + R_2 + R_3 = 47\\Ohm + 100\\Ohm + 33\\Ohm = 180\\Ohm$$",
        "musterloesungBild": "",
        "upload": True,
        "uploadPDF": False,
    },
    {
        "id": 3,
        "text": (
            "An einer Parallelschaltung liegt eine Spannung von $U = 12\\V$ an. "
            "Die Teilwiderstände betragen $R_1 = 60\\Ohm$ und $R_2 = 40\\Ohm$. "
            "Berechne den Gesamtstrom $I\\ges$."
        ),
        "kriterien": (
            "Berechnung der Teilströme $I_1$ und $I_2$; Gesamtstrom als Summe; "
            "alle Zwischenergebnisse mit SI-Einheiten; Ergebnis $I\\ges = 0{,}5\\A$."
        ),
        "musterloesungText": (
            "$$I_1 = \\frac{U}{R_1} = \\frac{12\\V}{60\\Ohm} = 0{,}2\\A \\qquad "
            "I_2 = \\frac{U}{R_2} = \\frac{12\\V}{40\\Ohm} = 0{,}3\\A$$ "
            "$$I\\ges = I_1 + I_2 = 0{,}5\\A$$"
        ),
        "musterloesungBild": "",
        "upload": True,
        "uploadPDF": False,
    },
    {
        "id": 4,
        "text": (
            "Skizziere den Schaltplan einer gemischten Schaltung: $R_1$ und $R_2$ in Reihe, "
            "dazu $R_3$ parallel zu $R_2$. Beschrifte alle Widerstände und Anschlusspunkte. "
            "Foto der Handskizze hochladen."
        ),
        "kriterien": (
            "Schaltplan vollständig und korrekt; alle Bauteile beschriftet; "
            "Anschlüsse eindeutig erkennbar; Foto scharf und leserlich."
        ),
        "musterloesungText": "",
        "musterloesungBild": "",
        "upload": True,
        "uploadPDF": True,
    },
    {
        "id": 5,
        "text": (
            "**Reflexion:** Was war heute neu für dich? An welcher Stelle warst du dir unsicher? "
            "Welche Inhalte möchtest du vor der nächsten Lernsituation noch vertiefen?"
        ),
        "kriterien": (
            "Persönlicher Bezug erkennbar; konkrete Nennung von Lerninhalten oder "
            "offenen Fragen; ehrliche Selbsteinschätzung."
        ),
        "musterloesungText": "",
        "musterloesungBild": "",
        "upload": False,
        "uploadPDF": False,
    },
]


@app.command("seed-sample")
def seed_sample(
    username: str = typer.Option(..., "--user", "-u", help="Benutzername (Owner des Beispielblatts)"),
):
    """Legt ein Beispiel-Aufgabenblatt zu Reihen-/Parallelschaltung für den angegebenen Nutzer an."""
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username.lower()).first()
        if not u:
            typer.echo(f"Nutzer '{username}' nicht gefunden.", err=True)
            sys.exit(1)
        ws = Worksheet(owner_user_id=u.id, title="LF3 · Reihen- und Parallelschaltung (Beispiel)")
        db.add(ws); db.flush()
        rev = WorksheetRevision(
            worksheet_id=ws.id,
            created_by_user_id=u.id,
            comment="Per drs-admin seed-sample erzeugt",
            meta_json=json.dumps(_SAMPLE_META, ensure_ascii=False),
            aufgaben_json=json.dumps(_SAMPLE_AUFGABEN, ensure_ascii=False),
        )
        db.add(rev)
        db.commit()
        typer.echo(f"Beispiel-Aufgabenblatt '{ws.title}' (id={ws.id}) für '{u.username}' angelegt.")
    finally:
        db.close()


if __name__ == "__main__":
    app()
