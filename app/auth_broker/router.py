import json
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.storage.db import get_db
from app.storage.redis_client import get_redis, auth_session_key, auth_state_key, user_session_key
from app.storage.repositories import auth_sessions as auth_sessions_repo
from app.storage.repositories import users as users_repo
from app.storage.repositories import tokens as tokens_repo
from app.storage.crypto import TokenCrypto
from app.auth_broker import oauth

import structlog

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

_SUCCESS_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Авторизация</title></head>
<body><h2>Авторизация завершена.</h2><p>Можно закрыть эту вкладку.</p></body></html>"""

_ERROR_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Ошибка</title></head>
<body><h2>Ошибка авторизации</h2><p>{message}</p></body></html>"""


def _error_page(message: str, status_code: int = 400) -> HTMLResponse:
    return HTMLResponse(content=_ERROR_HTML.format(message=message), status_code=status_code)


class StartAuthRequest(BaseModel):
    email: str


class StartAuthResponse(BaseModel):
    session_id: str
    auth_url: str
    expires_at: datetime


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    error_code: str | None = None


class LogoutRequest(BaseModel):
    email: str


@router.post("/start", response_model=StartAuthResponse)
async def start_auth(body: StartAuthRequest, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    state = oauth.generate_state()
    code_verifier = oauth.generate_code_verifier()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.AUTH_SESSION_TTL_SECONDS)

    session = await auth_sessions_repo.create_session(
        db, email, state, code_verifier, expires_at
    )
    await db.commit()

    auth_url = oauth.build_authorization_url(
        state=state,
        code_verifier=code_verifier,
        redirect_uri=settings.YANDEX_REDIRECT_URI,
        client_id=settings.YANDEX_CLIENT_ID,
    )

    redis = get_redis()
    session_data = {"session_id": str(session.id), "email": email, "state": state}
    ttl = settings.AUTH_SESSION_TTL_SECONDS
    await redis.setex(auth_session_key(str(session.id)), ttl, json.dumps(session_data))
    await redis.setex(auth_state_key(state), ttl, str(session.id))

    logger.info("auth_start", email=email, session_id=str(session.id))
    return StartAuthResponse(
        session_id=str(session.id),
        auth_url=auth_url,
        expires_at=expires_at,
    )


@router.get("/callback")
async def auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if not state:
        return _error_page("Missing state parameter.")

    redis = get_redis()
    session_id_str = await redis.get(auth_state_key(state))
    if not session_id_str:
        db_session = await auth_sessions_repo.get_by_state(db, state)
        if db_session is None:
            return _error_page("Session not found or expired.", 404)
        session_id_str = str(db_session.id)

    try:
        session_id = uuid.UUID(session_id_str)
    except ValueError:
        return _error_page("Invalid session ID.", 400)

    auth_session = await auth_sessions_repo.get_by_id(db, session_id)
    if auth_session is None:
        return _error_page("Session not found.", 404)

    now = datetime.now(timezone.utc)
    if auth_session.expires_at.replace(tzinfo=timezone.utc) < now:
        await auth_sessions_repo.fail_session(db, session_id, "expired", "Session expired")
        await db.commit()
        return _error_page("Session has expired.")

    if error:
        await auth_sessions_repo.fail_session(db, session_id, error, error_description or "")
        await db.commit()
        await redis.delete(auth_state_key(state))
        return _error_page(f"Authorization error: {error_description or error}")

    if not code:
        return _error_page("Missing authorization code.")

    try:
        token_data = await oauth.exchange_code(
            code=code,
            code_verifier=auth_session.code_verifier,
            redirect_uri=settings.YANDEX_REDIRECT_URI,
            client_id=settings.YANDEX_CLIENT_ID,
            client_secret=settings.YANDEX_CLIENT_SECRET,
        )
    except Exception as exc:
        logger.error("token_exchange_failed", error=str(exc))
        await auth_sessions_repo.fail_session(db, session_id, "token_exchange_failed", str(exc))
        await db.commit()
        await redis.delete(auth_state_key(state))
        return _error_page("Failed to exchange authorization code.")

    access_token = token_data.get("access_token", "")
    try:
        user_info = await oauth.get_user_info(access_token)
    except Exception as exc:
        logger.error("userinfo_failed", error=str(exc))
        await auth_sessions_repo.fail_session(db, session_id, "userinfo_failed", str(exc))
        await db.commit()
        await redis.delete(auth_state_key(state))
        return _error_page("Failed to retrieve user information.")

    profile_email = (user_info.get("default_email") or "").strip().lower()
    if profile_email != auth_session.email_claimed.lower():
        logger.warning("email_mismatch", claimed=auth_session.email_claimed, profile=profile_email)
        await auth_sessions_repo.fail_session(db, session_id, "email_mismatch", "Email mismatch")
        await db.commit()
        await redis.delete(auth_state_key(state))
        return _error_page("Email mismatch: the logged-in account does not match the claimed email.")

    crypto = TokenCrypto(settings.TOKEN_ENCRYPTION_KEY)
    access_enc = crypto.encrypt(access_token)
    refresh_token = token_data.get("refresh_token")
    refresh_enc = crypto.encrypt(refresh_token) if refresh_token else None

    expires_in = token_data.get("expires_in")
    access_exp = None
    if expires_in:
        access_exp = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    user = await users_repo.create_or_update(
        db,
        email=profile_email,
        yandex_uid=str(user_info.get("id", "")),
        org_id=settings.YANDEX_ORG_ID,
    )
    await tokens_repo.upsert_token(
        db,
        user_id=user.id,
        access_enc=access_enc,
        refresh_enc=refresh_enc,
        access_exp=access_exp,
        refresh_exp=None,
        scope=token_data.get("scope", "wiki:read"),
    )
    await users_repo.update_last_login(db, user.id)
    await auth_sessions_repo.complete_session(db, session_id)
    await db.commit()

    await redis.delete(auth_state_key(state))
    logger.info("auth_completed", email=profile_email, user_id=str(user.id))
    return HTMLResponse(content=_SUCCESS_HTML)


@router.get("/status/{session_id}", response_model=SessionStatusResponse)
async def session_status(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        return JSONResponse({"error": "invalid session_id"}, status_code=400)

    session = await auth_sessions_repo.get_by_id(db, sid)
    if session is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    now = datetime.now(timezone.utc)
    status = session.status
    if status == "pending" and session.expires_at.replace(tzinfo=timezone.utc) < now:
        status = "expired"

    return SessionStatusResponse(
        session_id=session_id,
        status=status,
        error_code=session.error_code,
    )


@router.post("/logout")
async def logout(body: LogoutRequest, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    user = await users_repo.get_by_email(db, email)
    if user is not None:
        await tokens_repo.revoke_tokens(db, user.id)
        await db.commit()
    redis = get_redis()
    await redis.delete(user_session_key(email))
    logger.info("logout", email=email)
    return {"ok": True}
