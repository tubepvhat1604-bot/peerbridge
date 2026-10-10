import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from ..onboarding.contracts import LearnerProfile
from ..onboarding.repository import OnboardingRepository
from .contracts import MatchResult, Pair, RerankingMetadata


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class PairRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.profiles = OnboardingRepository(connection)

    @contextmanager
    def atomic(self) -> Iterator[None]:
        # Serialize SQLite writers before state checks. Savepoint rollback also works when a caller catches an error.
        if not self.connection.in_transaction:
            self.connection.execute("BEGIN IMMEDIATE")
        self.connection.execute("SAVEPOINT data1_pair_write")
        try:
            yield
        except Exception:
            self.connection.execute("ROLLBACK TO data1_pair_write")
            self.connection.execute("RELEASE data1_pair_write")
            raise
        else:
            self.connection.execute("RELEASE data1_pair_write")

    def student_exists(self, user_id: int) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM users WHERE id=? AND role='STUDENT' AND is_seed=0", (user_id,)).fetchone() is not None

    def blocked(self, a: int, b: int) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
            (a, b, b, a)).fetchone() is not None

    def candidates(self, user_id: int) -> list[LearnerProfile]:
        rows = self.connection.execute(
            """SELECT u.id FROM users u JOIN onboarding_profiles p ON p.user_id=u.id
               LEFT JOIN pair_memberships m ON m.user_id=u.id
               WHERE u.role='STUDENT' AND u.is_seed=0 AND p.status='confirmed' AND m.user_id IS NULL
               AND NOT EXISTS(SELECT 1 FROM blocks b WHERE
                 (b.blocker_id=? AND b.blocked_id=u.id) OR (b.blocker_id=u.id AND b.blocked_id=?))
               ORDER BY u.id""", (user_id, user_id)).fetchall()
        profiles = [self.profiles.get_profile(row["id"]) for row in rows]
        return [profile for profile in profiles if profile is not None]

    def pair(self, pair_id: int) -> Pair | None:
        row = self.connection.execute("SELECT * FROM pairs WHERE id=?", (pair_id,)).fetchone()
        if row is None:
            return None
        return Pair(id=row["id"], peer_match_id=row["id"], user_a=row["user_a"], user_b=row["user_b"],
                    match_level=row["match_level"], match_reason=row["match_reason"],
                    match_result=MatchResult.model_validate(json.loads(row["match_result"])),
                    reranking=RerankingMetadata.model_validate(json.loads(row["reranking"])),
                    source=row["source"], started_at=row["started_at"], status=row["status"], ended_at=row["ended_at"])

    def active_pair(self, user_id: int) -> Pair | None:
        row = self.connection.execute("SELECT pair_id FROM pair_memberships WHERE user_id=?", (user_id,)).fetchone()
        return self.pair(row["pair_id"]) if row else None

    def enqueue(self, user_id: int, now: datetime) -> datetime:
        self.connection.execute(
            """INSERT INTO pair_match_queue(user_id,waiting_since,status) VALUES(?,?,'waiting')
               ON CONFLICT(user_id) DO UPDATE SET
                 waiting_since=CASE WHEN pair_match_queue.status='waiting' THEN pair_match_queue.waiting_since
                                    ELSE excluded.waiting_since END, status='waiting'""", (user_id, now.isoformat()))
        row = self.connection.execute("SELECT waiting_since FROM pair_match_queue WHERE user_id=?", (user_id,)).fetchone()
        return datetime.fromisoformat(row["waiting_since"])

    def waiting(self, user_id: int) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM pair_match_queue WHERE user_id=? AND status='waiting'", (user_id,)).fetchone() is not None

    def create_pair(self, a: int, b: int, result: MatchResult, source: str, now: datetime,
                    reranking: RerankingMetadata) -> Pair:
        left, right = sorted((a, b))
        peer = self.connection.execute(
            "SELECT id FROM peer_matches WHERE user_a_id=? AND user_b_id=?", (left, right)).fetchone()
        if peer:
            pair_id = peer["id"]
        else:
            request = self.connection.execute(
                """SELECT id FROM connection_requests WHERE status='PENDING'
                   AND ((requester_id=? AND recipient_id=?) OR (requester_id=? AND recipient_id=?)) ORDER BY id LIMIT 1""",
                (a, b, b, a)).fetchone()
            if request:
                request_id = request["id"]
                self.connection.execute("UPDATE connection_requests SET status='MATCHED',responded_at=? WHERE id=?",
                                        (now.isoformat(), request_id))
            else:
                request_id = self.connection.execute(
                    """INSERT INTO connection_requests(requester_id,recipient_id,status,created_at,responded_at)
                       VALUES(?,?,'MATCHED',?,?)""", (a, b, now.isoformat(), now.isoformat())).lastrowid
            pair_id = self.connection.execute(
                "INSERT INTO peer_matches(connection_request_id,user_a_id,user_b_id,created_at) VALUES(?,?,?,?)",
                (request_id, left, right, now.isoformat())).lastrowid
        self.connection.execute(
            """INSERT INTO pairs(id,user_a,user_b,match_level,match_reason,match_result,reranking,source,started_at,status)
               VALUES(?,?,?,?,?,?,?,?,?,'active') ON CONFLICT(id) DO UPDATE SET
                 match_level=excluded.match_level,match_reason=excluded.match_reason,match_result=excluded.match_result,
                 reranking=excluded.reranking,source=excluded.source,started_at=excluded.started_at,status='active',
                 ended_at=NULL,streak=0""",
            (pair_id, left, right, result.match_level, result.explanation, result.model_dump_json(),
             reranking.model_dump_json(), source, now.isoformat()))
        self.connection.executemany("INSERT INTO pair_memberships(user_id,pair_id) VALUES(?,?)", [(a, pair_id), (b, pair_id)])
        self.connection.execute("UPDATE pair_match_queue SET status='paired' WHERE user_id IN (?,?)", (a, b))
        self.connection.execute(
            """UPDATE connection_requests SET status='EXPIRED',responded_at=? WHERE status='PENDING'
               AND ((requester_id=? AND recipient_id=?) OR (requester_id=? AND recipient_id=?))""",
            (now.isoformat(), a, b, b, a))
        pair = self.pair(int(pair_id))
        assert pair is not None
        return pair

    def create_invitation(self, owner: int, target: int | None, code: str, now: datetime, expires: datetime) -> int:
        cursor = self.connection.execute(
            """INSERT INTO pair_invitations(code_hash,owner_user_id,target_user_id,status,created_at,expires_at)
               VALUES(?,?,?,'pending',?,?)""", (code_hash(code), owner, target, now.isoformat(), expires.isoformat()))
        return int(cursor.lastrowid)

    def invitation(self, code: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM pair_invitations WHERE code_hash=?", (code_hash(code),)).fetchone()

    def use_invitation(self, invitation_id: int, user_id: int, pair_id: int) -> None:
        changed = self.connection.execute(
            "UPDATE pair_invitations SET status='used',used_by=?,pair_id=? WHERE id=? AND status='pending'",
            (user_id, pair_id, invitation_id))
        if changed.rowcount != 1:
            raise ValueError("Invitation state changed")

    def end_pair(self, pair_id: int, now: datetime) -> None:
        self.connection.execute("UPDATE pairs SET status='ended',ended_at=? WHERE id=? AND status='active'",
                                (now.isoformat(), pair_id))
        self.connection.execute("DELETE FROM pair_memberships WHERE pair_id=?", (pair_id,))
