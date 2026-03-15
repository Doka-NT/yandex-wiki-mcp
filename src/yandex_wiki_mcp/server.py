"""MCP server for reading Yandex Wiki pages via the Yandex Wiki REST API."""

import os
from urllib.parse import urlparse

import httpx
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

YANDEX_WIKI_API_BASE = "https://api.wiki.yandex.net"

server = Server("yandex-wiki")


def _get_oauth_token() -> str:
    """Return the OAuth token from the environment, raising if absent."""
    token = os.getenv("YANDEX_WIKI_OAUTH_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "YANDEX_WIKI_OAUTH_TOKEN environment variable is not set. "
            "Please obtain a Yandex OAuth token and export it before starting "
            "the server: export YANDEX_WIKI_OAUTH_TOKEN=<your_token>"
        )
    return token


def _is_plain_slug(url: str) -> bool:
    """Return True when *url* looks like a bare wiki slug rather than a full URL.

    A plain slug has no URL scheme and its first path component contains no dots
    (which would indicate a hostname like ``wiki.yandex.ru``).
    """
    has_scheme = "://" in url
    first_component = url.split("/")[0]
    first_component_is_host = "." in first_component
    return not has_scheme and not first_component_is_host


def _extract_slug(url: str) -> str:
    """Extract the page slug (path) from a Yandex Wiki page URL.

    Examples
    --------
    - ``https://wiki.yandex.ru/org/team/page`` → ``org/team/page``
    - ``https://org.wiki.yandex.ru/team/page`` → ``team/page``
    - ``org/team/page``                        → ``org/team/page`` (passthrough)
    """
    url = url.strip()
    if not url:
        raise ValueError(f"Cannot extract a page slug from URL: {url!r}")
    if _is_plain_slug(url):
        slug = url.strip("/")
        if not slug:
            raise ValueError(f"Cannot extract a page slug from URL: {url!r}")
        return slug
    parsed = urlparse(url if "://" in url else f"https://{url}")
    slug = parsed.path.strip("/")
    if not slug:
        raise ValueError(f"Cannot extract a page slug from URL: {url!r}")
    return slug


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"OAuth {token}",
        "Accept": "application/json",
    }


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="read_page",
            description=(
                "Read the content of a Yandex Wiki page by its URL. "
                "Returns the page body in wiki markup (source format). "
                "Requires YANDEX_WIKI_OAUTH_TOKEN to be set in the environment."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "Full URL of the Yandex Wiki page, e.g. "
                            "https://wiki.yandex.ru/org/team/page"
                        ),
                    }
                },
                "required": ["url"],
            },
        )
    ]


@server.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if name != "read_page":
        raise ValueError(f"Unknown tool: {name!r}")

    url = arguments.get("url", "").strip()
    if not url:
        raise ValueError("'url' argument is required and must not be empty")

    token = _get_oauth_token()
    slug = _extract_slug(url)

    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: get page metadata to obtain the numeric page id
        meta_response = await client.get(
            f"{YANDEX_WIKI_API_BASE}/v1/pages",
            headers=_auth_headers(token),
            params={"slug": slug},
        )
        meta_response.raise_for_status()
        meta = meta_response.json()

        # Normalise: some API versions wrap results in a list
        if isinstance(meta, list):
            meta = meta[0] if meta else {}

        page_id = meta.get("id")

        if page_id:
            # Step 2: fetch the page body using its id
            body_response = await client.get(
                f"{YANDEX_WIKI_API_BASE}/v1/pages/{page_id}/body",
                headers=_auth_headers(token),
            )
            body_response.raise_for_status()
            body_data = body_response.json()
            content = body_data.get("body", body_data.get("source", ""))
        else:
            # Fallback: return whatever the metadata endpoint returned
            content = meta.get("body", meta.get("source", str(meta)))

    return [types.TextContent(type="text", text=str(content))]


def main() -> None:
    """Entry point – run the MCP server over stdio."""
    import asyncio

    async def _run() -> None:
        async with mcp.server.stdio.stdio_server(server):
            await asyncio.Event().wait()  # run forever

    asyncio.run(_run())


if __name__ == "__main__":
    main()
