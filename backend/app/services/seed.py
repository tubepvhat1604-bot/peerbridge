import json
from pathlib import Path

from ..db import database, utc_now
from ..security import hash_password


def seed_profiles() -> int:
    source = Path(__file__).resolve().parents[2] / "data" / "seed_profiles.json"
    profiles = json.loads(source.read_text(encoding="utf-8"))
    inserted = 0
    with database() as connection:
        for index, profile in enumerate(profiles):
            email = f"seed-{profile['slug']}@dongdieu.local"
            existing = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                continue
            cursor = connection.execute(
                "INSERT INTO users(email, password_hash, is_seed, simulated_interest, created_at) VALUES (?, ?, 1, ?, ?)",
                (email, hash_password(f"seed-{index}-not-for-login"), int(profile["simulated_interest"]), utc_now()),
            )
            connection.execute(
                """INSERT INTO profiles(
                    user_id, display_name, age, city, occupation, bio, intent,
                    interests, available_times, avatar_style, school, major, subjects, learning_goals, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cursor.lastrowid, profile["name"], profile["age"], profile["city"],
                    profile["occupation"], profile["bio"], profile["intent"],
                    json.dumps(profile["interests"], ensure_ascii=False),
                    json.dumps(profile["available_times"], ensure_ascii=False),
                    profile["avatar_style"], profile.get("school", ""), profile.get("major", ""),
                    json.dumps(profile.get("subjects", []), ensure_ascii=False),
                    json.dumps(profile.get("learning_goals", []), ensure_ascii=False),
                    utc_now(),
                ),
            )
            inserted += 1
    return inserted

