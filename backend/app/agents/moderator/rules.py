"""Rule tiếng Việt + tiếng Anh chạy trước LLM. Deterministic, không gọi mạng.

Rule chia 2 tầng (xem classify_intent để biết cách gộp với LLM):
  HARD  LLM không được hạ mức: exam_leak, do_task_for_me (thuê/nhờ làm bài thi), exam_cheating_en, personal_info
        (email/SĐT), prompt_injection, insult_direct (xúc phạm nhắm trực tiếp vào người).
  SOFT  chỉ là gợi ý, LLM tự tin được phép ghi đè: từ khoá đơn lẻ (cheating_keyword "chép/cheat", insult_keyword,
        "làm hộ" trong solution_request), answer_sharing, solution_request, long_code_block.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from ...services.content_safety import EMAIL_PATTERN, PHONE_PATTERN
from .intents import MessageIntent, most_severe

# Rủi ro nền của từng nhóm rule (0..1).
RISK_HARMFUL_INSULT = 0.7
RISK_PERSONAL_INFO = 0.5
RISK_DISHONESTY = 0.85
RISK_ANSWER_SHARING = 0.5
RISK_LONG_CODE = 0.55
RISK_SOLUTION_REQUEST = 0.4
RISK_INJECTION = 0.5
LONG_CODE_LINES = 8

HARD = "hard"
SOFT = "soft"
Tier = Literal["hard", "soft"]

_CODE_BLOCK = re.compile(r"```(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class RuleSignals:
    """Kết quả rule: intent nghiêm trọng nhất, rủi ro tối đa, tên rule khớp (gồm cả hai tầng) và tên theo tầng."""

    intent: MessageIntent | None = None
    risk: float = 0.0
    matched: tuple[str, ...] = ()
    hard: tuple[str, ...] = ()
    soft: tuple[str, ...] = ()


def _rule(
    tier: Tier, name: str, intent: MessageIntent, risk: float, pattern: str
) -> tuple[Tier, str, MessageIntent, float, re.Pattern[str]]:
    return tier, name, intent, risk, re.compile(pattern)


# Pattern viết trên văn bản đã bỏ dấu, chữ thường (xem normalize_text).
_INSULT_DIRECT = r"do ngu|thang ngu|con ngu|may ngu|dm|dmm|dit me|cut di|chet di|kill yourself"
_INSULT_KEYWORD = r"ngu nhu|quay roi|fuck|idiot|stupid"
INSULT_PATTERN = rf"\b({_INSULT_DIRECT}|{_INSULT_KEYWORD})\b"  # output_guard dùng cả hai nhóm

_TEXT_RULES = [
    _rule(HARD, "exam_photo_coordination", MessageIntent.ACADEMIC_DISHONESTY, RISK_DISHONESTY,
        r"\b(kiem tra|thi)\b.{0,100}\b(chup|photo)\b.{0,20}\bde\b.{0,30}\b(gui|chia se)\b"),
    _rule(HARD, "direct_threat", MessageIntent.HARMFUL, RISK_HARMFUL_INSULT,
        r"\b(may|mi|ban)\b.{0,30}\b(lieu hon|coi chung tao|tao se danh|tao se giet)\b"),
    _rule(HARD, "live_exam_collaboration", MessageIntent.ACADEMIC_DISHONESTY, RISK_DISHONESTY,
        r"\b(dang thi|mai thi|luc thi|khi thi|trong (gio|bai|ky) thi)\b.{0,160}\b(gui|nhan|bao|chia se)\b.{0,30}\bdap an\b"),
    _rule(HARD, "insult_direct", MessageIntent.HARMFUL, RISK_HARMFUL_INSULT, rf"\b({_INSULT_DIRECT})\b"),
    _rule(SOFT, "insult_keyword", MessageIntent.HARMFUL, RISK_HARMFUL_INSULT, rf"\b({_INSULT_KEYWORD})\b"),
    _rule(
        HARD,
        "do_task_for_me",
        MessageIntent.ACADEMIC_DISHONESTY,
        RISK_DISHONESTY,
        r"\b(lam bai ho|thi ho|hoc ho|lam ho bai (kiem tra|thi)|lam ho de thi)\b",
    ),
    _rule(
        HARD,
        "exam_leak",
        MessageIntent.ACADEMIC_DISHONESTY,
        RISK_DISHONESTY,
        r"\b(chia se|gui|leak|lo)\b.{0,20}\bde (thi|kiem tra)\b|\bde (thi|kiem tra)\b.{0,20}\b(chia se|gui|leak|lo)\b",
    ),
    _rule(
        HARD,
        "exam_cheating_en",
        MessageIntent.ACADEMIC_DISHONESTY,
        RISK_DISHONESTY,
        r"\b(exam leak|do my exam|take my exam|share the exam)\b",
    ),
    _rule(
        SOFT,
        "cheating_keyword",
        MessageIntent.ACADEMIC_DISHONESTY,
        RISK_DISHONESTY,
        r"\b(cheat|cheating|gian lan|copy bai|chep bai)\b",
    ),
    _rule(
        SOFT,
        "answer_sharing",
        MessageIntent.ANSWER_SHARING,
        RISK_ANSWER_SHARING,
        r"\bdap an (?:bai \w+ )?(?:la|:)\s*(?!gi\b|bao nhieu\b)\S|\bthe answer is\b|\bloi giai\s*:|\bsolution\s*:"
        r"|\b(gui|dang|chia se)\b.{0,20}\bloi giai\b.{0,40}\b(chep|ghi y chang|copy)\b"
        r"|\bcode\b.{0,100}\bcopy nop\b",
    ),
    _rule(
        SOFT,
        "solution_request",
        MessageIntent.SOLUTION_REQUEST,
        RISK_SOLUTION_REQUEST,
        r"\b(giai ho|giai giup|lam ho|lam giup bai|cho xin dap an|xin dap an|cho minh dap an|xin loi giai"
        r"|dap (so|an) cuoi|ket qua cuoi(?! ky)|check (giup |ho |dum )?(ket qua|dap an|dap so)"
        r"|chi can (con so|dap so|dap an|ket qua)"
        r"|cho (minh|toi|em)\b.{0,15}\bloi giai\b"
        r"|viet (giup|ho)\b.{0,20}\b(code|ham)\b|code (giup|ho)\b.{0,20}\bbai\b"
        r"|gui\b.{0,15}\bcode hoan chinh\b|ghi (giup|ho)\b.{0,20}\bdap an\b|xin code bai\b"
        r"|dap so\b.{0,20}\b(co phai|la bao nhieu|bang bao nhieu|dung (khong|ko|chua))"
        r"|give me the answer|solve (this|it) for me|do my homework|send (me )?the (answer|solution))\b",
    ),
    _rule(
        HARD,
        "prompt_injection",
        MessageIntent.OFF_TOPIC,
        RISK_INJECTION,
        r"\b(bo qua (moi )?(huong dan|chi dan|chi thi)|ignore (all |the )?(previous |above )?(instructions|rules)"
        r"|cho risk 0|risk (=|la|bang) ?0|system prompt|chatbot khong kiem duyet)\b",
    ),
]


def normalize_text(text: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt để một pattern khớp cả câu có dấu lẫn không dấu."""
    decomposed = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _has_long_code_block(message: str) -> bool:
    return any(
        sum(1 for line in block.splitlines() if line.strip()) >= LONG_CODE_LINES
        for block in _CODE_BLOCK.findall(message)
    )


def analyze_message(message: str) -> RuleSignals:
    """Chạy toàn bộ rule trên tin nhắn; intent là nhóm nghiêm trọng nhất khớp, kèm tên rule theo tầng."""
    normalized = normalize_text(message)
    hits: list[tuple[Tier, str, MessageIntent, float]] = [
        (tier, name, intent, risk) for tier, name, intent, risk, pattern in _TEXT_RULES if pattern.search(normalized)
    ]
    if EMAIL_PATTERN.search(message) or PHONE_PATTERN.search(message):
        hits.append((HARD, "personal_info", MessageIntent.HARMFUL, RISK_PERSONAL_INFO))
    if _has_long_code_block(message):
        hits.append((SOFT, "long_code_block", MessageIntent.ANSWER_SHARING, RISK_LONG_CODE))
    return RuleSignals(
        intent=most_severe([intent for _, _, intent, _ in hits]),
        risk=max((risk for _, _, _, risk in hits), default=0.0),
        matched=tuple(name for _, name, _, _ in hits),
        hard=tuple(name for tier, name, _, _ in hits if tier == HARD),
        soft=tuple(name for tier, name, _, _ in hits if tier == SOFT),
    )
