"""init schema

Revision ID: 0001
Revises:
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="teacher"),
        sa.Column("full_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("must_change_pw", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("failed_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime, nullable=True),
        sa.Column("anthropic_key_enc", sa.LargeBinary, nullable=True),
        sa.Column("untis_creds_enc", sa.LargeBinary, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("last_login_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("user_agent", sa.String(255), nullable=False, server_default=""),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("actor_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(120), nullable=False, server_default=""),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_action", "audit_log")
    op.drop_index("ix_audit_log_at", "audit_log")
    op.drop_table("audit_log")
    op.drop_table("user_sessions")
    op.drop_index("ix_users_username", "users")
    op.drop_table("users")
