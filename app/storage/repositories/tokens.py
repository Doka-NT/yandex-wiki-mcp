import uuid
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.storage.models import OAuthToken


async def get_active_token(db: AsyncSession, user_id: uuid.UUID) -> OAuthToken | None:
    result = await db.execute(
        select(OAuthToken)
        .where(OAuthToken.user_id == user_id, OAuthToken.token_status == "active")
        .order_by(OAuthToken.created_at.desc())
    )
    return result.scalar_one_or_none()


async def upsert_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    access_enc: str,
    refresh_enc: str | None,
    access_exp: datetime | None,
    refresh_exp: datetime | None,
    scope: str = "wiki:read",
) -> OAuthToken:
    existing = await get_active_token(db, user_id)
    if existing is not None:
        existing.access_token_encrypted = access_enc
        if refresh_enc is not None:
            existing.refresh_token_encrypted = refresh_enc
        existing.access_token_expires_at = access_exp
        existing.refresh_token_expires_at = refresh_exp
        existing.scope = scope
        existing.token_status = "active"
        existing.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return existing
    token = OAuthToken(
        id=uuid.uuid4(),
        user_id=user_id,
        access_token_encrypted=access_enc,
        refresh_token_encrypted=refresh_enc,
        access_token_expires_at=access_exp,
        refresh_token_expires_at=refresh_exp,
        scope=scope,
        token_status="active",
    )
    db.add(token)
    await db.flush()
    return token


async def revoke_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(OAuthToken)
        .where(OAuthToken.user_id == user_id)
        .values(token_status="revoked", updated_at=datetime.now(timezone.utc))
    )
    await db.flush()


async def mark_refresh_required(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(OAuthToken)
        .where(OAuthToken.user_id == user_id, OAuthToken.token_status == "active")
        .values(token_status="refresh_required", updated_at=datetime.now(timezone.utc))
    )
    await db.flush()
