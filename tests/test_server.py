"""Tests for the Yandex Wiki MCP server."""

import time

import httpx
import pytest
import respx

import yandex_wiki_mcp.server as server_module
from yandex_wiki_mcp.server import (
    _extract_slug,
    call_tool,
    get_token_for_user,
    list_tools,
    store_token,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_token_store():
    """Ensure the in-memory token store is empty before every test."""
    with server_module._token_store_lock:
        server_module._token_store.clear()
    yield
    with server_module._token_store_lock:
        server_module._token_store.clear()


FAKE_EMAIL = "user@example.com"
FAKE_TOKEN = "fake_oauth_token"
FAKE_SLUG = "org/team/page"
FAKE_URL = f"https://wiki.yandex.ru/{FAKE_SLUG}"
FAKE_PAGE_ID = "42"
FAKE_BODY = "= Hello =\nThis is the page content."


# ---------------------------------------------------------------------------
# _extract_slug
# ---------------------------------------------------------------------------

class TestExtractSlug:
    def test_full_url_wiki_yandex_ru(self):
        assert _extract_slug("https://wiki.yandex.ru/org/team/page") == "org/team/page"

    def test_subdomain_wiki_url(self):
        assert _extract_slug("https://org.wiki.yandex.ru/team/page") == "team/page"

    def test_trailing_slash(self):
        assert _extract_slug("https://wiki.yandex.ru/org/team/page/") == "org/team/page"

    def test_slug_passthrough(self):
        assert _extract_slug("org/team/page") == "org/team/page"

    def test_url_without_scheme(self):
        assert _extract_slug("wiki.yandex.ru/org/team/page") == "org/team/page"

    def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="Cannot extract"):
            _extract_slug("https://wiki.yandex.ru/")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            _extract_slug("  ")


# ---------------------------------------------------------------------------
# store_token / get_token_for_user
# ---------------------------------------------------------------------------

class TestTokenStore:
    def test_store_and_retrieve(self):
        store_token(FAKE_EMAIL, FAKE_TOKEN)
        assert get_token_for_user(FAKE_EMAIL) == FAKE_TOKEN

    def test_email_normalised_to_lowercase(self):
        store_token("User@Example.COM", FAKE_TOKEN)
        assert get_token_for_user("user@example.com") == FAKE_TOKEN

    def test_raises_when_no_token(self):
        with pytest.raises(ValueError, match="No OAuth token registered"):
            get_token_for_user(FAKE_EMAIL)

    def test_raises_on_empty_email(self):
        with pytest.raises(ValueError, match="'email'"):
            store_token("", FAKE_TOKEN)

    def test_raises_on_empty_token(self):
        with pytest.raises(ValueError, match="'oauth_token'"):
            store_token(FAKE_EMAIL, "")

    def test_raises_when_token_expired(self, monkeypatch):
        store_token(FAKE_EMAIL, FAKE_TOKEN)
        # Wind clock past TTL by one second
        original_monotonic = time.monotonic
        monkeypatch.setattr(
            server_module.time, "monotonic", lambda: original_monotonic() + server_module.TOKEN_TTL_SECONDS + 1
        )
        with pytest.raises(ValueError, match="expired"):
            get_token_for_user(FAKE_EMAIL)

    def test_overwrite_token(self):
        store_token(FAKE_EMAIL, "old_token")
        store_token(FAKE_EMAIL, "new_token")
        assert get_token_for_user(FAKE_EMAIL) == "new_token"

    def test_multiple_users_independent(self):
        store_token("alice@example.com", "token_alice")
        store_token("bob@example.com", "token_bob")
        assert get_token_for_user("alice@example.com") == "token_alice"
        assert get_token_for_user("bob@example.com") == "token_bob"


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tools_returns_both_tools():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert names == {"register_token", "read_page"}


@pytest.mark.asyncio
async def test_list_tools_register_token_schema():
    tools = await list_tools()
    tool = next(t for t in tools if t.name == "register_token")
    assert "email" in tool.inputSchema["properties"]
    assert "oauth_token" in tool.inputSchema["properties"]
    assert set(tool.inputSchema["required"]) == {"email", "oauth_token"}


@pytest.mark.asyncio
async def test_list_tools_read_page_schema():
    tools = await list_tools()
    tool = next(t for t in tools if t.name == "read_page")
    assert "url" in tool.inputSchema["properties"]
    assert "email" in tool.inputSchema["properties"]
    assert set(tool.inputSchema["required"]) == {"url", "email"}


# ---------------------------------------------------------------------------
# call_tool – register_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_token_stores_token():
    result = await call_tool("register_token", {"email": FAKE_EMAIL, "oauth_token": FAKE_TOKEN})
    assert len(result) == 1
    assert "registered successfully" in result[0].text
    assert get_token_for_user(FAKE_EMAIL) == FAKE_TOKEN


@pytest.mark.asyncio
async def test_register_token_raises_on_empty_email():
    with pytest.raises(ValueError, match="'email'"):
        await call_tool("register_token", {"email": "", "oauth_token": FAKE_TOKEN})


@pytest.mark.asyncio
async def test_register_token_raises_on_empty_token():
    with pytest.raises(ValueError, match="'oauth_token'"):
        await call_tool("register_token", {"email": FAKE_EMAIL, "oauth_token": ""})


