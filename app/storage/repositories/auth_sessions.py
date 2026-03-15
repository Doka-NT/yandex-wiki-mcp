import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.storage.models import AuthSession


async def create_session(
    db: AsyncSession,
    email_claimed: str,
    state: str,
    code_verifier: str | None,
    expires_at: datetime,
    return_url: str | None = None,
) -> AuthSession:
    session = AuthSession(
        id=uuid.uuid4(),
        email_claimed=email_claimed.lower(),
        state=state,
        code_verifier=code_verifier,
        status="pending",
        return_url=return_url,
        created_at=datetime.now(timezone.utc),
        expires_at=expires_at,
    )
    db.add(session)
    await db.flush()
    return session


async def get_by_state(db: AsyncSession, state: str) -> AuthSession | None:
    result = await db.execute(select(AuthSession).where(AuthSession.state == state))
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, session_id: uuid.UUID) -> AuthSession | None:
    result = await db.execute(select(AuthSession).where(AuthSession.id == session_id))
    return result.scalar_one_or_none()


async def complete_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    result = await db.execute(select(AuthSession).where(AuthSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is not None:
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        await db.flush()


async def fail_session(db: AsyncSession, session_id: uuid.UUID, error_code: str, error_message: str) -> None:
    result = await db.execute(select(AuthSession).where(AuthSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is not None:
        session.status = "failed"
        session.error_code = error_code
        session.error_message = error_message
        await db.flush()
