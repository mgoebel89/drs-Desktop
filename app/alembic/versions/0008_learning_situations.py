"""learning_situations + smb_creds + FK-Verknüpfungen

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_situations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("klassen_key", sa.String(255), nullable=False, server_default=""),
        sa.Column("lernfeld", sa.String(64), nullable=False, server_default=""),
        sa.Column("smb_folder_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("obsidian_note_path", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_learning_situations_user", "learning_situations",
                    ["user_id"])
    op.create_index("ix_learning_situations_slug", "learning_situations",
                    ["user_id", "slug"], unique=True)
    op.create_index("ix_learning_situations_klassen", "learning_situations",
                    ["user_id", "klassen_key"])

    with op.batch_alter_table("lesson_notes") as batch:
        batch.add_column(sa.Column("learning_situation_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_lesson_notes_ls", "learning_situations",
            ["learning_situation_id"], ["id"], ondelete="SET NULL",
        )
    op.create_index("ix_lesson_notes_ls", "lesson_notes",
                    ["learning_situation_id"])

    with op.batch_alter_table("worksheets") as batch:
        batch.add_column(sa.Column("learning_situation_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_worksheets_ls", "learning_situations",
            ["learning_situation_id"], ["id"], ondelete="SET NULL",
        )
    op.create_index("ix_worksheets_ls", "worksheets",
                    ["learning_situation_id"])

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("smb_creds_enc", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("smb_creds_enc")

    op.drop_index("ix_worksheets_ls", "worksheets")
    with op.batch_alter_table("worksheets") as batch:
        batch.drop_constraint("fk_worksheets_ls", type_="foreignkey")
        batch.drop_column("learning_situation_id")

    op.drop_index("ix_lesson_notes_ls", "lesson_notes")
    with op.batch_alter_table("lesson_notes") as batch:
        batch.drop_constraint("fk_lesson_notes_ls", type_="foreignkey")
        batch.drop_column("learning_situation_id")

    op.drop_index("ix_learning_situations_klassen", "learning_situations")
    op.drop_index("ix_learning_situations_slug", "learning_situations")
    op.drop_index("ix_learning_situations_user", "learning_situations")
    op.drop_table("learning_situations")
