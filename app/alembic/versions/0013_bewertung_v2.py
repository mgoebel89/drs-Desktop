"""Bewertung v2: grading_scales, exam_students, exam_group_results,
feedback_templates + exam_feedback_points.scope

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # scope auf Feedbackpunkte
    with op.batch_alter_table("exam_feedback_points") as batch:
        batch.add_column(sa.Column("scope", sa.String(16),
                                   nullable=False, server_default="individual"))

    op.create_table(
        "exam_students",
        sa.Column("exam_id", sa.Integer(),
                  sa.ForeignKey("exams.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("student_id", sa.Integer(),
                  sa.ForeignKey("students.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("group_label", sa.String(40), nullable=False, server_default=""),
    )

    op.create_table(
        "exam_group_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(),
                  sa.ForeignKey("exams.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("group_label", sa.String(40), nullable=False, server_default=""),
        sa.Column("erreicht_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_exam_group_results_unique", "exam_group_results",
                    ["exam_id", "group_label"], unique=True)

    op.create_table(
        "grading_scales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("scale_type", sa.String(32), nullable=False, server_default="mss_noten"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "feedback_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Migriere bestehende exams: alle aktiven Schüler der Klasse als Teilnehmer
    # übernehmen (damit Bestandsprüfungen weiter alle Schüler zeigen).
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO exam_students (exam_id, student_id, group_label)
        SELECT e.id, s.id, ''
        FROM exams e
        JOIN students s
          ON s.owner_user_id = e.owner_user_id
         AND s.klassen_key = e.klassen_key
         AND s.active = 1
    """))

    # grading_scale_key auf builtin-Präfix normalisieren
    conn.execute(sa.text("""
        UPDATE exams SET grading_scale_key = 'builtin:' || grading_scale_key
        WHERE grading_scale_key IN ('mss_noten', 'mss_punkte')
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE exams SET grading_scale_key = replace(grading_scale_key, 'builtin:', '')
        WHERE grading_scale_key LIKE 'builtin:%'
    """))
    op.drop_table("feedback_templates")
    op.drop_table("grading_scales")
    op.drop_index("ix_exam_group_results_unique", "exam_group_results")
    op.drop_table("exam_group_results")
    op.drop_table("exam_students")
    with op.batch_alter_table("exam_feedback_points") as batch:
        batch.drop_column("scope")
