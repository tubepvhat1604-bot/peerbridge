"""Cặp tạo bằng nút "Kết nối" được bổ sung thành cặp học của Data 1 (`pairs` + `pair_memberships`) khi cần đo tiến độ.

Chỉ tạo khi cả hai chưa có cặp Data 1 nào đang active, và chỉ lúc có hoạt động học (check-in, mở Tổng quan),
nên luồng ghép cặp/lời mời của Data 1 vẫn dùng được cho kết nối vừa chấp nhận.

Data 1 đo tiến độ chỉ cho cặp `active` có đủ hai membership. Cặp tạo từ lời mời trực tiếp là `source='invitation'`;
điểm ghép (MatchResult) để trống vì hai bạn tự chọn nhau, không qua thuật toán gợi ý.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, date, datetime

from ..matching.contracts import Components, ExplanationFacts, MatchResult, RerankingMetadata

log = logging.getLogger("loop.pairing")
REASON = "Hai bạn tự kết nối với nhau."


def _direct_result(a: int, b: int, today: date) -> MatchResult:
    facts = ExplanationFacts(
        requester_user_id=a, candidate_user_id=b, requester_revision=1, candidate_revision=1,
        concepts_a_receives_from_b=[], concepts_b_receives_from_a=[], shared_learning_concepts=[], common_slots=[],
        reference_week=today, weekly_hours_a=1, weekly_hours_b=1, weekly_hours_ratio=1, same_stated_goal=False,
    )
    zero = Components(coverage_a_by_b=0, coverage_b_by_a=0, reciprocal_complementarity=0, concept_overlap=0,
                      availability_overlap=0, commitment_similarity=0)
    return MatchResult(candidate_user_id=b, total_score=0, reciprocal_score=0, component_scores=zero,
                       match_level="shared_commitment", facts=facts, explanation=REASON)


def ensure_pair(connection: sqlite3.Connection, peer_match_id: int, user_a: int, user_b: int,
                now: datetime | None = None) -> bool:
    """Tạo cặp Data 1 cho peer match nếu cả hai chưa có cặp active. Trả True nếu vừa tạo."""
    now = now or datetime.now(UTC)
    a, b = sorted((user_a, user_b))
    busy = connection.execute(
        "SELECT COUNT(*) FROM pair_memberships m JOIN pairs p ON p.id=m.pair_id WHERE m.user_id IN (?,?) AND p.status='active'",
        (a, b),
    ).fetchone()[0]
    if busy:
        return False
    try:
        result = _direct_result(a, b, now.date())
        connection.execute(
            """INSERT INTO pairs(id,user_a,user_b,match_level,match_reason,match_result,reranking,source,started_at,status)
               VALUES(?,?,?,?,?,?,?,'invitation',?,'active') ON CONFLICT(id) DO UPDATE SET status='active', ended_at=NULL,
               started_at=excluded.started_at, streak=0""",
            (peer_match_id, a, b, result.match_level, REASON, result.model_dump_json(),
             RerankingMetadata().model_dump_json(), now.isoformat()),
        )
        connection.execute("DELETE FROM pair_memberships WHERE user_id IN (?,?)", (a, b))
        connection.executemany("INSERT INTO pair_memberships(user_id,pair_id) VALUES(?,?)",
                               [(a, peer_match_id), (b, peer_match_id)])
        return True
    except sqlite3.Error:
        log.exception("Không tạo được cặp Data 1 cho peer match %s", peer_match_id)
        return False


def ensure_for_user(user_id: int) -> int | None:
    """Cặp Data 1 đang active của người dùng; chưa có thì tạo từ kết nối gần nhất. Trả id cặp hoặc None."""
    from ..db import database

    with database() as db:
        row = db.execute(
            "SELECT p.id FROM pair_memberships m JOIN pairs p ON p.id=m.pair_id WHERE m.user_id=? AND p.status='active'",
            (user_id,),
        ).fetchone()
        if row:
            return row["id"]
        pm = db.execute(
            "SELECT id, user_a_id, user_b_id FROM peer_matches WHERE user_a_id=? OR user_b_id=? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (user_id, user_id),
        ).fetchone()
        if pm is None:
            return None
        return pm["id"] if ensure_pair(db, pm["id"], pm["user_a_id"], pm["user_b_id"]) else None
