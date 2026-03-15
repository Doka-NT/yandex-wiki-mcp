# Yandex Wiki MCP Server

Production-ready multi-user MCP (Model Context Protocol) server for reading Yandex Wiki pages. Supports both a simple stdio server and a full HTTP remote server with OAuth 2.0 authentication.

## Architecture Overview

The system consists of 4 main components:

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  MCP Server  │  │ Auth Broker  │  │  Wiki Adapter    │  │
│  │  (SSE/HTTP)  │  │  /auth/*     │  │  (API + Cache)   │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                   │             │
│  ┌──────▼─────────────────▼───────────────────▼──────────┐  │
│  │                   Storage Layer                        │  │
│  │   PostgreSQL (SQLAlchemy async) + Redis (cache/state)  │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Components

1. **MCP Server** (`app/mcp_server/`) — FastMCP-based HTTP server exposing tools over SSE at `/mcp`
2. **Auth Broker** (`app/auth_broker/`) — OAuth 2.0 authorization code flow with PKCE
3. **Wiki Adapter** (`app/wiki_adapter/`) — Yandex Wiki REST API client with caching
4. **Storage** (`app/storage/`) — PostgreSQL ORM models, Redis client, encrypted token storage

## Quick Start with Docker Compose

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env with your Yandex OAuth credentials

# 2. Generate Fernet encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Add output as TOKEN_ENCRYPTION_KEY in .env

# 3. Start services
docker compose up -d

# 4. Check health
curl http://localhost:8000/docs
```

## Configuration

All settings can be configured via environment variables or `.env` file:

| Variable | Default | Required | Description |
|---|---|---|---|
| `APP_ENV` | `development` | No | Environment name |
| `APP_BASE_URL` | `http://localhost:8000` | No | Application base URL |
| `MCP_BASE_URL` | `http://localhost:8000` | No | MCP server URL |
| `AUTH_BASE_URL` | `http://localhost:8000` | No | Auth broker base URL |
| `YANDEX_CLIENT_ID` | — | **Yes** | Yandex OAuth app client ID |
| `YANDEX_CLIENT_SECRET` | — | **Yes** | Yandex OAuth app client secret |
| `YANDEX_REDIRECT_URI` | `http://localhost:8000/auth/callback` | No | OAuth callback URL |
| `YANDEX_ORG_ID` | — | **Yes** | Yandex organization ID |
| `POSTGRES_DSN` | `postgresql+asyncpg://wiki:wiki@localhost:5432/wiki` | No | PostgreSQL connection string |
| `REDIS_DSN` | `redis://localhost:6379/0` | No | Redis connection string |
| `TOKEN_ENCRYPTION_KEY` | — | **Yes** | Fernet key for encrypting OAuth tokens |
| `AUTH_SESSION_TTL_SECONDS` | `900` | No | Auth session timeout (15 min) |
| `PAGE_CACHE_TTL_SECONDS` | `300` | No | Wiki page cache TTL (5 min) |
| `ACCESS_TOKEN_REFRESH_SKEW_SECONDS` | `60` | No | Token refresh ahead-of-expiry window |
| `LOG_LEVEL` | `INFO` | No | Logging level |

## MCP Tools

Connect to the MCP server at `http://localhost:8000/mcp` using SSE transport.

### `wiki_auth_status`
Check if a user is authorized and get an auth URL if needed.

**Input:**
```json
{"email": "user@example.com"}
```

**Output (authorized):**
```json
{"authorized": true, "needs_auth": false, "email": "user@example.com"}
```

**Output (not authorized):**
```json
{
  "authorized": false,
  "needs_auth": true,
  "email": "user@example.com",
  "session_id": "...",
  "auth_url": "https://oauth.yandex.ru/authorize?...",
  "expires_at": "2024-01-01T00:15:00Z"
}
```

### `wiki_get_page`
Get a wiki page by ID or slug.

**Input:**
```json
{"email": "user@example.com", "page_id": "123456"}
```
or
```json
{"email": "user@example.com", "slug": "/org/team/page-name"}
```

**Output:**
```json
{
  "ok": true,
  "page": {"page_id": "123456", "slug": "/org/team/page-name", "title": "Page Title", "content": "..."},
  "source": {"type": "api"}
}
```

### `wiki_search_pages`
Search wiki pages by query.

**Input:**
```json
{"email": "user@example.com", "query": "deployment guide", "limit": 10}
```

**Output:**
```json
{
  "ok": true,
  "items": [{"page_id": "...", "slug": "...", "title": "..."}]
}
```

### `wiki_get_page_raw`
Get raw wiki page content.

**Input:**
```json
{"email": "user@example.com", "page_id": "123456"}
```

**Output:**
```json
{"ok": true, "content_raw": "..."}
```

## Auth Flow

```
User/Client         MCP Server          Auth Broker         Yandex OAuth
    │                    │                    │                    │
    │  wiki_get_page()   │                    │                    │
    ├──────────────────► │                    │                    │
    │                    │  (no token found)  │                    │
    │ needs_auth=true    │                    │                    │
    │ auth_url=...       │                    │                    │
    ◄──────────────────── │                    │                    │
    │                    │                    │                    │
    │  Open auth_url     │                    │                    │
    ├────────────────────────────────────────────────────────────► │
    │                    │                    │  GET /auth/callback │
    │                    │                    ◄────────────────────  │
    │                    │                    │  exchange code     │
    │                    │                    ├───────────────────► │
    │                    │                    │  tokens            │
    │                    │                    ◄────────────────────  │
    │                    │                    │  (encrypt & store) │
    │                    │                    │                    │
    │  wiki_get_page()   │                    │                    │
    ├──────────────────► │  (token found)     │                    │
    │  page content      │                    │                    │
    ◄──────────────────── │                    │                    │
```

## Local Development Setup

```bash
# Install dependencies
pip install -e ".[server,dev]"

# Start infrastructure
docker compose up postgres redis -d

# Copy and configure env
cp .env.example .env
# Set YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET, YANDEX_ORG_ID, TOKEN_ENCRYPTION_KEY

# Run database migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload

# Simple stdio server (original)
yandex-wiki-mcp
```

## Running Tests

```bash
# All tests
pytest tests/ -v

# Original stdio server tests only
pytest tests/test_server.py -v

# New component tests
pytest tests/test_auth_broker.py tests/test_wiki_adapter.py tests/test_tools.py -v
```

## Project Structure

```
├── src/yandex_wiki_mcp/   # Original stdio MCP server
├── app/                   # HTTP remote MCP server
│   ├── config.py          # Settings (pydantic-settings)
│   ├── main.py            # FastAPI app entry point
│   ├── mcp_server/        # MCP tool definitions
│   ├── auth_broker/       # OAuth 2.0 flow
│   ├── wiki_adapter/      # Yandex Wiki API client
│   └── storage/           # DB models, repositories, crypto
├── alembic/               # Database migrations
├── tests/                 # Test suite
├── docker-compose.yml     # Local dev infrastructure
├── Dockerfile             # Container image
└── .env.example           # Environment variable template
```
