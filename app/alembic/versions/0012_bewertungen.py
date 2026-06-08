"""Bewertungs-Modul: students, exams, exam_feedback_points, exam_results

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("klassen_key", sa.String(255), nullable=False, server_default=""),
        sa.Column("nachname", sa.String(120), nullable=False),
        sa.Column("vorname", sa.String(120), nullable=False, server_default=""),
        sa.Column("email", sa.String(255), nullable=False, server_default=""),
        sa.Column("moodle_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_students_klassen", "students",
                    ["owner_user_id", "klassen_key"])

    op.create_table(
        "exams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=False, server_default="Neue Prüfung"),
        sa.Column("datum", sa.String(10), nullable=False, server_default=""),
        sa.Column("klassen_key", sa.String(255), nullable=False, server_default=""),
        sa.Column("learning_situation_id", sa.Integer(),
                  sa.ForeignKey("learning_situations.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("lesson_note_id", sa.Integer(),
                  sa.ForeignKey("lesson_notes.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("grading_scale_key", sa.String(32),
                  nullable=False, server_default="mss_noten"),
        sa.Column("input_mode", sa.String(16),
                  nullable=False, server_default="numeric"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_exams_klassen", "exams",
                    ["owner_user_id", "klassen_key", "datum"])

    op.create_table(
        "exam_feedback_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(),
                  sa.ForeignKey("exams.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("max_points", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stages_json", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "exam_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(),
                  sa.ForeignKey("exams.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("student_id", sa.Integer(),
                  sa.ForeignKey("students.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("erreicht_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_exam_results_unique", "exam_results",
                    ["exam_id", "student_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_exam_results_unique", "exam_results")
    op.drop_table("exam_results")
    op.drop_table("exam_feedback_points")
    op.drop_index("ix_exams_klassen", "exams")
    op.drop_table("exams")
    op.drop_index("ix_students_klassen", "students")
    op.drop_table("students")
