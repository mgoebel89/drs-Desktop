"""Bewertung v3: eval_type + weight_pct auf exam_feedback_points

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("exam_feedback_points") as batch:
        batch.add_column(sa.Column("eval_type", sa.String(16),
                                   nullable=False, server_default="punkte"))
        batch.add_column(sa.Column("weight_pct", sa.Float(),
                                   nullable=False, server_default="0"))

    # Datenmigration: eval_type aus altem exam.input_mode ableiten.
    # Punkte, die zu einem exam mit input_mode='stages' gehören → 'stufen'.
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE exam_feedback_points
        SET eval_type = 'stufen'
        WHERE exam_id IN (SELECT id FROM exams WHERE input_mode = 'stages')
    """))


def downgrade() -> None:
    with op.batch_alter_table("exam_feedback_points") as batch:
        batch.drop_column("weight_pct")
        batch.drop_column("eval_type")
