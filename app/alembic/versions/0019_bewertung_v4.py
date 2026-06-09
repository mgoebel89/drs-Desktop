"""Bewertung v4: Modus, mündliche Bemerkungen, Notennamen, Unterschrift/Paraphe

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-09

- exams.bewertung_mode  ('note' | 'punkte' | 'mixed'; bestehende → 'mixed')
- exam_results.feedback_remarks_json (Map fp_id → mündliche Bemerkung)
- exam_group_results.feedback_remarks_json (analog für Gruppen-FPs)
- grading_scales.grade_names_json (Map label → schriftliche Bezeichnung)
- users.signature_data/_mime und .paraphe_data/_mime (BLOB, max ~500 KB)
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
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

    # exams.bewertung_mode (Default 'mixed' → Altdaten verhalten sich wie heute)
    if "bewertung_mode" not in _existing_columns(insp, "exams"):
        with op.batch_alter_table("exams") as batch:
            batch.add_column(sa.Column(
                "bewertung_mode", sa.String(16),
                nullable=False, server_default="mixed",
            ))

    # Bemerkungen pro (Schüler, FP) bzw. (Gruppe, FP)
    if "feedback_remarks_json" not in _existing_columns(insp, "exam_results"):
        with op.batch_alter_table("exam_results") as batch:
            batch.add_column(sa.Column(
                "feedback_remarks_json", sa.Text(),
                nullable=False, server_default="{}",
            ))
    if "feedback_remarks_json" not in _existing_columns(insp, "exam_group_results"):
        with op.batch_alter_table("exam_group_results") as batch:
            batch.add_column(sa.Column(
                "feedback_remarks_json", sa.Text(),
                nullable=False, server_default="{}",
            ))

    # Schriftliche Notenbezeichnungen pro Skala
    if "grade_names_json" not in _existing_columns(insp, "grading_scales"):
        with op.batch_alter_table("grading_scales") as batch:
            batch.add_column(sa.Column(
                "grade_names_json", sa.Text(),
                nullable=False, server_default="{}",
            ))

    # Unterschrift + Paraphe pro Lehrer
    user_cols = _existing_columns(insp, "users")
    additions = []
    if "signature_data" not in user_cols:
        additions.append(sa.Column("signature_data", sa.LargeBinary(), nullable=True))
    if "signature_mime" not in user_cols:
        additions.append(sa.Column("signature_mime", sa.String(80),
                                   nullable=False, server_default=""))
    if "paraphe_data" not in user_cols:
        additions.append(sa.Column("paraphe_data", sa.LargeBinary(), nullable=True))
    if "paraphe_mime" not in user_cols:
        additions.append(sa.Column("paraphe_mime", sa.String(80),
                                   nullable=False, server_default=""))
    if additions:
        with op.batch_alter_table("users") as batch:
            for col in additions:
                batch.add_column(col)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        for c in ("paraphe_mime", "paraphe_data", "signature_mime", "signature_data"):
            try:
                batch.drop_column(c)
            except Exception:
                pass
    with op.batch_alter_table("grading_scales") as batch:
        try:
            batch.drop_column("grade_names_json")
        except Exception:
            pass
    with op.batch_alter_table("exam_group_results") as batch:
        try:
            batch.drop_column("feedback_remarks_json")
        except Exception:
            pass
    with op.batch_alter_table("exam_results") as batch:
        try:
            batch.drop_column("feedback_remarks_json")
        except Exception:
            pass
    with op.batch_alter_table("exams") as batch:
        try:
            batch.drop_column("bewertung_mode")
        except Exception:
            pass
