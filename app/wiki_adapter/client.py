import json
from datetime import datetime, timezone, timedelta
import httpx
import structlog

from app.config import settings
from app.storage.crypto import TokenCrypto
from app.storage.repositories import users as users_repo
from app.storage.repositories import tokens as tokens_repo
from app.storage.repositories import page_cache as page_cache_repo
from app.storage.redis_client import wiki_page_key
from app.auth_broker import oauth

logger = structlog.get_logger()

WIKI_API_BASE = "https://api.wiki.yandex.net/v1"


class WikiError(Exception):
    pass


class PageNotFoundError(WikiError):
    pass


class AccessDeniedError(WikiError):
    pass


class AuthRequiredError(WikiError):
    pass


class WikiAdapter:
    def __init__(self, org_id: str, crypto: TokenCrypto, db_session, redis):
        self.org_id = org_id
        self.crypto = crypto
        self.db = db_session
        self.redis = redis

    async def _get_valid_token(self, email: str) -> str | None:
        user = await users_repo.get_by_email(self.db, email)
        if user is None:
            return None
        token_record = await tokens_repo.get_active_token(self.db, user.id)
        if token_record is None:
            return None
        if token_record.token_status == "revoked":
            return None

        now = datetime.now(timezone.utc)
        skew = timedelta(seconds=settings.ACCESS_TOKEN_REFRESH_SKEW_SECONDS)
        if token_record.access_token_expires_at is not None:
            exp = token_record.access_token_expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp - now < skew:
                refreshed = await self._refresh_token_for_user(user.id, token_record)
                if not refreshed:
                    return None
                token_record = await tokens_repo.get_active_token(self.db, user.id)
                if token_record is None:
                    return None

        return self.crypto.decrypt(token_record.access_token_encrypted)

    async def _refresh_token_for_user(self, user_id, token_record) -> bool:
        if not token_record.refresh_token_encrypted:
            await tokens_repo.revoke_tokens(self.db, user_id)
            await self.db.commit()
            return False
        try:
            refresh_token = self.crypto.decrypt(token_record.refresh_token_encrypted)
            token_data = await oauth.refresh_access_token(
                refresh_token=refresh_token,
                client_id=settings.YANDEX_CLIENT_ID,
                client_secret=settings.YANDEX_CLIENT_SECRET,
            )
        except Exception as exc:
            logger.error("token_refresh_failed", user_id=str(user_id), error=str(exc))
            await tokens_repo.revoke_tokens(self.db, user_id)
            await self.db.commit()
            return False

        new_access = token_data.get("access_token", "")
        new_refresh = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in")
        access_exp = None
        if expires_in:
            access_exp = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

        access_enc = self.crypto.encrypt(new_access)
        refresh_enc = self.crypto.encrypt(new_refresh) if new_refresh else token_record.refresh_token_encrypted

        await tokens_repo.upsert_token(
            self.db,
            user_id=user_id,
            access_enc=access_enc,
            refresh_enc=refresh_enc,
            access_exp=access_exp,
            refresh_exp=token_record.refresh_token_expires_at,
            scope=token_record.scope,
        )
        await self.db.commit()
        return True

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"OAuth {token}",
            "X-Org-Id": self.org_id,
        }

    def _normalize_page(self, data: dict) -> dict:
        return {
            "page_id": str(data.get("id") or data.get("page_id") or ""),
            "slug": data.get("slug") or data.get("url") or "",
            "title": data.get("title") or "",
            "content": data.get("body") or data.get("content") or "",
        }

    async def _get_cached(self, page_id: str) -> dict | None:
        redis_key = wiki_page_key(self.org_id, page_id)
        cached_str = await self.redis.get(redis_key)
        if cached_str:
            try:
                return json.loads(cached_str)
            except Exception:
                pass
        db_cached = await page_cache_repo.get_cached_page(self.db, self.org_id, page_id)
        if db_cached is not None:
            return {
                "page_id": db_cached.page_id,
                "slug": db_cached.slug or "",
                "title": db_cached.title or "",
                "content": db_cached.content_raw,
            }
        return None

    async def _store_cache(self, page: dict, content_raw: str) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.PAGE_CACHE_TTL_SECONDS)
        page_id = page.get("page_id", "")
        if page_id:
            redis_key = wiki_page_key(self.org_id, page_id)
            cache_data = {**page, "content": content_raw}
            await self.redis.setex(redis_key, settings.PAGE_CACHE_TTL_SECONDS, json.dumps(cache_data))
            await page_cache_repo.upsert_page(
                self.db,
                org_id=self.org_id,
                page_id=page_id,
                slug=page.get("slug"),
                title=page.get("title"),
                content_raw=content_raw,
                expires_at=expires_at,
            )
            await self.db.commit()

    async def _request(self, token: str, method: str, url: str, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, headers=self._headers(token), **kwargs)
        return response

    async def _handle_response(self, response: httpx.Response, email: str, retry_fn):
        if response.status_code == 401:
            user = await users_repo.get_by_email(self.db, email)
            if user:
                token_record = await tokens_repo.get_active_token(self.db, user.id)
                if token_record:
                    refreshed = await self._refresh_token_for_user(user.id, token_record)
                    if refreshed:
                        new_token = await self._get_valid_token(email)
                        if new_token:
                            return await retry_fn(new_token)
                await tokens_repo.revoke_tokens(self.db, user.id)
                await self.db.commit()
            raise AuthRequiredError("Authentication required. Token revoked or expired.")
        if response.status_code == 403:
            raise AccessDeniedError("Access denied.")
        if response.status_code == 404:
            raise PageNotFoundError("Page not found.")
        response.raise_for_status()
        return response

    async def get_page(self, email: str, page_id: str) -> dict:
        cached = await self._get_cached(page_id)
        if cached:
            return cached

        token = await self._get_valid_token(email)
        if token is None:
            raise AuthRequiredError("No valid token for user.")

        url = f"{WIKI_API_BASE}/pages/{page_id}"

        async def do_request(t: str) -> httpx.Response:
            return await self._request(t, "GET", url)

        response = await do_request(token)
        response = await self._handle_response(response, email, do_request)
        data = response.json()
        page = self._normalize_page(data)
        content = page.get("content", "")
        await self._store_cache(page, content)
        return page

    async def get_page_by_slug(self, email: str, slug: str) -> dict:
        token = await self._get_valid_token(email)
        if token is None:
            raise AuthRequiredError("No valid token for user.")

        url = f"{WIKI_API_BASE}/pages"

        async def do_request(t: str) -> httpx.Response:
            return await self._request(t, "GET", url, params={"slug": slug})

        response = await do_request(token)
        response = await self._handle_response(response, email, do_request)
        data = response.json()
        if isinstance(data, list) and data:
            page = self._normalize_page(data[0])
        else:
            page = self._normalize_page(data)
        content = page.get("content", "")
        if page.get("page_id"):
            await self._store_cache(page, content)
        return page

    async def search_pages(self, email: str, query: str, limit: int = 10) -> list[dict]:
        token = await self._get_valid_token(email)
        if token is None:
            raise AuthRequiredError("No valid token for user.")

        url = f"{WIKI_API_BASE}/pages/search"

        async def do_request(t: str) -> httpx.Response:
            return await self._request(t, "GET", url, params={"query": query, "limit": limit})

        response = await do_request(token)
        response = await self._handle_response(response, email, do_request)
        data = response.json()
        items = data if isinstance(data, list) else data.get("items", [])
        return [
            {
                "page_id": str(item.get("id") or item.get("page_id") or ""),
                "slug": item.get("slug") or item.get("url") or "",
                "title": item.get("title") or "",
            }
            for item in items
        ]

    async def get_raw_content(self, email: str, page_id: str) -> str:
        cached = await self._get_cached(page_id)
        if cached:
            return cached.get("content", "")

        token = await self._get_valid_token(email)
        if token is None:
            raise AuthRequiredError("No valid token for user.")

        url = f"{WIKI_API_BASE}/pages/{page_id}/body"

        async def do_request(t: str) -> httpx.Response:
            return await self._request(t, "GET", url)

        response = await do_request(token)
        response = await self._handle_response(response, email, do_request)
        if response.headers.get("content-type", "").startswith("application/json"):
            data = response.json()
            return data.get("body") or data.get("content") or ""
        return response.text
