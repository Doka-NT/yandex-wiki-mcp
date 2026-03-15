"""MCP server for reading Yandex Wiki pages via the Yandex Wiki REST API."""

import os
import threading
import time
from urllib.parse import urlparse

import httpx
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

YANDEX_WIKI_API_BASE = "https://api.wiki.yandex.net"
TOKEN_TTL_SECONDS = 2 * 60 * 60  # 2 hours

# Link shown to users when they need to obtain a new OAuth token.
YANDEX_OAUTH_URL = "https://oauth.yandex.ru"
YANDEX_WIKI_API_DOCS_URL = "https://yandex.ru/support/wiki/api-ref/access.html"

server = Server("yandex-wiki")

# In-memory token store: email -> (oauth_token, expiry_timestamp)
_token_store: dict[str, tuple[str, float]] = {}
_token_store_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def _get_user_email() -> str:
    """Return the current user's email from the environment, raising if absent."""
    email = os.getenv("YANDEX_WIKI_USER_EMAIL", "").strip().lower()
    if not email:
        raise ValueError(
            "YANDEX_WIKI_USER_EMAIL environment variable is not set. "
            "Please set it to your Yandex account email before starting the server: "
            "export YANDEX_WIKI_USER_EMAIL=user@yandex.ru"
        )
    return email


def _token_required_message(email: str) -> str:
    """Return a human-readable message explaining how to obtain and register a token."""
    return (
        f"No valid OAuth token found for {email!r}.\n"
        "To fix this, obtain a Yandex OAuth token and register it:\n"
        f"  1. Open {YANDEX_OAUTH_URL} and create an application with wiki:read permission.\n"
        "  2. Copy your token.\n"
        "  3. Call: register_token(oauth_token=\"<your_token>\")\n"
        f"Documentation: {YANDEX_WIKI_API_DOCS_URL}"
    )


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


def get_token_for_user(email: str) -> str | None:
    """Return the stored OAuth token for *email*, or None if absent/expired."""
    email = email.strip().lower()
    with _token_store_lock:
        entry = _token_store.get(email)
        if entry is None:
            return None
        token, expiry = entry
        if time.monotonic() > expiry:
            del _token_store[email]
            return None
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
                "Register your Yandex OAuth token so read_page can access the Wiki on your behalf. "
                "The token is stored in memory for 2 hours. "
                "Your email is read automatically from the YANDEX_WIKI_USER_EMAIL environment variable. "
                "Call this tool once before using read_page, or whenever read_page reports that the token is missing or expired."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "oauth_token": {
                        "type": "string",
                        "description": (
                            "Your Yandex OAuth token with wiki:read permission. "
                            f"Obtain it at {YANDEX_OAUTH_URL}"
                        ),
                    },
                },
                "required": ["oauth_token"],
            },
        ),
        types.Tool(
            name="read_page",
            description=(
                "Read the content of a Yandex Wiki page by its URL. "
                "Returns the page body in wiki markup (source format). "
                "Your email is read from the YANDEX_WIKI_USER_EMAIL environment variable. "
                "If no valid token is found, returns instructions on how to register one."
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
                },
                "required": ["url"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(
    name: str, arguments: dict
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if name == "register_token":
        email = _get_user_email()
        oauth_token = arguments.get("oauth_token", "")
        store_token(email, oauth_token)
        return [
            types.TextContent(
                type="text",
                text=(
                    f"OAuth token for {email!r} registered successfully. "
                    "It will expire in 2 hours."
                ),
            )
        ]

    if name == "read_page":
        url = arguments.get("url", "").strip()
        if not url:
            raise ValueError("'url' argument is required and must not be empty")

        email = _get_user_email()

        # Check token before making any HTTP call
        token = get_token_for_user(email)
        if token is None:
            return [types.TextContent(type="text", text=_token_required_message(email))]

        slug = _extract_slug(url)

        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: get page metadata to obtain the numeric page id
            meta_response = await client.get(
                f"{YANDEX_WIKI_API_BASE}/v1/pages",
                headers=_auth_headers(token),
                params={"slug": slug},
            )
            if meta_response.status_code in (401, 403):
                return [types.TextContent(type="text", text=_token_required_message(email))]
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
                if body_response.status_code in (401, 403):
                    return [types.TextContent(type="text", text=_token_required_message(email))]
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

