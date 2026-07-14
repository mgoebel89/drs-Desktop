"""Vikunja-Konfiguration pro Nutzer (Aufgaben-Modul).

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-14

Legt `users.vikunja_cfg_enc` an: AES-GCM-verschlüsseltes JSON
{url, token, project_id}. Idempotent — die Spalte wird nur angelegt,
wenn sie fehlt.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def _has_column(insp, table: str, column: str) -> bool:
    try:
        return column in {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return False


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not _has_column(insp, "users", "vikunja_cfg_enc"):
        op.add_column(
            "users",
            sa.Column("vikunja_cfg_enc", sa.LargeBinary(), nullable=True),
        )


def downgrade() -> None:
    try:
        op.drop_column("users", "vikunja_cfg_enc")
    except Exception:
        pass
