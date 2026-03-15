import json
from datetime import datetime, timezone, timedelta
import structlog

from app.config import settings
from app.storage.crypto import TokenCrypto
from app.storage.repositories import users as users_repo
from app.storage.repositories import tokens as tokens_repo
from app.storage.repositories import auth_sessions as auth_sessions_repo
from app.storage.redis_client import auth_session_key, auth_state_key
from app.auth_broker.oauth import generate_state, generate_code_verifier, build_authorization_url
from app.wiki_adapter.client import WikiAdapter, AuthRequiredError, PageNotFoundError, AccessDeniedError

logger = structlog.get_logger()


def _needs_auth_response(email: str, session_id: str, auth_url: str, expires_at: datetime) -> dict:
    return {
        "ok": False,
        "needs_auth": True,
        "email": email,
        "session_id": session_id,
        "auth_url": auth_url,
        "expires_at": expires_at.isoformat(),
        "message": "Authentication required. Visit auth_url to authorize, then retry.",
    }


async def _ensure_auth_session(email: str, db, redis) -> tuple[str, str, datetime]:
    state = generate_state()
    code_verifier = generate_code_verifier()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.AUTH_SESSION_TTL_SECONDS)
    session = await auth_sessions_repo.create_session(db, email, state, code_verifier, expires_at)
    await db.commit()
    auth_url = build_authorization_url(
        state=state,
        code_verifier=code_verifier,
        redirect_uri=settings.YANDEX_REDIRECT_URI,
        client_id=settings.YANDEX_CLIENT_ID,
    )
    session_data = {"session_id": str(session.id), "email": email, "state": state}
    ttl = settings.AUTH_SESSION_TTL_SECONDS
    await redis.setex(auth_session_key(str(session.id)), ttl, json.dumps(session_data))
    await redis.setex(auth_state_key(state), ttl, str(session.id))
    return str(session.id), auth_url, expires_at


async def wiki_auth_status(email: str, db, redis) -> dict:
    email = email.strip().lower()
    crypto = TokenCrypto(settings.TOKEN_ENCRYPTION_KEY)
    adapter = WikiAdapter(settings.YANDEX_ORG_ID, crypto, db, redis)
    token = await adapter._get_valid_token(email)
    if token is not None:
        return {"authorized": True, "needs_auth": False, "email": email}
    session_id, auth_url, expires_at = await _ensure_auth_session(email, db, redis)
    return {
        "authorized": False,
        "needs_auth": True,
        "email": email,
        "session_id": session_id,
        "auth_url": auth_url,
        "expires_at": expires_at.isoformat(),
    }


async def wiki_get_page(email: str, page_id: str | None, slug: str | None, db, redis) -> dict:
    email = email.strip().lower()
    if not page_id and not slug:
        return {"ok": False, "error": "Either page_id or slug must be provided."}
    crypto = TokenCrypto(settings.TOKEN_ENCRYPTION_KEY)
    adapter = WikiAdapter(settings.YANDEX_ORG_ID, crypto, db, redis)
    token = await adapter._get_valid_token(email)
    if token is None:
        session_id, auth_url, expires_at = await _ensure_auth_session(email, db, redis)
        return _needs_auth_response(email, session_id, auth_url, expires_at)
    try:
        if page_id:
            page = await adapter.get_page(email, page_id)
            source = "api"
        else:
            page = await adapter.get_page_by_slug(email, slug)
            source = "api"
        return {"ok": True, "page": page, "source": {"type": source}}
    except AuthRequiredError:
        session_id, auth_url, expires_at = await _ensure_auth_session(email, db, redis)
        return _needs_auth_response(email, session_id, auth_url, expires_at)
    except PageNotFoundError:
        return {"ok": False, "error": "Page not found."}
    except AccessDeniedError:
        return {"ok": False, "error": "Access denied."}
    except Exception as exc:
        logger.error("wiki_get_page_error", email=email, error=str(exc))
        return {"ok": False, "error": str(exc)}


async def wiki_search_pages(email: str, query: str, limit: int, db, redis) -> dict:
    email = email.strip().lower()
    if not query.strip():
        return {"ok": False, "error": "Query must not be empty."}
    limit = max(1, min(limit, 50))
    crypto = TokenCrypto(settings.TOKEN_ENCRYPTION_KEY)
    adapter = WikiAdapter(settings.YANDEX_ORG_ID, crypto, db, redis)
    token = await adapter._get_valid_token(email)
    if token is None:
        session_id, auth_url, expires_at = await _ensure_auth_session(email, db, redis)
        return _needs_auth_response(email, session_id, auth_url, expires_at)
    try:
        items = await adapter.search_pages(email, query, limit)
        return {"ok": True, "items": items}
    except AuthRequiredError:
        session_id, auth_url, expires_at = await _ensure_auth_session(email, db, redis)
        return _needs_auth_response(email, session_id, auth_url, expires_at)
    except AccessDeniedError:
        return {"ok": False, "error": "Access denied."}
    except Exception as exc:
        logger.error("wiki_search_error", email=email, error=str(exc))
        return {"ok": False, "error": str(exc)}


async def wiki_get_page_raw(email: str, page_id: str, db, redis) -> dict:
    email = email.strip().lower()
    if not page_id:
        return {"ok": False, "error": "page_id must not be empty."}
    crypto = TokenCrypto(settings.TOKEN_ENCRYPTION_KEY)
    adapter = WikiAdapter(settings.YANDEX_ORG_ID, crypto, db, redis)
    token = await adapter._get_valid_token(email)
    if token is None:
        session_id, auth_url, expires_at = await _ensure_auth_session(email, db, redis)
        return _needs_auth_response(email, session_id, auth_url, expires_at)
    try:
        content = await adapter.get_raw_content(email, page_id)
        return {"ok": True, "content_raw": content}
    except AuthRequiredError:
        session_id, auth_url, expires_at = await _ensure_auth_session(email, db, redis)
        return _needs_auth_response(email, session_id, auth_url, expires_at)
    except PageNotFoundError:
        return {"ok": False, "error": "Page not found."}
    except AccessDeniedError:
        return {"ok": False, "error": "Access denied."}
    except Exception as exc:
        logger.error("wiki_get_page_raw_error", email=email, error=str(exc))
        return {"ok": False, "error": str(exc)}
