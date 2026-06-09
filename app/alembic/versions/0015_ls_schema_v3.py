"""LS-Schema v3: ls_arbeitsblaetter + erweiterte learning_situations-Felder

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-09

Erweitert learning_situations um die strukturierten v3-Felder
(Lehrerinformationen, Lernsituationsbeschreibung, Leistungsfeststellung,
Hash-/Mtime-Tracking für Zwei-Wege-Sync) und legt die neue Tabelle
ls_arbeitsblaetter an (LS → Arbeitsblatt → Aufgabe). Bestehende Aufgaben
hängen weiter direkt an der LS (arbeitsblatt_id = NULL).
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


_LS_COLUMNS = [
    ("schema_version", lambda: sa.Column("schema_version", sa.Integer(),
                                          nullable=False, server_default="2")),
    ("dauer_stunden", lambda: sa.Column("dauer_stunden", sa.Integer(),
                                         nullable=False, server_default="0")),
    ("version_no", lambda: sa.Column("version_no", sa.Integer(),
                                      nullable=False, server_default="1")),
    ("lernsituation_md", lambda: sa.Column("lernsituation_md", sa.Text(),
                                            nullable=False, server_default="")),
    ("lernsituation_bild_path", lambda: sa.Column("lernsituation_bild_path",
                                                   sa.String(500),
                                                   nullable=False,
                                                   server_default="")),
    ("kompetenzen_md", lambda: sa.Column("kompetenzen_md", sa.Text(),
                                          nullable=False, server_default="")),
    ("uebergreifende_aspekte_md", lambda: sa.Column("uebergreifende_aspekte_md",
                                                     sa.Text(),
                                                     nullable=False,
                                                     server_default="")),
    ("lehrer_vorwissen_md", lambda: sa.Column("lehrer_vorwissen_md", sa.Text(),
                                               nullable=False,
                                               server_default="")),
    ("leistungsfeststellung_md", lambda: sa.Column("leistungsfeststellung_md",
                                                    sa.Text(),
                                                    nullable=False,
                                                    server_default="")),
    ("content_hash", lambda: sa.Column("content_hash", sa.String(64),
                                        nullable=False, server_default="")),
    ("content_mtime", lambda: sa.Column("content_mtime", sa.DateTime(),
                                         nullable=True)),
]


def _existing_columns(insp, table: str) -> set[str]:
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    ls_existing = _existing_columns(insp, "learning_situations")
    missing = [(name, factory) for name, factory in _LS_COLUMNS
               if name not in ls_existing]
    if missing:
        with op.batch_alter_table("learning_situations") as batch:
            for _, factory in missing:
                batch.add_column(factory())

    if "ls_arbeitsblaetter" not in set(insp.get_table_names()):
        op.create_table(
            "ls_arbeitsblaetter",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("learning_situation_id", sa.Integer(),
                      sa.ForeignKey("learning_situations.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("title", sa.String(255), nullable=False, server_default=""),
            sa.Column("phase", sa.String(255), nullable=False, server_default=""),
            sa.Column("bearbeitungshinweis_md", sa.Text(),
                      nullable=False, server_default=""),
            sa.Column("content_md", sa.Text(), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(), nullable=False,
                      server_default=sa.func.now()),
        )
        op.create_index("ix_ls_arbeitsblaetter_ls_pos", "ls_arbeitsblaetter",
                        ["learning_situation_id", "position"])

    aufg_existing = _existing_columns(insp, "ls_aufgaben")
    if "arbeitsblatt_id" not in aufg_existing:
        # In SQLite-batch-Mode muss jeder FK-Constraint einen Namen haben,
        # damit alembic die Tabelle korrekt neu aufbauen kann.
        with op.batch_alter_table("ls_aufgaben") as batch:
            batch.add_column(sa.Column(
                "arbeitsblatt_id", sa.Integer(),
                sa.ForeignKey(
                    "ls_arbeitsblaetter.id",
                    name="fk_ls_aufgaben_arbeitsblatt_id",
                    ondelete="CASCADE",
                ),
                nullable=True, index=True,
            ))


def downgrade() -> None:
    with op.batch_alter_table("ls_aufgaben") as batch:
        batch.drop_column("arbeitsblatt_id")
    op.drop_index("ix_ls_arbeitsblaetter_ls_pos", "ls_arbeitsblaetter")
    op.drop_table("ls_arbeitsblaetter")
    with op.batch_alter_table("learning_situations") as batch:
        for col in (
            "schema_version", "dauer_stunden", "version_no", "lernsituation_md",
            "lernsituation_bild_path", "kompetenzen_md",
            "uebergreifende_aspekte_md", "lehrer_vorwissen_md",
            "leistungsfeststellung_md", "content_hash", "content_mtime",
        ):
            batch.drop_column(col)
