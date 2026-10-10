"""Trusted operator CLI. Assignment privileges are never exposed to learners or the LLM."""
import argparse

from .db import database


def assign_session(session_id: int, course_id: str, instructor_id: int) -> None:
    if not course_id.strip() or course_id.startswith("__"):
        raise ValueError("A real course ID is required")
    with database() as connection:
        session = connection.execute("SELECT learner_id, helper_id FROM study_sessions WHERE id = ?", (session_id,)).fetchone()
        instructor = connection.execute("SELECT role FROM users WHERE id = ? AND is_seed = 0", (instructor_id,)).fetchone()
        if session is None or instructor is None or instructor["role"] != "INSTRUCTOR":
            raise ValueError("Existing session and non-seed instructor required")
        connection.execute("INSERT OR IGNORE INTO session_instructors VALUES (?, ?)", (session_id, instructor_id))
        connection.executemany("INSERT OR IGNORE INTO course_memberships VALUES (?, ?)",
            [(course_id, user_id) for user_id in (*session, instructor_id)])
        connection.execute("INSERT INTO session_courses VALUES (?, ?) ON CONFLICT(session_id) DO UPDATE SET course_id=excluded.course_id",
            (session_id, course_id))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--instructor-id", type=int, required=True)
    args = parser.parse_args()
    assign_session(args.session_id, args.course_id, args.instructor_id)


if __name__ == "__main__":
    main()
