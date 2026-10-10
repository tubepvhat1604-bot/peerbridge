from collections.abc import Generator

from ..db import database, utc_now
from ..enums import Role
from ..repositories.matches import MatchRequestRepository
from ..repositories.profiles import ProfileRepository
from ..schemas import MatchSearchResponse
from .match_ai import rerank
from .matching_engine import _topic_set, find_top_matches, goal_similarity

MATCH_SEARCH_TOP_K = 15


class MatchProfileNotFoundError(Exception):
    """Raised when a student has no profile to match from."""


class MatchRequestNotFoundError(Exception):
    """Raised when a persisted match request does not exist for the student."""


class MatchSearchForbiddenError(Exception):
    """Raised when a non-student tries to use student matching."""


class MatchSearchService:
    def __init__(self, profiles: ProfileRepository, match_requests: MatchRequestRepository) -> None:
        self.profiles = profiles
        self.match_requests = match_requests

    def search_matches(self, user: dict) -> MatchSearchResponse:
        requester_id = self._current_student_id(user)
        requester = self.profiles.get_profile_bundle(requester_id)
        if requester is None:
            raise MatchProfileNotFoundError("Profile not found")

        bundles = self.profiles.list_student_profile_bundles()
        ranked_candidates = find_top_matches(
            requester=requester,
            candidates=bundles,
            top_k=50,
        )
        ranked_candidates, mode = rerank(requester, ranked_candidates, bundles)
        record = self.match_requests.create_match_request(
            requester_id=requester_id,
            candidates=ranked_candidates[:MATCH_SEARCH_TOP_K],
            created_at=utc_now(),
        )
        response = self._enrich(record, requester)
        response.matching_mode = mode
        return response

    def get_match_request(self, user: dict, request_id: int) -> MatchSearchResponse:
        requester_id = self._current_student_id(user)
        record = self.match_requests.get_match_request(requester_id=requester_id, request_id=request_id)
        if record is None:
            raise MatchRequestNotFoundError("Match request not found")
        return self._enrich(record, self.profiles.get_profile_bundle(requester_id))

    def _enrich(self, record, requester):
        for candidate in record["candidates"]:
            bundle = self.profiles.get_profile_bundle(candidate["candidate_id"])
            if not bundle:
                continue
            candidate.update(
                learning_goals=bundle["profile"]["learning_goals"],
                bio=bundle["profile"]["bio"],
                needs=[n["topic"] for n in bundle["needs_help_with"]],
                strengths=[n["topic"] for n in bundle["can_help_with"]],
                availability=bundle["availability"],
            )
            my_needs = _topic_set(requester or {}, "needs_help_with")
            shared = [n for n in candidate["strengths"] if _topic_set({"can_help_with": [{"topic": n}]}, "can_help_with") & my_needs]
            reasons = []
            if shared:
                reasons.append("Có thể đồng hành với bạn ở " + ", ".join(shared))
            if candidate["component_scores"].get("availability_overlap", 0) > 0:
                reasons.append("Hai bạn có khung giờ rảnh trùng nhau để cùng giữ nhịp học.")
            common_needs = my_needs & _topic_set(bundle, "needs_help_with")
            if common_needs:
                reasons.append("Hai bạn đang cần học cùng chủ đề; có thể cùng luyện tập và check-in tiến độ.")
            mutual = _topic_set(requester or {}, "can_help_with") & _topic_set(bundle, "needs_help_with")
            if mutual:
                reasons.append("Bạn cũng có thế mạnh phù hợp với nhu cầu của người này; hai bạn có thể hỗ trợ qua lại.")
            if goal_similarity(requester or {}, bundle) > 0.15:
                reasons.append("Mục tiêu học tập có điểm chung; phù hợp để cùng luyện tập và nhắc nhau giữ cam kết.")
            if candidate["learning_goals"]:
                reasons.append("Đang hướng tới: " + candidate["learning_goals"][0])
            candidate["reasons"] = reasons
        return MatchSearchResponse(**record)

    @staticmethod
    def _current_student_id(user: dict) -> int:
        if str(user.get("role")) != Role.STUDENT.value:
            raise MatchSearchForbiddenError("Only students can search matches")
        return int(user["id"])


def get_match_search_service() -> Generator[MatchSearchService, None, None]:
    with database() as connection:
        yield MatchSearchService(
            profiles=ProfileRepository(connection),
            match_requests=MatchRequestRepository(connection),
        )
