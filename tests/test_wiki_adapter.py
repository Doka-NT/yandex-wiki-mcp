import pytest
import respx
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from app.wiki_adapter.client import WikiAdapter, PageNotFoundError, AccessDeniedError, AuthRequiredError
from app.storage.crypto import TokenCrypto


def make_crypto():
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    return TokenCrypto(key)


def make_token_record(expired=False, status="active"):
    record = MagicMock()
    record.token_status = status
    record.access_token_encrypted = make_crypto().encrypt("test_access_token")
    record.refresh_token_encrypted = None
    if expired:
        record.access_token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    else:
        record.access_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    record.refresh_token_expires_at = None
    record.scope = "wiki:read"
    return record


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    return redis


@pytest.mark.asyncio
async def test_get_page_not_found(mock_db, mock_redis):
    crypto = make_crypto()
    adapter = WikiAdapter("test_org", crypto, mock_db, mock_redis)

    with patch("app.wiki_adapter.client.users_repo.get_by_email") as mock_user, \
         patch("app.wiki_adapter.client.tokens_repo.get_active_token") as mock_token, \
         patch("app.wiki_adapter.client.page_cache_repo.get_cached_page") as mock_cache:

        mock_user.return_value = MagicMock(id="user-1")
        token_record = make_token_record()
        token_record.access_token_encrypted = crypto.encrypt("test_token")
        mock_token.return_value = token_record
        mock_cache.return_value = None

        with respx.mock:
            respx.get("https://api.wiki.yandex.net/v1/pages/nonexistent").mock(
                return_value=httpx.Response(404)
            )
            with pytest.raises(PageNotFoundError):
                await adapter.get_page("user@example.com", "nonexistent")


@pytest.mark.asyncio
async def test_get_page_cache_hit(mock_db, mock_redis):
    crypto = make_crypto()
    adapter = WikiAdapter("test_org", crypto, mock_db, mock_redis)

    cached_data = {"page_id": "123", "slug": "/test", "title": "Test", "content": "Hello"}
    import json
    mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))

    with patch("app.wiki_adapter.client.users_repo.get_by_email") as mock_user, \
         patch("app.wiki_adapter.client.tokens_repo.get_active_token") as mock_token:

        mock_user.return_value = MagicMock(id="user-1")
        mock_token.return_value = make_token_record()

        result = await adapter.get_page("user@example.com", "123")
        assert result["page_id"] == "123"
        assert result["title"] == "Test"


@pytest.mark.asyncio
async def test_get_page_access_denied(mock_db, mock_redis):
    crypto = make_crypto()
    adapter = WikiAdapter("test_org", crypto, mock_db, mock_redis)

    with patch("app.wiki_adapter.client.users_repo.get_by_email") as mock_user, \
         patch("app.wiki_adapter.client.tokens_repo.get_active_token") as mock_token, \
         patch("app.wiki_adapter.client.page_cache_repo.get_cached_page") as mock_cache:

        mock_user.return_value = MagicMock(id="user-1")
        token_record = make_token_record()
        token_record.access_token_encrypted = crypto.encrypt("test_token")
        mock_token.return_value = token_record
        mock_cache.return_value = None

        with respx.mock:
            respx.get("https://api.wiki.yandex.net/v1/pages/forbidden").mock(
                return_value=httpx.Response(403)
            )
            with pytest.raises(AccessDeniedError):
                await adapter.get_page("user@example.com", "forbidden")


@pytest.mark.asyncio
async def test_no_valid_token_returns_none(mock_db, mock_redis):
    crypto = make_crypto()
    adapter = WikiAdapter("test_org", crypto, mock_db, mock_redis)

    with patch("app.wiki_adapter.client.users_repo.get_by_email") as mock_user:
        mock_user.return_value = None
        result = await adapter._get_valid_token("unknown@example.com")
        assert result is None


@pytest.mark.asyncio
async def test_auth_required_when_no_token(mock_db, mock_redis):
    crypto = make_crypto()
    adapter = WikiAdapter("test_org", crypto, mock_db, mock_redis)

    with patch("app.wiki_adapter.client.users_repo.get_by_email") as mock_user, \
         patch("app.wiki_adapter.client.page_cache_repo.get_cached_page") as mock_cache:

        mock_user.return_value = None
        mock_cache.return_value = None

        with pytest.raises(AuthRequiredError):
            await adapter.get_page("nobody@example.com", "page-1")
