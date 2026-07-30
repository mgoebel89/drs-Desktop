"""Paperless-Konfiguration pro Nutzer (Dokumente-Modul).

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-30

Legt `users.paperless_cfg_enc` an: AES-GCM-verschlüsseltes JSON
{url, token, view_tag_ids, upload_tag_id, storage_path_id}. Idempotent —
die Spalte wird nur angelegt, wenn sie fehlt.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def _has_column(insp, table: str, column: str) -> bool:
    try:
        return column in {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return False


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not _has_column(insp, "users", "paperless_cfg_enc"):
        op.add_column(
            "users",
            sa.Column("paperless_cfg_enc", sa.LargeBinary(), nullable=True),
        )


def downgrade() -> None:
    try:
        op.drop_column("users", "paperless_cfg_enc")
    except Exception:
        pass
