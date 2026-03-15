import pytest
from app.auth_broker.oauth import (
    build_authorization_url,
    generate_state,
    generate_code_verifier,
    compute_code_challenge,
)


def test_generate_state_length():
    state = generate_state()
    assert len(state) == 64
    assert all(c in "0123456789abcdef" for c in state)


def test_generate_state_uniqueness():
    states = {generate_state() for _ in range(100)}
    assert len(states) == 100


def test_generate_code_verifier():
    verifier = generate_code_verifier()
    assert len(verifier) >= 43


def test_compute_code_challenge():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    challenge = compute_code_challenge(verifier)
    assert isinstance(challenge, str)
    assert len(challenge) > 0
    assert "=" not in challenge


def test_compute_code_challenge_s256():
    import hashlib, base64
    verifier = "test_verifier_string"
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert compute_code_challenge(verifier) == expected


def test_build_authorization_url_without_pkce():
    url = build_authorization_url(
        state="teststate",
        code_verifier=None,
        redirect_uri="http://localhost:8000/auth/callback",
        client_id="myclientid",
    )
    assert "oauth.yandex.ru/authorize" in url
    assert "state=teststate" in url
    assert "client_id=myclientid" in url
    assert "response_type=code" in url
    assert "code_challenge" not in url


def test_build_authorization_url_with_pkce():
    verifier = generate_code_verifier()
    url = build_authorization_url(
        state="teststate",
        code_verifier=verifier,
        redirect_uri="http://localhost:8000/auth/callback",
        client_id="myclientid",
    )
    assert "code_challenge_method=S256" in url
    assert "code_challenge=" in url


def test_email_normalization():
    email = "  User@Example.COM  "
    normalized = email.strip().lower()
    assert normalized == "user@example.com"
