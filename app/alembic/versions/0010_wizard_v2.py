"""Wizard v2: Inhalts-MD-Felder + markdown_source auf worksheet_revisions

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("learning_situations") as batch:
        batch.add_column(sa.Column("last_material_type", sa.String(32),
                                   nullable=False, server_default=""))
        batch.add_column(sa.Column("last_extras", sa.Text(),
                                   nullable=False, server_default=""))
        batch.add_column(sa.Column("content_md_present", sa.Boolean(),
                                   nullable=False, server_default=sa.text("0")))

    with op.batch_alter_table("worksheet_revisions") as batch:
        batch.add_column(sa.Column("markdown_source", sa.Text(),
                                   nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("worksheet_revisions") as batch:
        batch.drop_column("markdown_source")

    with op.batch_alter_table("learning_situations") as batch:
        batch.drop_column("content_md_present")
        batch.drop_column("last_extras")
        batch.drop_column("last_material_type")
