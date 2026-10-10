import os
import tempfile
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.gettempdir()) / f"peerbridge-discovery-{uuid4().hex}.db"))
os.environ.setdefault("UPLOAD_DIRECTORY", str(Path(tempfile.gettempdir()) / f"peerbridge-uploads-{uuid4().hex}"))
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.config import get_settings
from app.db import database, utc_now
from app.main import app
from app.security import create_token
from fastapi.testclient import TestClient


def create_instructor() -> dict[str, str]:
    with database() as connection:
        cursor = connection.execute(
            """INSERT INTO users(email, role, password_hash, created_at)
               VALUES (?, 'INSTRUCTOR', ?, ?)""",
            (f"instructor-{uuid4().hex}@example.edu", "not-used", utc_now()),
        )
        user_id = int(cursor.lastrowid)
    return {"Authorization": f"Bearer {create_token(user_id)}"}


def test_discover_rejects_instructors() -> None:
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.get("/api/v1/discover", headers=create_instructor())

    assert response.status_code == 403
