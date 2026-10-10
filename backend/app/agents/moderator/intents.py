"""Intent nội bộ của moderator (không dùng chung, nên không nằm trong app/enums.py)."""

from enum import StrEnum


class MessageIntent(StrEnum):
    CONCEPT_QUESTION = "CONCEPT_QUESTION"  # hỏi khái niệm
    SOLUTION_REQUEST = "SOLUTION_REQUEST"  # xin đáp án / giải hộ
    ANSWER_SHARING = "ANSWER_SHARING"  # đưa đáp án / lời giải / code hoàn chỉnh
    ACADEMIC_DISHONESTY = "ACADEMIC_DISHONESTY"  # chia sẻ đề thi, làm bài hộ, gian lận
    HARMFUL = "HARMFUL"  # xúc phạm, quấy rối, lộ thông tin cá nhân
    OFF_TOPIC = "OFF_TOPIC"
    SOCIAL = "SOCIAL"


# Càng cao càng nghiêm trọng; dùng để chọn intent khi rule và LLM khác nhau.
INTENT_SEVERITY: dict[MessageIntent, int] = {
    MessageIntent.SOCIAL: 0,
    MessageIntent.CONCEPT_QUESTION: 1,
    MessageIntent.OFF_TOPIC: 2,
    MessageIntent.SOLUTION_REQUEST: 3,
    MessageIntent.ANSWER_SHARING: 4,
    MessageIntent.ACADEMIC_DISHONESTY: 5,
    MessageIntent.HARMFUL: 6,
}


def most_severe(intents: list[MessageIntent]) -> MessageIntent | None:
    """Trả intent nghiêm trọng nhất, hoặc None nếu danh sách rỗng."""
    return max(intents, key=INTENT_SEVERITY.__getitem__, default=None)
