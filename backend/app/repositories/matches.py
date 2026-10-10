import json
import sqlite3
from typing import Any

MatchCandidateResult = dict[str, Any]
MatchRequestRecord = dict[str, Any]


def _component_scores(value: str) -> dict[str, float]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): float(score) for key, score in parsed.items()}


class MatchRequestRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_match_request(
        self,
        requester_id: int,
        candidates: list[MatchCandidateResult],
        created_at: str,
    ) -> MatchRequestRecord:
        cursor = self.connection.execute(
            "INSERT INTO match_requests(requester_id, created_at) VALUES (?, ?)",
            (requester_id, created_at),
        )
        request_id = int(cursor.lastrowid)
        self.connection.executemany(
            """INSERT INTO match_candidates(
                request_id, candidate_id, total_score, component_scores, rank, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    request_id,
                    int(candidate["candidate_id"]),
                    float(candidate["total_score"]),
                    json.dumps(candidate["component_scores"], ensure_ascii=False, sort_keys=True),
                    int(candidate["rank"]),
                    created_at,
                )
                for candidate in candidates
            ],
        )
        record = self.get_match_request(requester_id=requester_id, request_id=request_id)
        if record is None:
            raise RuntimeError("Created match request could not be loaded")
        return record

    def get_match_request(self, requester_id: int, request_id: int) -> MatchRequestRecord | None:
        request = self.connection.execute(
            "SELECT id FROM match_requests WHERE id = ? AND requester_id = ?",
            (request_id, requester_id),
        ).fetchone()
        if request is None:
            return None

        candidates = self.connection.execute(
            """SELECT mc.request_id, mc.candidate_id, p.display_name, p.school, p.major,
                      mc.total_score, mc.component_scores, mc.rank
               FROM match_candidates mc
               JOIN profiles p ON p.user_id = mc.candidate_id
               WHERE mc.request_id = ?
               ORDER BY mc.rank, mc.id""",
            (request_id,),
        ).fetchall()
        return {
            "request_id": int(request["id"]),
            "candidates": [
                {
                    "request_id": int(candidate["request_id"]),
                    "candidate_id": int(candidate["candidate_id"]),
                    "display_name": candidate["display_name"],
                    "school": candidate["school"],
                    "major": candidate["major"],
                    "total_score": float(candidate["total_score"]),
                    "component_scores": _component_scores(candidate["component_scores"]),
                    "rank": int(candidate["rank"]),
                }
                for candidate in candidates
            ],
        }