# ---------------------------------------------------------------------------
# call_tool – read_page
# ---------------------------------------------------------------------------

@pytest.fixture
def registered_user():
    """Pre-register FAKE_EMAIL with FAKE_TOKEN in the store."""
    store_token(FAKE_EMAIL, FAKE_TOKEN)


@pytest.mark.asyncio
@respx.mock
async def test_read_page_returns_body(registered_user):
    respx.get("https://api.wiki.yandex.net/v1/pages").mock(
        return_value=httpx.Response(200, json={"id": FAKE_PAGE_ID, "slug": FAKE_SLUG})
    )
    respx.get(f"https://api.wiki.yandex.net/v1/pages/{FAKE_PAGE_ID}/body").mock(
        return_value=httpx.Response(200, json={"body": FAKE_BODY})
    )

    result = await call_tool("read_page", {"url": FAKE_URL, "email": FAKE_EMAIL})

    assert len(result) == 1
    assert result[0].type == "text"
    assert result[0].text == FAKE_BODY


@pytest.mark.asyncio
@respx.mock
async def test_read_page_fallback_to_source_field(registered_user):
    respx.get("https://api.wiki.yandex.net/v1/pages").mock(
        return_value=httpx.Response(200, json={"id": FAKE_PAGE_ID})
    )
    respx.get(f"https://api.wiki.yandex.net/v1/pages/{FAKE_PAGE_ID}/body").mock(
        return_value=httpx.Response(200, json={"source": FAKE_BODY})
    )

    result = await call_tool("read_page", {"url": FAKE_URL, "email": FAKE_EMAIL})

    assert result[0].text == FAKE_BODY


@pytest.mark.asyncio
@respx.mock
async def test_read_page_list_response(registered_user):
    """API returns a list of pages instead of a single object."""
    respx.get("https://api.wiki.yandex.net/v1/pages").mock(
        return_value=httpx.Response(200, json=[{"id": FAKE_PAGE_ID, "slug": FAKE_SLUG}])
    )
    respx.get(f"https://api.wiki.yandex.net/v1/pages/{FAKE_PAGE_ID}/body").mock(
        return_value=httpx.Response(200, json={"body": FAKE_BODY})
    )

    result = await call_tool("read_page", {"url": FAKE_URL, "email": FAKE_EMAIL})

    assert result[0].text == FAKE_BODY


@pytest.mark.asyncio
@respx.mock
async def test_read_page_no_id_fallback(registered_user):
    """When API does not return an id, return whatever the metadata endpoint gave us."""
    respx.get("https://api.wiki.yandex.net/v1/pages").mock(
        return_value=httpx.Response(200, json={"body": FAKE_BODY})
    )

    result = await call_tool("read_page", {"url": FAKE_URL, "email": FAKE_EMAIL})

    assert result[0].text == FAKE_BODY


@pytest.mark.asyncio
async def test_read_page_raises_on_missing_url(registered_user):
    with pytest.raises(ValueError, match="'url' argument"):
        await call_tool("read_page", {"email": FAKE_EMAIL})


@pytest.mark.asyncio
async def test_read_page_raises_on_missing_email():
    with pytest.raises(ValueError, match="'email' argument"):
        await call_tool("read_page", {"url": FAKE_URL})


@pytest.mark.asyncio
async def test_read_page_raises_when_token_not_registered():
    with pytest.raises(ValueError, match="No OAuth token registered"):
        await call_tool("read_page", {"url": FAKE_URL, "email": "unknown@example.com"})


@pytest.mark.asyncio
async def test_call_tool_raises_on_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool"):
        await call_tool("unknown_tool", {"url": FAKE_URL, "email": FAKE_EMAIL})


@pytest.mark.asyncio
@respx.mock
async def test_read_page_http_error_propagates(registered_user):
    respx.get("https://api.wiki.yandex.net/v1/pages").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await call_tool("read_page", {"url": FAKE_URL, "email": FAKE_EMAIL})


@pytest.mark.asyncio
@respx.mock
async def test_two_users_use_own_tokens():
    """Two users registered simultaneously each read with their own token."""
    store_token("alice@example.com", "token_alice")
    store_token("bob@example.com", "token_bob")

    def make_meta_response(request):
        auth = request.headers.get("Authorization", "")
        if "token_alice" in auth or "token_bob" in auth:
            return httpx.Response(200, json={"id": FAKE_PAGE_ID})
        return httpx.Response(403)

    def make_body_response(request):
        auth = request.headers.get("Authorization", "")
        if "token_alice" in auth:
            return httpx.Response(200, json={"body": "Alice's page"})
        if "token_bob" in auth:
            return httpx.Response(200, json={"body": "Bob's page"})
        return httpx.Response(403)

    respx.get("https://api.wiki.yandex.net/v1/pages").mock(side_effect=make_meta_response)
    respx.get(f"https://api.wiki.yandex.net/v1/pages/{FAKE_PAGE_ID}/body").mock(
        side_effect=make_body_response
    )

    alice_result = await call_tool("read_page", {"url": FAKE_URL, "email": "alice@example.com"})
    bob_result = await call_tool("read_page", {"url": FAKE_URL, "email": "bob@example.com"})

    assert alice_result[0].text == "Alice's page"
    assert bob_result[0].text == "Bob's page"

