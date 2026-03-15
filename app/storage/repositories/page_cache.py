import uuid
import hashlib
from datetime import datetime, timezone
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.storage.models import WikiPageCache


async def get_cached_page(db: AsyncSession, org_id: str, page_id: str) -> WikiPageCache | None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(WikiPageCache).where(
            WikiPageCache.org_id == org_id,
            WikiPageCache.page_id == page_id,
            WikiPageCache.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def upsert_page(
    db: AsyncSession,
    org_id: str,
    page_id: str,
    slug: str | None,
    title: str | None,
    content_raw: str,
    expires_at: datetime,
) -> WikiPageCache:
    content_hash = hashlib.sha256(content_raw.encode()).hexdigest()
    existing = await db.execute(
        select(WikiPageCache).where(WikiPageCache.org_id == org_id, WikiPageCache.page_id == page_id)
    )
    page = existing.scalar_one_or_none()
    if page is not None:
        page.slug = slug
        page.title = title
        page.content_raw = content_raw
        page.content_hash = content_hash
        page.cached_at = datetime.now(timezone.utc)
        page.expires_at = expires_at
        await db.flush()
        return page
    page = WikiPageCache(
        id=uuid.uuid4(),
        org_id=org_id,
        page_id=page_id,
        slug=slug,
        title=title,
        content_raw=content_raw,
        content_hash=content_hash,
        cached_at=datetime.now(timezone.utc),
        expires_at=expires_at,
    )
    db.add(page)
    await db.flush()
    return page


async def evict_expired(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        delete(WikiPageCache).where(WikiPageCache.expires_at <= now)
    )
    await db.flush()
    return result.rowcount
