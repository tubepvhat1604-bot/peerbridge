import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .db import database

bearer = HTTPBearer(auto_error=False)


def _jwt_secret_bytes() -> bytes:
    secret = get_settings().jwt_secret
    if secret is None or not secret.get_secret_value():
        raise HTTPException(status_code=500, detail="JWT_SECRET is not configured")
    return secret.get_secret_value().encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), int(rounds))
        return hmac.compare_digest(_b64(actual), expected)
    except (ValueError, TypeError):
        return False


def create_token(user_id: int) -> str:
    settings = get_settings()
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({
        "sub": str(user_id),
        "exp": int(time.time()) + settings.access_token_minutes * 60,
    }, separators=(",", ":")).encode())
    body = f"{header}.{payload}"
    signature = hmac.new(_jwt_secret_bytes(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def decode_token(token: str) -> int:
    try:
        header, payload, signature = token.split(".")
        body = f"{header}.{payload}"
        expected = hmac.new(_jwt_secret_bytes(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature)):
            raise ValueError("bad signature")
        data = json.loads(_unb64(payload))
        if int(data["exp"]) < int(time.time()):
            raise ValueError("expired")
        return int(data["sub"])
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Token không hợp lệ hoặc đã hết hạn")


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Thiếu Bearer token")
    user_id = decode_token(credentials.credentials)
    with database() as connection:
        row = connection.execute(
            "SELECT id, email, role, is_seed, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if not row or row["is_seed"]:
        raise HTTPException(status_code=401, detail="Người dùng không tồn tại")
    return dict(row)

