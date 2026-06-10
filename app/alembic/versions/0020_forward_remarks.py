"""LessonNote: forward_remarks + forward_remarks_done_at

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-09

Bemerkungen für die NÄCHSTE Stunde derselben Klasse+Fach plus ein
'erledigt'-Zeitstempel — wird in der Folgestunde als oranger Banner
angezeigt und durch Klick auf 'Erledigt' geschlossen.
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
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
    cols = _existing_columns(insp, "lesson_notes")
    additions = []
    if "forward_remarks" not in cols:
        additions.append(sa.Column(
            "forward_remarks", sa.Text(), nullable=False, server_default=""))
    if "forward_remarks_done_at" not in cols:
        additions.append(sa.Column(
            "forward_remarks_done_at", sa.DateTime(), nullable=True))
    if not additions:
        return
    with op.batch_alter_table("lesson_notes") as batch:
        for col in additions:
            batch.add_column(col)


def downgrade() -> None:
    with op.batch_alter_table("lesson_notes") as batch:
        for c in ("forward_remarks_done_at", "forward_remarks"):
            try:
                batch.drop_column(c)
            except Exception:
                pass
