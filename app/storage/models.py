import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("yandex_uid", name="uq_users_yandex_uid"),
        Index("ix_users_email", "email"),
        Index("ix_users_yandex_uid", "yandex_uid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    yandex_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    __table_args__ = (
        Index("ix_oauth_tokens_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scope: Mapped[str] = mapped_column(String(255), nullable=False, default="wiki:read")
    token_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("state", name="uq_auth_sessions_state"),
        Index("ix_auth_sessions_state", "state"),
        Index("ix_auth_sessions_email_claimed", "email_claimed"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_claimed: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(128), nullable=False)
    code_verifier: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    return_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WikiPageCache(Base):
    __tablename__ = "wiki_page_cache"
    __table_args__ = (
        UniqueConstraint("org_id", "page_id", name="uq_wiki_page_cache_org_page"),
        Index("ix_wiki_page_cache_org_id_page_id", "org_id", "page_id"),
        Index("ix_wiki_page_cache_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    page_id: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_raw: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
