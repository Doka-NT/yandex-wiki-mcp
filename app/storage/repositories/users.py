import uuid
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.storage.models import User


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def get_by_yandex_uid(db: AsyncSession, yandex_uid: str) -> User | None:
    result = await db.execute(select(User).where(User.yandex_uid == yandex_uid))
    return result.scalar_one_or_none()


async def create_or_update(db: AsyncSession, email: str, yandex_uid: str, org_id: str) -> User:
    email = email.lower()
    user = await get_by_email(db, email)
    if user is None:
        user = User(
            id=uuid.uuid4(),
            email=email,
            yandex_uid=yandex_uid,
            org_id=org_id,
        )
        db.add(user)
        await db.flush()
    else:
        user.yandex_uid = yandex_uid
        user.org_id = org_id
        user.updated_at = datetime.now(timezone.utc)
        await db.flush()
    return user


async def update_last_login(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(last_login_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    )
    await db.flush()
