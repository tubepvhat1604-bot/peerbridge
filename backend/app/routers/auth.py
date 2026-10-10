import sqlite3

from fastapi import APIRouter, HTTPException

from ..admin_roles import promote_if_listed
from ..db import database, utc_now
from ..schemas import LoginRequest, RegisterRequest, TokenResponse
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest) -> TokenResponse:
    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
                (str(payload.email).lower(), hash_password(payload.password), utc_now()),
            )
            user_id = int(cursor.lastrowid)
            promote_if_listed(connection, user_id, str(payload.email))
            connection.execute(
                """INSERT INTO profiles(
                    user_id, display_name, age, city, intent, interests, available_times, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, payload.display_name.strip(), payload.age, payload.city.strip(), payload.intent, "[]", "[]", utc_now()),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Email đã được sử dụng")
    return TokenResponse(access_token=create_token(user_id), user_id=user_id)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    with database() as connection:
        row = connection.execute(
            "SELECT id, password_hash, is_seed FROM users WHERE email = ?", (str(payload.email).lower(),)
        ).fetchone()
    if not row or row["is_seed"] or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Email hoặc mật khẩu không đúng")
    with database() as connection:
        promote_if_listed(connection, int(row["id"]), str(payload.email))
    return TokenResponse(access_token=create_token(row["id"]), user_id=row["id"])

