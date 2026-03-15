"""MCP server for reading Yandex Wiki pages via the Yandex Wiki REST API."""

import threading
import time
from urllib.parse import urlparse

import httpx
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

YANDEX_WIKI_API_BASE = "https://api.wiki.yandex.net"
TOKEN_TTL_SECONDS = 2 * 60 * 60  # 2 hours

server = Server("yandex-wiki")

# In-memory token store: email -> (oauth_token, expiry_timestamp)
_token_store: dict[str, tuple[str, float]] = {}
_token_store_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Token store helpers
# ---------------------------------------------------------------------------

def store_token(email: str, oauth_token: str) -> None:
    """Store *oauth_token* for *email* with a 2-hour TTL."""
    email = email.strip().lower()
    oauth_token = oauth_token.strip()
    if not email:
        raise ValueError("'email' must not be empty")
    if not oauth_token:
        raise ValueError("'oauth_token' must not be empty")
    with _token_store_lock:
        _token_store[email] = (oauth_token, time.monotonic() + TOKEN_TTL_SECONDS)


def get_token_for_user(email: str) -> str:
    """Return the stored OAuth token for *email*, raising if absent or expired."""
    email = email.strip().lower()
    with _token_store_lock:
        entry = _token_store.get(email)
        if entry is None:
            raise ValueError(
                f"No OAuth token registered for {email!r}. "
                "Call register_token(email, oauth_token) first."
            )
        token, expiry = entry
        if time.monotonic() > expiry:
            del _token_store[email]
            raise ValueError(
                f"OAuth token for {email!r} has expired (TTL is 2 hours). "
                "Call register_token(email, oauth_token) again."
            )
    return token


# ---------------------------------------------------------------------------
# URL → slug
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="register_token",
            description=(
                "Register a Yandex OAuth token for a user identified by their email. "
                "The token is stored in memory for 2 hours. "
                "Must be called before read_page."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Yandex account email address of the user.",
                    },
                    "oauth_token": {
                        "type": "string",
                        "description": (
                            "Yandex OAuth token with wiki:read permission. "
                            "Obtain it at https://oauth.yandex.ru"
                        ),
                    },
                },
                "required": ["email", "oauth_token"],
            },
        ),
        types.Tool(
            name="read_page",
            description=(
                "Read the content of a Yandex Wiki page by its URL. "
                "Returns the page body in wiki markup (source format). "
                "Requires the user's OAuth token to have been registered "
                "via register_token first."
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
                    },
                    "email": {
                        "type": "string",
                        "description": (
                            "Yandex account email address of the user whose "
                            "token should be used to fetch the page."
                        ),
                    },
                },
                "required": ["url", "email"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if name == "register_token":
        email = arguments.get("email", "")
        oauth_token = arguments.get("oauth_token", "")
        store_token(email, oauth_token)
        display_email = email.strip().lower()
        return [
            types.TextContent(
                type="text",
                text=f"OAuth token for {display_email!r} registered successfully. It will expire in 2 hours.",
            )
        ]

    if name == "read_page":
        url = arguments.get("url", "").strip()
        if not url:
            raise ValueError("'url' argument is required and must not be empty")

        email = arguments.get("email", "").strip()
        if not email:
            raise ValueError("'email' argument is required and must not be empty")

        token = get_token_for_user(email)
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

    raise ValueError(f"Unknown tool: {name!r}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point – run the MCP server over stdio."""
    import asyncio

    async def _run() -> None:
        async with mcp.server.stdio.stdio_server(server):
            await asyncio.Event().wait()  # run forever

    asyncio.run(_run())


if __name__ == "__main__":
    main()

