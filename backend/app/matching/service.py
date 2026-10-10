import secrets
import sqlite3
from collections.abc import Callable, Generator
from datetime import UTC, date, datetime, timedelta

from ..db import database
from ..onboarding.contracts import LearnerProfile
from .availability import PRODUCT_ZONE
from .config import DEFAULT_CONFIG, MatchingConfig
from .contracts import Invitation, InviteRequest, MatchResponse, Pair, RerankingMetadata
from .engine import rank_candidates, result_for
from .filters import rejection_reasons
from .repository import PairRepository
from .reranking import Reranker, rerank
from .validation import explanation_is_grounded


class PairError(Exception):
    def __init__(self, detail: str, status_code: int = 409) -> None:
        super().__init__(detail)
        self.status_code = status_code


def current_time() -> datetime:
    return datetime.now(UTC)


def reference_week(now: datetime) -> date:
    day = now.astimezone(PRODUCT_ZONE).date()
    return day - timedelta(days=day.weekday())


class PairService:
    def __init__(self, repository: PairRepository, *, config: MatchingConfig = DEFAULT_CONFIG,
                 reranker: Reranker | None = None, clock: Callable[[], datetime] = current_time) -> None:
        self.repository, self.config, self.reranker, self.clock = repository, config, reranker, clock

    def confirmed(self, user_id: int) -> LearnerProfile:
        if not self.repository.student_exists(user_id):
            raise PairError("Student account required", 403)
        profile = self.repository.profiles.get_profile(user_id)
        if profile is None or profile.status != "confirmed" or profile.confirmed_at is None:
            raise PairError("Confirm the learner concept profile first")
        return profile

    def require_free(self, user_id: int) -> None:
        if self.repository.active_pair(user_id):
            raise PairError("An active Data 1 pair already exists")

    def require_unblocked(self, a: int, b: int) -> None:
        if self.repository.blocked(a, b):
            raise PairError("Pair unavailable", 403)

    async def match(self, user_id: int) -> MatchResponse:
        profile = self.confirmed(user_id)
        existing = self.repository.active_pair(user_id)
        if existing:
            return MatchResponse(status="paired", pair=existing)
        now = self.clock()
        week = reference_week(now)
        candidates, _ = rank_candidates(profile, self.repository.candidates(user_id), self.config, week)
        ranked, metadata = await rerank(candidates, self.reranker, self.config)
        # No provider calls inside the transaction. Recheck confirmation/revisions after the await.
        try:
            with self.repository.atomic():
                existing = self.repository.active_pair(user_id)
                if existing:
                    return MatchResponse(status="paired", pair=existing)
                current_profile = self.confirmed(user_id)
                if current_profile.revision != profile.revision:
                    raise PairError("Profile changed; repeat matching")
                # All returned candidates, including unqueued peers, must still be confirmed and factually current.
                for candidate in ranked:
                    partner_id = candidate.candidate_user_id
                    if (not self.repository.student_exists(partner_id) or self.repository.active_pair(partner_id)
                            or self.repository.blocked(user_id, partner_id)):
                        raise PairError("Candidate state changed; repeat matching")
                    partner = self.repository.profiles.get_profile(partner_id)
                    if (partner is None or partner.status != "confirmed" or partner.confirmed_at is None
                            or partner.revision != candidate.facts.candidate_revision
                            or rejection_reasons(current_profile, partner, self.config, week)
                            or not explanation_is_grounded(candidate, current_profile, partner, self.config)):
                        raise PairError("Candidate profile changed; repeat matching")
                since = self.repository.enqueue(user_id, now)
                for candidate in ranked:
                    if candidate.total_score < self.config.minimum_match_score:
                        continue
                    partner_id = candidate.candidate_user_id
                    if not self.repository.waiting(partner_id) or self.repository.active_pair(partner_id):
                        continue
                    pair = self.repository.create_pair(user_id, partner_id, candidate, "automatic", now, metadata)
                    return MatchResponse(status="paired", candidates=ranked, reranking=metadata, pair=pair)
        except sqlite3.IntegrityError as error:
            raise PairError("Pair state changed; reload") from error
        fallback_at = since + self.config.wait_duration
        suggest = now >= fallback_at and not any(c.total_score >= self.config.minimum_match_score for c in ranked)
        return MatchResponse(status="invite_suggested" if suggest else "waiting", candidates=ranked,
                             reranking=metadata, waiting_since=since, fallback_available_at=fallback_at,
                             fallback_actions=["invite_friend", "manual_concierge"] if suggest else [])

    def invite(self, user_id: int, payload: InviteRequest) -> Invitation:
        now = self.clock()
        with self.repository.atomic():
            self.confirmed(user_id)
            self.require_free(user_id)
            if payload.target_user_id == user_id:
                raise PairError("Cannot invite yourself", 422)
            if payload.target_user_id is not None:
                if not self.repository.student_exists(payload.target_user_id):
                    raise PairError("Target student not found", 404)
                self.require_unblocked(user_id, payload.target_user_id)
            code = secrets.token_urlsafe(32)
            expires = now + self.config.invitation_lifetime
            invitation_id = self.repository.create_invitation(user_id, payload.target_user_id, code, now, expires)
        return Invitation(invitation_id=invitation_id, owner_user_id=user_id, target_user_id=payload.target_user_id,
                          code=code, join_path=f"/api/v1/pairs/join/{code}", expires_at=expires)

    def join(self, user_id: int, code: str) -> Pair:
        now = self.clock()
        try:
            with self.repository.atomic():
                invite = self.repository.invitation(code)
                if invite is None:
                    raise PairError("Invitation not found", 404)
                owner = invite["owner_user_id"]
                if owner == user_id:
                    raise PairError("Cannot join your own invitation", 403)
                if invite["target_user_id"] is not None and invite["target_user_id"] != user_id:
                    raise PairError("Invitation is addressed to another student", 403)
                self.confirmed(user_id)
                self.require_unblocked(owner, user_id)
                if invite["status"] == "used":
                    pair = self.repository.pair(invite["pair_id"])
                    if invite["used_by"] == user_id and pair and pair.status == "active":
                        return pair  # HTTP retries are idempotent, even after the code's original expiry.
                    raise PairError("Invitation already used")
                if invite["status"] != "pending":
                    raise PairError("Invitation is no longer pending")
                if datetime.fromisoformat(invite["expires_at"]) <= now:
                    raise PairError("Invitation expired", 410)
                a, b = self.confirmed(owner), self.confirmed(user_id)
                self.require_free(owner)
                self.require_free(user_id)
                # Friend links are a distinct product path; they do not pretend to pass automatic-match filters.
                result = result_for(a, b, self.config, reference_week(now))
                pair = self.repository.create_pair(owner, user_id, result, "invitation", now, RerankingMetadata())
                self.repository.use_invitation(invite["id"], user_id, pair.id)
                return pair
        except (sqlite3.IntegrityError, ValueError) as error:
            raise PairError("Invitation or pair state changed; reload") from error

    def get_pair(self, user_id: int, pair_id: int) -> Pair:
        pair = self.repository.pair(pair_id)
        if pair is None:
            raise PairError("Data 1 pair not found", 404)
        if user_id not in (pair.user_a, pair.user_b):
            raise PairError("Pair membership required", 403)
        return pair

    def leave(self, user_id: int, pair_id: int) -> Pair:
        with self.repository.atomic():
            self.get_pair(user_id, pair_id)
            self.repository.end_pair(pair_id, self.clock())
            return self.get_pair(user_id, pair_id)

    def cancel_matching(self, user_id: int) -> None:
        with self.repository.atomic():
            self.repository.connection.execute("UPDATE pair_match_queue SET status='cancelled' WHERE user_id=?", (user_id,))

    def revoke_invitation(self, user_id: int, invitation_id: int) -> None:
        with self.repository.atomic():
            row = self.repository.connection.execute("SELECT * FROM pair_invitations WHERE id=?", (invitation_id,)).fetchone()
            if row is None:
                raise PairError("Invitation not found", 404)
            if row["owner_user_id"] != user_id:
                raise PairError("Invitation ownership required", 403)
            if row["status"] == "used":
                raise PairError("Invitation already used")
            self.repository.connection.execute("UPDATE pair_invitations SET status='revoked' WHERE id=?", (invitation_id,))


def get_reranker() -> Reranker | None:
    """Override this dependency at the composition root to enable a configured provider."""
    return None


def get_pair_service() -> Generator[PairService, None, None]:
    with database() as connection:
        yield PairService(PairRepository(connection))
