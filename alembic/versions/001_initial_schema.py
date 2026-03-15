"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("yandex_uid", sa.String(64), nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_unique_constraint("uq_users_yandex_uid", "users", ["yandex_uid"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_yandex_uid", "users", ["yandex_uid"])

    op.create_table(
        "oauth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_token_encrypted", sa.Text, nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text, nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.String(255), nullable=False, server_default="wiki:read"),
        sa.Column("token_status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_oauth_tokens_user_id", "oauth_tokens", ["user_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email_claimed", sa.String(255), nullable=False),
        sa.Column("state", sa.String(128), nullable=False),
        sa.Column("code_verifier", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("return_url", sa.String(2048), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_auth_sessions_state", "auth_sessions", ["state"])
    op.create_index("ix_auth_sessions_state", "auth_sessions", ["state"])
    op.create_index("ix_auth_sessions_email_claimed", "auth_sessions", ["email_claimed"])

    op.create_table(
        "wiki_page_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("page_id", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(1024), nullable=True),
        sa.Column("title", sa.String(1024), nullable=True),
        sa.Column("content_raw", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("cached_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint("uq_wiki_page_cache_org_page", "wiki_page_cache", ["org_id", "page_id"])
    op.create_index("ix_wiki_page_cache_org_id_page_id", "wiki_page_cache", ["org_id", "page_id"])
    op.create_index("ix_wiki_page_cache_expires_at", "wiki_page_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_table("wiki_page_cache")
    op.drop_table("auth_sessions")
    op.drop_table("oauth_tokens")
    op.drop_table("users")
