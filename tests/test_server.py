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
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_token_store():
    """Ensure the in-memory token store is empty before every test."""
    with server_module._token_store_lock:
        server_module._token_store.clear()
    yield
    with server_module._token_store_lock:
        server_module._token_store.clear()


@pytest.fixture(autouse=True)
def set_user_email(monkeypatch):
    """Set the required YANDEX_WIKI_USER_EMAIL env var for every test."""
    monkeypatch.setenv("YANDEX_WIKI_USER_EMAIL", FAKE_EMAIL)


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

    def test_returns_none_when_no_token(self):
        assert get_token_for_user(FAKE_EMAIL) is None

    def test_raises_on_empty_email(self):
        with pytest.raises(ValueError, match="'email'"):
            store_token("", FAKE_TOKEN)

    def test_raises_on_empty_token(self):
        with pytest.raises(ValueError, match="'oauth_token'"):
            store_token(FAKE_EMAIL, "")

    def test_returns_none_when_token_expired(self, monkeypatch):
        store_token(FAKE_EMAIL, FAKE_TOKEN)
        # Wind clock past TTL by one second
        original_monotonic = time.monotonic
        monkeypatch.setattr(
            server_module.time,
            "monotonic",
            lambda: original_monotonic() + server_module.TOKEN_TTL_SECONDS + 1,
        )
        assert get_token_for_user(FAKE_EMAIL) is None

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
# _get_user_email
# ---------------------------------------------------------------------------

def test_get_user_email_raises_when_env_absent(monkeypatch):
    monkeypatch.delenv("YANDEX_WIKI_USER_EMAIL", raising=False)
    with pytest.raises(ValueError, match="YANDEX_WIKI_USER_EMAIL"):
        server_module._get_user_email()


def test_get_user_email_normalises_to_lowercase(monkeypatch):
    monkeypatch.setenv("YANDEX_WIKI_USER_EMAIL", "User@Example.COM")
    assert server_module._get_user_email() == "user@example.com"


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
    assert "oauth_token" in tool.inputSchema["properties"]
    # email is NOT an argument — it comes from the env var
    assert "email" not in tool.inputSchema["properties"]
    assert tool.inputSchema["required"] == ["oauth_token"]


@pytest.mark.asyncio
async def test_list_tools_read_page_schema():
    tools = await list_tools()
    tool = next(t for t in tools if t.name == "read_page")
    assert "url" in tool.inputSchema["properties"]
    # email is NOT an argument — it comes from the env var
    assert "email" not in tool.inputSchema["properties"]
    assert tool.inputSchema["required"] == ["url"]


# ---------------------------------------------------------------------------
# call_tool – register_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_token_stores_token():
    result = await call_tool("register_token", {"oauth_token": FAKE_TOKEN})
    assert len(result) == 1
    assert "registered successfully" in result[0].text
    assert get_token_for_user(FAKE_EMAIL) == FAKE_TOKEN


@pytest.mark.asyncio
async def test_register_token_uses_email_from_env(monkeypatch):
    monkeypatch.setenv("YANDEX_WIKI_USER_EMAIL", "other@example.com")
    await call_tool("register_token", {"oauth_token": FAKE_TOKEN})
    assert get_token_for_user("other@example.com") == FAKE_TOKEN


@pytest.mark.asyncio
async def test_register_token_raises_when_email_env_absent(monkeypatch):
    monkeypatch.delenv("YANDEX_WIKI_USER_EMAIL", raising=False)
    with pytest.raises(ValueError, match="YANDEX_WIKI_USER_EMAIL"):
        await call_tool("register_token", {"oauth_token": FAKE_TOKEN})


@pytest.mark.asyncio
async def test_register_token_raises_on_empty_token():
    with pytest.raises(ValueError, match="'oauth_token'"):
        await call_tool("register_token", {"oauth_token": ""})


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

    result = await call_tool("read_page", {"url": FAKE_URL})

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

    result = await call_tool("read_page", {"url": FAKE_URL})

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

    result = await call_tool("read_page", {"url": FAKE_URL})

    assert result[0].text == FAKE_BODY


