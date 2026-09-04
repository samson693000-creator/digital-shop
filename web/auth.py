"""Web admin authentication helpers."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from itsdangerous import BadSignature, URLSafeTimedSerializer

from config import settings

SESSION_COOKIE = "admin_session"
MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="admin-auth")


def hash_password(password: str) -> str:
    return hashlib.sha256(
        (settings.secret_key + password).encode("utf-8")
    ).hexdigest()


def verify_credentials(username: str, password: str) -> bool:
    return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(
        password, settings.admin_password
    )


def create_session_token(username: str) -> str:
    return _serializer().dumps({"u": username, "n": secrets.token_hex(8)})


def load_session_token(token: str) -> str | None:
    try:
        data = _serializer().loads(token, max_age=MAX_AGE)
        if data.get("u") == settings.admin_username:
            return data["u"]
    except BadSignature:
        return None
    return None
