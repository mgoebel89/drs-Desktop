from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Boolean, ForeignKey, LargeBinary, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="teacher")  # "admin" | "teacher"
    full_name: Mapped[str] = mapped_column(String(120), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_pw: Mapped[bool] = mapped_column(Boolean, default=True)

    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Verschlüsselt (AES-GCM): nonce || ciphertext || tag
    anthropic_key_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    untis_creds_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # SMB-Anbindung an OMV-Share. JSON {host, share, username, password,
    # vault_subpath, material_subpath}, AES-GCM verschlüsselt.
    smb_creds_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # random token
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")

    user: Mapped[User] = relationship(back_populates="sessions")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)  # login_ok, login_fail, user_created, ...
    target: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


class Worksheet(Base):
    __tablename__ = "worksheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Neues Aufgabenblatt")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Optionale Verknüpfung zur Lernsituation
    learning_situation_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_situations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    revisions: Mapped[list["WorksheetRevision"]] = relationship(
        back_populates="worksheet", cascade="all, delete-orphan",
        order_by="WorksheetRevision.id.desc()",
    )


class WorksheetRevision(Base):
    __tablename__ = "worksheet_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    worksheet_id: Mapped[int] = mapped_column(ForeignKey("worksheets.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    comment: Mapped[str] = mapped_column(String(255), default="")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    aufgaben_json: Mapped[str] = mapped_column(Text, default="[]")
    # Wenn die Revision aus dem Wizard kommt: roher Markdown-Quelltext.
    markdown_source: Mapped[str] = mapped_column(Text, default="")

    worksheet: Mapped[Worksheet] = relationship(back_populates="revisions")


class LessonNote(Base):
    """Datumsspezifische Lehrer-Notizen zu einer Untis-Stunde.
    Key: user + Datum + Klassen-Kombi + Fach-Kombi.
    Mehrere Stunden mit identischer Klasse/Fach am selben Tag teilen sich eine Notiz."""
    __tablename__ = "lesson_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_date: Mapped[str] = mapped_column(String(10), index=True)   # 'YYYY-MM-DD'
    klassen_key: Mapped[str] = mapped_column(String(255), index=True)  # z.B. 'BSMT 23 a'
    subjects_key: Mapped[str] = mapped_column(String(255), index=True) # z.B. 'BBU_Mt2'
    block_start: Mapped[str] = mapped_column(String(5), default="", index=True)  # 'HH:MM'
    theme: Mapped[str] = mapped_column(String(500), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    material: Mapped[str] = mapped_column(Text, default="")
    remarks: Mapped[str] = mapped_column(Text, default="")
    # Sitzungs-spezifische Fach-Anzeige (überschreibt Untis-Kürzel und Reihen-Default)
    subject_override: Mapped[str] = mapped_column(String(200), default="")
    # Stunde als Prüfung markieren (roter Rahmen im Grid)
    is_exam: Mapped[bool] = mapped_column(Boolean, default=False)
    # Verknüpfung zur Lernsituation (optional)
    learning_situation_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_situations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LsAufgabe(Base):
    """Aufgabe innerhalb einer Lernsituation. Quelle bleibt die Inhalts-MD;
    diese Tabelle ist ein Index für Verknüpfungen + Anzeige."""
    __tablename__ = "ls_aufgaben"

    id: Mapped[int] = mapped_column(primary_key=True)
    learning_situation_id: Mapped[int] = mapped_column(
        ForeignKey("learning_situations.id", ondelete="CASCADE"), index=True
    )
    nummer: Mapped[int] = mapped_column(Integer)
    titel: Mapped[str] = mapped_column(String(500), default="")
    anchor: Mapped[str] = mapped_column(String(120), default="")
    phasen: Mapped[str] = mapped_column(String(255), default="")  # CSV
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LessonNoteAufgabe(Base):
    """M2M zwischen lesson_notes und ls_aufgaben."""
    __tablename__ = "lesson_note_aufgaben"

    lesson_note_id: Mapped[int] = mapped_column(
        ForeignKey("lesson_notes.id", ondelete="CASCADE"), primary_key=True
    )
    ls_aufgabe_id: Mapped[int] = mapped_column(
        ForeignKey("ls_aufgaben.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)


class LearningSituation(Base):
    """Didaktische Lernsituation. Spannt meist mehrere Blöcke über Wochen.
    Verknüpft mit lesson_notes und worksheets. Hat einen stabilen SMB-Ordner und
    eine Obsidian-Notiz im zentralen Vault."""
    __tablename__ = "learning_situations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(120), index=True)  # slugifiziert, immutable nach Anlegen
    display_name: Mapped[str] = mapped_column(String(200))  # frei umbenennbar
    klassen_key: Mapped[str] = mapped_column(String(255), default="", index=True)
    lernfeld: Mapped[str] = mapped_column(String(64), default="")
    # Stabiler Ordnername auf dem SMB-Share, Pattern "LS-{id:04d}_{slug}"
    smb_folder_name: Mapped[str] = mapped_column(String(200), default="")
    # Pfad zur Obsidian-Notiz, relativ zur Vault
    obsidian_note_path: Mapped[str] = mapped_column(String(255), default="")
    # Wizard-Persistenz (lernziele/vorwissen aus Wizard v1 — werden in v2
    # durch die Inhalts-MD ersetzt, bleiben aber für Bestandsdaten erhalten)
    lernziele: Mapped[str] = mapped_column(Text, default="")
    vorwissen: Mapped[str] = mapped_column(Text, default="")
    last_fobizz_prompt: Mapped[str] = mapped_column(Text, default="")
    last_fobizz_output: Mapped[str] = mapped_column(Text, default="")
    # Wizard v2
    last_material_type: Mapped[str] = mapped_column(String(32), default="")
    last_extras: Mapped[str] = mapped_column(Text, default="")
    content_md_present: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LessonSeriesOverride(Base):
    """Reihen-weite Fach-Bezeichnung pro (Klassen, Fach)-Kombi.
    Beispiel: 'BBU_Mt2' → 'Elektrotechnik LF3 Stromkreise analysieren'."""
    __tablename__ = "lesson_series_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    klassen_key: Mapped[str] = mapped_column(String(255), index=True)
    subjects_key: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class IcalCalendar(Base):
    """Pro Nutzer hinterlegte externe Kalender via iCal-URL."""
    __tablename__ = "ical_calendars"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(80), default="Kalender")
    color: Mapped[str] = mapped_column(String(16), default="#7B61FF")  # hex
    url_enc: Mapped[bytes] = mapped_column(LargeBinary)  # AES-GCM verschlüsselt
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    """Globale Schlüssel/Wert-Einstellungen (Branding etc.)."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    mime: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
