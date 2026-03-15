import redis.asyncio as aioredis

_redis = None


def init_redis(dsn: str) -> None:
    global _redis
    _redis = aioredis.from_url(dsn, decode_responses=True)


def get_redis():
    if _redis is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _redis


def auth_session_key(session_id: str) -> str:
    return f"auth_session:{session_id}"


def auth_state_key(state: str) -> str:
    return f"auth_state:{state}"


def user_session_key(email: str) -> str:
    return f"user_session:{email}"


def wiki_page_key(org_id: str, page_id: str) -> str:
    return f"wiki_page:{org_id}:{page_id}"


def rate_limit_ip_key(ip: str) -> str:
    return f"rate_limit:ip:{ip}"


def rate_limit_email_key(email: str) -> str:
    return f"rate_limit:email:{email}"
