"""Admin-CLI: Bootstrap und Notfall-Operationen."""
import getpass
import sys

import typer

from app.crypto import hash_password
from app.db import SessionLocal
from app.models import User

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
def reset_password(username: str):
    """Setzt das Passwort eines Nutzers (CLI-Notfall)."""
    pw1 = getpass.getpass("Neues Passwort: ")
    pw2 = getpass.getpass("Wiederholen: ")
    if pw1 != pw2 or len(pw1) < 10:
        typer.echo("Eingaben ungültig.", err=True)
        sys.exit(1)
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username.lower()).first()
        if not u:
            typer.echo(f"Nutzer '{username}' nicht gefunden.", err=True)
            sys.exit(1)
        u.password_hash = hash_password(pw1)
        u.must_change_pw = True
        u.failed_attempts = 0
        u.locked_until = None
        db.commit()
        typer.echo(f"Passwort für '{u.username}' zurückgesetzt (must-change beim nächsten Login).")
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


if __name__ == "__main__":
    app()
