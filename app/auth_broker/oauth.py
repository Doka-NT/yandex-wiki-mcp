import secrets
import hashlib
import base64
from urllib.parse import urlencode
import httpx

YANDEX_AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
YANDEX_TOKEN_URL = "https://oauth.yandex.ru/token"
YANDEX_USERINFO_URL = "https://login.yandex.ru/info"


def generate_state() -> str:
    return secrets.token_hex(32)


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def compute_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def build_authorization_url(
    state: str,
    code_verifier: str | None,
    redirect_uri: str,
    client_id: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "wiki:read",
        "state": state,
    }
    if code_verifier is not None:
        params["code_challenge_method"] = "S256"
        params["code_challenge"] = compute_code_challenge(code_verifier)
    return f"{YANDEX_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(
    code: str,
    code_verifier: str | None,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if code_verifier is not None:
        data["code_verifier"] = code_verifier
    async with httpx.AsyncClient() as client:
        response = await client.post(YANDEX_TOKEN_URL, data=data)
        response.raise_for_status()
        return response.json()


async def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> dict:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(YANDEX_TOKEN_URL, data=data)
        response.raise_for_status()
        return response.json()


async def get_user_info(access_token: str) -> dict:
    headers = {"Authorization": f"OAuth {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(YANDEX_USERINFO_URL, headers=headers)
        response.raise_for_status()
        return response.json()
