import json
import sqlite3
from collections import defaultdict
from datetime import time
from typing import Any

from ..schemas import ProfileMeUpdate, ProfileUpdate

ProfileBundle = dict[str, Any]


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _time_value(value: time) -> str:
    return value.isoformat()


def _rows_by_user(rows: list[sqlite3.Row]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["user_id"])].append(dict(row))
    return grouped


class ProfileRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_profile_bundle(self, user_id: int) -> ProfileBundle | None:
        profile = self.connection.execute(
            """SELECT user_id, display_name, age, city, occupation, bio, school, major,
                      subjects, learning_goals, intent, interests, available_times, avatar_style, avatar_url
               FROM profiles WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        if not profile:
            return None

        needs = self.connection.execute(
            """SELECT id, profile_user_id AS user_id, topic, description, current_level, target_outcome
               FROM help_needs WHERE profile_user_id = ? ORDER BY id""",
            (user_id,),
        ).fetchall()
        offers = self.connection.execute(
            """SELECT id, profile_user_id AS user_id, topic, description, proficiency_level, max_sessions_per_week
               FROM help_offers WHERE profile_user_id = ? ORDER BY id""",
            (user_id,),
        ).fetchall()
        availability = self.connection.execute(
            """SELECT id, profile_user_id AS user_id, day_of_week, start_time, end_time, timezone
               FROM availability WHERE profile_user_id = ? ORDER BY day_of_week, start_time, id""",
            (user_id,),
        ).fetchall()

        return {
            "profile": {
                "user_id": profile["user_id"],
                "display_name": profile["display_name"],
                "age": profile["age"],
                "city": profile["city"],
                "occupation": profile["occupation"],
                "bio": profile["bio"],
                "school": profile["school"],
                "major": profile["major"],
                "subjects": _json_list(profile["subjects"]),
                "learning_goals": _json_list(profile["learning_goals"]),
                "intent": profile["intent"],
                "interests": _json_list(profile["interests"]),
                "available_times": _json_list(profile["available_times"]),
                "avatar_style": profile["avatar_style"],
                "avatar_url": profile["avatar_url"],
            },
            "needs_help_with": [dict(row) for row in needs],
            "can_help_with": [dict(row) for row in offers],
            "availability": [dict(row) for row in availability],
        }

    def list_student_profile_bundles(self) -> list[ProfileBundle]:
        profiles = self.connection.execute(
            """SELECT p.user_id, p.display_name, p.age, p.city, p.occupation, p.bio, p.school, p.major,
                      p.subjects, p.learning_goals, p.intent, p.interests, p.available_times,
                      p.avatar_style, p.avatar_url
               FROM profiles p
               JOIN users u ON u.id = p.user_id
               WHERE u.role = 'STUDENT'
               ORDER BY p.user_id"""
        ).fetchall()
        if not profiles:
            return []

        user_ids = [int(profile["user_id"]) for profile in profiles]
        placeholders = ",".join("?" for _ in user_ids)
        needs = self.connection.execute(
            f"""SELECT id, profile_user_id AS user_id, topic, description, current_level, target_outcome
                FROM help_needs
                WHERE profile_user_id IN ({placeholders})
                ORDER BY profile_user_id, id""",
            user_ids,
        ).fetchall()
        offers = self.connection.execute(
            f"""SELECT id, profile_user_id AS user_id, topic, description, proficiency_level, max_sessions_per_week
                FROM help_offers
                WHERE profile_user_id IN ({placeholders})
                ORDER BY profile_user_id, id""",
            user_ids,
        ).fetchall()
        availability = self.connection.execute(
            f"""SELECT id, profile_user_id AS user_id, day_of_week, start_time, end_time, timezone
                FROM availability
                WHERE profile_user_id IN ({placeholders})
                ORDER BY profile_user_id, day_of_week, start_time, id""",
            user_ids,
        ).fetchall()

        needs_by_user = _rows_by_user(needs)
        offers_by_user = _rows_by_user(offers)
        availability_by_user = _rows_by_user(availability)

        return [
            {
                "profile": {
                    "user_id": profile["user_id"],
                    "display_name": profile["display_name"],
                    "age": profile["age"],
                    "city": profile["city"],
                    "occupation": profile["occupation"],
                    "bio": profile["bio"],
                    "school": profile["school"],
                    "major": profile["major"],
                    "subjects": _json_list(profile["subjects"]),
                    "learning_goals": _json_list(profile["learning_goals"]),
                    "intent": profile["intent"],
                    "interests": _json_list(profile["interests"]),
                    "available_times": _json_list(profile["available_times"]),
                    "avatar_style": profile["avatar_style"],
                    "avatar_url": profile["avatar_url"],
                },
                "needs_help_with": needs_by_user[int(profile["user_id"])],
                "can_help_with": offers_by_user[int(profile["user_id"])],
                "availability": availability_by_user[int(profile["user_id"])],
            }
            for profile in profiles
        ]

    def replace_peerbridge_profile(self, user_id: int, payload: ProfileMeUpdate, updated_at: str) -> bool:
        profile = payload.profile
        cursor = self.connection.execute(
            """UPDATE profiles SET display_name=?, bio=?, school=?, major=?, subjects=?, learning_goals=?, updated_at=?
               WHERE user_id=?""",
            (
                profile.display_name,
                profile.bio,
                profile.school,
                profile.major,
                json.dumps(profile.subjects, ensure_ascii=False),
                json.dumps(profile.learning_goals, ensure_ascii=False),
                updated_at,
                user_id,
            ),
        )
        if cursor.rowcount == 0:
            return False

        self.connection.execute("DELETE FROM help_needs WHERE profile_user_id = ?", (user_id,))
        self.connection.execute("DELETE FROM help_offers WHERE profile_user_id = ?", (user_id,))
        self.connection.execute("DELETE FROM availability WHERE profile_user_id = ?", (user_id,))

        self.connection.executemany(
            """INSERT INTO help_needs(
                profile_user_id, topic, description, current_level, target_outcome, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    user_id,
                    item.topic,
                    item.description,
                    item.current_level,
                    item.target_outcome,
                    updated_at,
                    updated_at,
                )
                for item in payload.needs_help_with
            ],
        )
        self.connection.executemany(
            """INSERT INTO help_offers(
                profile_user_id, topic, description, proficiency_level, max_sessions_per_week, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    user_id,
                    item.topic,
                    item.description,
                    item.proficiency_level,
                    item.max_sessions_per_week,
                    updated_at,
                    updated_at,
                )
                for item in payload.can_help_with
            ],
        )
        self.connection.executemany(
            """INSERT INTO availability(
                profile_user_id, day_of_week, start_time, end_time, timezone, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    user_id,
                    item.day_of_week,
                    _time_value(item.start_time),
                    _time_value(item.end_time),
                    item.timezone,
                    updated_at,
                    updated_at,
                )
                for item in payload.availability
            ],
        )
        return True

    def update_legacy_profile(self, user_id: int, payload: ProfileUpdate, updated_at: str) -> bool:
        cursor = self.connection.execute(
            """UPDATE profiles SET display_name=?, age=?, city=?, occupation=?, bio=?, intent=?,
                interests=?, available_times=?, updated_at=? WHERE user_id=?""",
            (
                payload.display_name.strip(),
                payload.age,
                payload.city.strip(),
                payload.occupation.strip(),
                payload.bio.strip(),
                payload.intent,
                json.dumps(payload.interests, ensure_ascii=False),
                json.dumps(payload.available_times, ensure_ascii=False),
                updated_at,
                user_id,
            ),
        )
        return cursor.rowcount > 0
