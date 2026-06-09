"""ls_aufgaben.text_md + loesungsskizze_md für Inline-Edit pro Aufgabe

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _existing_columns(insp, table: str) -> set[str]:
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = _existing_columns(insp, "ls_aufgaben")
    additions = []
    if "text_md" not in existing:
        additions.append(sa.Column("text_md", sa.Text(),
                                   nullable=False, server_default=""))
    if "loesungsskizze_md" not in existing:
        additions.append(sa.Column("loesungsskizze_md", sa.Text(),
                                   nullable=False, server_default=""))
    if not additions:
        return
    with op.batch_alter_table("ls_aufgaben") as batch:
        for col in additions:
            batch.add_column(col)


def downgrade() -> None:
    with op.batch_alter_table("ls_aufgaben") as batch:
        for col in ("text_md", "loesungsskizze_md"):
            try:
                batch.drop_column(col)
            except Exception:
                pass
