"""Wizard-Zustandsfelder auf learning_situations

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("learning_situations") as batch:
        batch.add_column(sa.Column("lernziele", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("vorwissen", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("last_fobizz_prompt", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("last_fobizz_output", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("learning_situations") as batch:
        batch.drop_column("last_fobizz_output")
        batch.drop_column("last_fobizz_prompt")
        batch.drop_column("vorwissen")
        batch.drop_column("lernziele")
