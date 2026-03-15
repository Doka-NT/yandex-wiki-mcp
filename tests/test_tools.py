import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
import uuid

from app.mcp_server.tools import wiki_auth_status, wiki_get_page, wiki_search_pages, wiki_get_page_raw


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


@pytest.fixture
def mock_settings(monkeypatch):
    monkeypatch.setattr("app.mcp_server.tools.settings.TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_ORG_ID", "test_org")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_CLIENT_ID", "test_client")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr("app.mcp_server.tools.settings.AUTH_SESSION_TTL_SECONDS", 900)


@pytest.mark.asyncio
async def test_needs_auth_when_no_token(mock_db, mock_redis, monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.mcp_server.tools.settings.TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_ORG_ID", "test_org")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_CLIENT_ID", "test_client")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr("app.mcp_server.tools.settings.AUTH_SESSION_TTL_SECONDS", 900)

    with patch("app.mcp_server.tools.WikiAdapter") as MockAdapter, \
         patch("app.mcp_server.tools.auth_sessions_repo.create_session") as mock_create:

        adapter_instance = AsyncMock()
        adapter_instance._get_valid_token = AsyncMock(return_value=None)
        MockAdapter.return_value = adapter_instance

        session = MagicMock()
        session.id = uuid.uuid4()
        mock_create.return_value = session

        result = await wiki_auth_status("user@example.com", mock_db, mock_redis)
        assert result["authorized"] is False
        assert result["needs_auth"] is True
        assert "auth_url" in result


@pytest.mark.asyncio
async def test_auth_status_authorized(mock_db, mock_redis, monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.mcp_server.tools.settings.TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_ORG_ID", "test_org")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_CLIENT_ID", "test_client")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr("app.mcp_server.tools.settings.AUTH_SESSION_TTL_SECONDS", 900)

    with patch("app.mcp_server.tools.WikiAdapter") as MockAdapter:
        adapter_instance = AsyncMock()
        adapter_instance._get_valid_token = AsyncMock(return_value="valid_token")
        MockAdapter.return_value = adapter_instance

        result = await wiki_auth_status("user@example.com", mock_db, mock_redis)
        assert result["authorized"] is True
        assert result["needs_auth"] is False


@pytest.mark.asyncio
async def test_wiki_get_page_needs_auth(mock_db, mock_redis, monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.mcp_server.tools.settings.TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_ORG_ID", "test_org")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_CLIENT_ID", "test_client")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr("app.mcp_server.tools.settings.AUTH_SESSION_TTL_SECONDS", 900)

    with patch("app.mcp_server.tools.WikiAdapter") as MockAdapter, \
         patch("app.mcp_server.tools.auth_sessions_repo.create_session") as mock_create:

        adapter_instance = AsyncMock()
        adapter_instance._get_valid_token = AsyncMock(return_value=None)
        MockAdapter.return_value = adapter_instance

        session = MagicMock()
        session.id = uuid.uuid4()
        mock_create.return_value = session

        result = await wiki_get_page("user@example.com", "page-1", None, mock_db, mock_redis)
        assert result["ok"] is False
        assert result["needs_auth"] is True


@pytest.mark.asyncio
async def test_wiki_get_page_success(mock_db, mock_redis, monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.mcp_server.tools.settings.TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_ORG_ID", "test_org")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_CLIENT_ID", "test_client")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr("app.mcp_server.tools.settings.AUTH_SESSION_TTL_SECONDS", 900)

    with patch("app.mcp_server.tools.WikiAdapter") as MockAdapter:
        adapter_instance = AsyncMock()
        adapter_instance._get_valid_token = AsyncMock(return_value="valid_token")
        adapter_instance.get_page = AsyncMock(return_value={
            "page_id": "page-1",
            "slug": "/test",
            "title": "Test Page",
            "content": "Hello world",
        })
        MockAdapter.return_value = adapter_instance

        result = await wiki_get_page("user@example.com", "page-1", None, mock_db, mock_redis)
        assert result["ok"] is True
        assert result["page"]["page_id"] == "page-1"


@pytest.mark.asyncio
async def test_wiki_search_empty_query(mock_db, mock_redis, monkeypatch):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.mcp_server.tools.settings.TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_ORG_ID", "test_org")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_CLIENT_ID", "test_client")
    monkeypatch.setattr("app.mcp_server.tools.settings.YANDEX_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setattr("app.mcp_server.tools.settings.AUTH_SESSION_TTL_SECONDS", 900)

    result = await wiki_search_pages("user@example.com", "   ", 10, mock_db, mock_redis)
    assert result["ok"] is False
    assert "error" in result
