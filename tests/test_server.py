"""Tests for the Yandex Wiki MCP server."""

import os

import httpx
import pytest
import respx

from yandex_wiki_mcp.server import _extract_slug, _get_oauth_token, call_tool, list_tools


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
# _get_oauth_token
# ---------------------------------------------------------------------------

class TestGetOauthToken:
    def test_returns_token_from_env(self, monkeypatch):
        monkeypatch.setenv("YANDEX_WIKI_OAUTH_TOKEN", "test_token_123")
        assert _get_oauth_token() == "test_token_123"

    def test_raises_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("YANDEX_WIKI_OAUTH_TOKEN", raising=False)
        with pytest.raises(ValueError, match="YANDEX_WIKI_OAUTH_TOKEN"):
            _get_oauth_token()

    def test_raises_when_env_empty(self, monkeypatch):
        monkeypatch.setenv("YANDEX_WIKI_OAUTH_TOKEN", "   ")
        with pytest.raises(ValueError, match="YANDEX_WIKI_OAUTH_TOKEN"):
            _get_oauth_token()


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tools_returns_read_page():
    tools = await list_tools()
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "read_page"
    assert "url" in tool.inputSchema["properties"]
    assert "url" in tool.inputSchema["required"]


# ---------------------------------------------------------------------------
# call_tool – read_page
# ---------------------------------------------------------------------------

FAKE_TOKEN = "fake_oauth_token"
FAKE_SLUG = "org/team/page"
FAKE_URL = f"https://wiki.yandex.ru/{FAKE_SLUG}"
FAKE_PAGE_ID = "42"
FAKE_BODY = "= Hello =\nThis is the page content."


@pytest.fixture(autouse=True)
def set_oauth_token(monkeypatch):
    monkeypatch.setenv("YANDEX_WIKI_OAUTH_TOKEN", FAKE_TOKEN)


@pytest.mark.asyncio
@respx.mock
async def test_read_page_returns_body():
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
async def test_read_page_fallback_to_source_field():
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
async def test_read_page_list_response():
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
async def test_read_page_no_id_fallback():
    """When API does not return an id, return whatever the metadata endpoint gave us."""
    respx.get("https://api.wiki.yandex.net/v1/pages").mock(
        return_value=httpx.Response(200, json={"body": FAKE_BODY})
    )

    result = await call_tool("read_page", {"url": FAKE_URL})

    assert result[0].text == FAKE_BODY


@pytest.mark.asyncio
async def test_read_page_raises_on_missing_url():
    with pytest.raises(ValueError, match="'url' argument"):
        await call_tool("read_page", {})


@pytest.mark.asyncio
async def test_read_page_raises_on_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool"):
        await call_tool("unknown_tool", {"url": FAKE_URL})


@pytest.mark.asyncio
@respx.mock
async def test_read_page_http_error_propagates():
    respx.get("https://api.wiki.yandex.net/v1/pages").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await call_tool("read_page", {"url": FAKE_URL})
