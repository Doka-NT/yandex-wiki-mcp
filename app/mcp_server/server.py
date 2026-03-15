from mcp.server.fastmcp import FastMCP
from app.mcp_server import tools
from app.storage.db import get_db, AsyncSessionLocal
from app.storage.redis_client import get_redis

mcp = FastMCP("yandex-wiki")


async def _get_deps():
    if AsyncSessionLocal is None:
        raise RuntimeError("DB not initialized")
    async with AsyncSessionLocal() as db:
        redis = get_redis()
        return db, redis


@mcp.tool()
async def wiki_auth_status(email: str) -> dict:
    """Check auth status and get auth URL if needed."""
    db, redis = await _get_deps()
    async with db:
        return await tools.wiki_auth_status(email, db, redis)


@mcp.tool()
async def wiki_get_page(email: str, page_id: str = "", slug: str = "") -> dict:
    """Get a Yandex Wiki page by page_id or slug."""
    db, redis = await _get_deps()
    async with db:
        return await tools.wiki_get_page(email, page_id or None, slug or None, db, redis)


@mcp.tool()
async def wiki_search_pages(email: str, query: str, limit: int = 10) -> dict:
    """Search Yandex Wiki pages."""
    db, redis = await _get_deps()
    async with db:
        return await tools.wiki_search_pages(email, query, limit, db, redis)


@mcp.tool()
async def wiki_get_page_raw(email: str, page_id: str) -> dict:
    """Get raw content of a Yandex Wiki page."""
    db, redis = await _get_deps()
    async with db:
        return await tools.wiki_get_page_raw(email, page_id, db, redis)