@pytest.mark.asyncio
@respx.mock
async def test_read_page_no_id_fallback(registered_user):
    """When API does not return an id, return whatever the metadata endpoint gave us."""
    respx.get("https://api.wiki.yandex.net/v1/pages").mock(
        return_value=httpx.Response(200, json={"body": FAKE_BODY})
    )

    result = await call_tool("read_page", {"url": FAKE_URL})

    assert result[0].text == FAKE_BODY


@pytest.mark.asyncio
async def test_read_page_raises_on_missing_url(registered_user):
    with pytest.raises(ValueError, match="'url' argument"):
        await call_tool("read_page", {})


@pytest.mark.asyncio
async def test_read_page_raises_when_email_env_absent(monkeypatch, registered_user):
    monkeypatch.delenv("YANDEX_WIKI_USER_EMAIL", raising=False)
    with pytest.raises(ValueError, match="YANDEX_WIKI_USER_EMAIL"):
        await call_tool("read_page", {"url": FAKE_URL})


@pytest.mark.asyncio
async def test_read_page_returns_token_instructions_when_no_token_stored():
    """When no token is registered, read_page returns help text instead of raising."""
    result = await call_tool("read_page", {"url": FAKE_URL})
    assert len(result) == 1
    assert "register_token" in result[0].text
    assert server_module.YANDEX_OAUTH_URL in result[0].text


@pytest.mark.asyncio
async def test_read_page_returns_token_instructions_when_token_expired(monkeypatch):
    store_token(FAKE_EMAIL, FAKE_TOKEN)
    original_monotonic = time.monotonic
    monkeypatch.setattr(
        server_module.time,
        "monotonic",
        lambda: original_monotonic() + server_module.TOKEN_TTL_SECONDS + 1,
    )
    result = await call_tool("read_page", {"url": FAKE_URL})
    assert "register_token" in result[0].text


@pytest.mark.asyncio
@respx.mock
async def test_read_page_returns_token_instructions_on_401(registered_user):
    """HTTP 401 from the API returns token instructions instead of raising."""
    respx.get("https://api.wiki.yandex.net/v1/pages").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )

    result = await call_tool("read_page", {"url": FAKE_URL})

    assert "register_token" in result[0].text
    assert server_module.YANDEX_OAUTH_URL in result[0].text


@pytest.mark.asyncio
@respx.mock
async def test_read_page_returns_token_instructions_on_403(registered_user):
    """HTTP 403 from the API returns token instructions instead of raising."""
    respx.get("https://api.wiki.yandex.net/v1/pages").mock(
        return_value=httpx.Response(403, json={"error": "Forbidden"})
    )

    result = await call_tool("read_page", {"url": FAKE_URL})

    assert "register_token" in result[0].text
    assert server_module.YANDEX_OAUTH_URL in result[0].text


@pytest.mark.asyncio
@respx.mock
async def test_read_page_http_error_propagates_on_non_auth_errors(registered_user):
    """Non-auth HTTP errors (e.g. 500) still propagate as exceptions."""
    respx.get("https://api.wiki.yandex.net/v1/pages").mock(
        return_value=httpx.Response(500, json={"error": "Internal Server Error"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await call_tool("read_page", {"url": FAKE_URL})


@pytest.mark.asyncio
async def test_call_tool_raises_on_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool"):
        await call_tool("unknown_tool", {"url": FAKE_URL})


@pytest.mark.asyncio
@respx.mock
async def test_different_users_read_with_own_tokens(monkeypatch):
    """Each user email maps to its own token in the store; sequential reads use the right token."""
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

    monkeypatch.setenv("YANDEX_WIKI_USER_EMAIL", "alice@example.com")
    alice_result = await call_tool("read_page", {"url": FAKE_URL})

    monkeypatch.setenv("YANDEX_WIKI_USER_EMAIL", "bob@example.com")
    bob_result = await call_tool("read_page", {"url": FAKE_URL})

    assert alice_result[0].text == "Alice's page"
    assert bob_result[0].text == "Bob's page"


