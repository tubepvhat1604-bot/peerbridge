"""Output guard: hàm thuần kiểm tra guidance do LLM tạo trước khi trả ra ngoài.

Mã vi phạm:
  answer_leak     xác nhận/phủ nhận/nêu đáp án, đáp số, kết quả cuối hoặc công thức kết quả
  code_leak       code fence, inline code dài, dòng có dạng code
  prompt_leak     delimiter nội bộ, nhắc system prompt, "as an AI", nội dung few-shot
  pii             email / số điện thoại
  toxic           từ xúc phạm
  too_long        dài quá MAX_GUIDANCE_CHARS
  wrong_language  câu dài nhưng gần như không có ký tự tiếng Việt
  not_socratic    từ 2 câu trở lên mà dưới một nửa là câu hỏi
  solution_steps  câu khẳng định mô tả lời giải cụ thể (trường hợp cơ sở = số, trả về số, gọi lại với n-1, các bước)
"""

import re

from pydantic import BaseModel, Field

from ...services.content_safety import EMAIL_PATTERN, PHONE_PATTERN
from .intents import MessageIntent
from .prompts import DELIMITER_TAGS, FEW_SHOT_MESSAGES
from .rules import INSULT_PATTERN, normalize_text
from .state import ModeratorState

MAX_GUIDANCE_CHARS = 600
MAX_REASON_CHARS = 300
INLINE_CODE_MAX_CHARS = 30
LANGUAGE_MIN_LETTERS = 40
VIETNAMESE_MIN_RATIO = 0.08
MIN_SENTENCES_FOR_SOCRATIC_CHECK = 2
REDACTED = "[đã ẩn]"

# Các pattern dưới đây chạy trên văn bản đã bỏ dấu, chữ thường (normalize_text).
_CONFIRM_PATTERN = re.compile(
    r"\b(dung roi|chinh xac(?: roi| la)|sai roi|chuan roi|ban dung roi|ket qua cua ban (?:dung|sai))\b"
)
_RESULT_PATTERN = re.compile(
    r"\b(?:dap an|dap so|ket qua)(?: cuoi)?(?: cua [^.?!\n]{1,30}?)? (?:la|se la|bang|=|:) *(?:-?\d|[a-d]\b)"
)
_SENTENCE_CONFIRM_WORDS = re.compile(r"\b(dung|sai|chinh xac|chuan|khop|trung|phai)\b")
_LABEL_WORDS = {"cau", "bai", "buoc", "muc", "phan", "dong", "trang", "chuong", "vi", "du", "ex", "q"}
_NUMBER = re.compile(r"(?:(\w+)\s+)?(-?\d+(?:[.,]\d+)?)")

# Mô tả lời giải trong câu khẳng định (văn bản đã bỏ dấu).
_SOLUTION_STEPS = re.compile(
    r"(?:truong hop co so|dieu kien dung)\b.{0,60}?(?:bang|=)\s*-?\d"
    r"|\btra ve (?:la |gia tri )?-?\d"
    r"|\bgoi lai\b.{0,25}?\b\w\s*[-+]\s*\d"
    r"|\bnhan (?:ket qua )?(?:voi|cho) \w"
    r"|\bbuoc ?1\b.*\bbuoc ?2\b"
)
_RECURRENCE_CALL = re.compile(r"\b\w+\(\s*\w\s*[-+]\s*\d\s*\)")  # f(n-1) trong câu khẳng định

# Chạy trên văn bản gốc.
_FORMULA_RESULT = re.compile(r"\d+\s*(?:[*x×+/-]\s*\d+\s*)+=\s*-?\d+")
_CODE_FENCE = "```"
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_CODE_LINE = re.compile(
    r"^\s*(?:def |class |return\b|import \w|from \w+ import |print\(|printf\(|console\.log|#include|public static"
    r"|for\s*\(|while\s*\(|if\s*\(.*\)\s*\{|for \w+ in )"
)
_CODE_ANYWHERE = re.compile(r"\bdef\s+\w+\s*\(|=>|[{}]|^[^;]*[=()][^;]*;\s*$|\bprintf\s*\(")

_PROMPT_LEAK_PHRASES = ("system prompt", "huong dan he thong", "as an ai", "as a language model", "few-shot")
_INSULT = re.compile(INSULT_PATTERN)
_NORMALIZED_FEW_SHOT = tuple(normalize_text(message) for message in FEW_SHOT_MESSAGES)


class GuardResult(BaseModel):
    """Kết quả guard: sanitized = text gốc nếu ok, None nếu có vi phạm (khi đó dùng template)."""

    ok: bool
    violations: list[str] = Field(default_factory=list)
    sanitized: str | None = None


def _student_numbers(message: str) -> set[str]:
    """Số trong tin nhắn sinh viên, bỏ số nhãn như 'câu 4', 'bài 2'."""
    numbers: set[str] = set()
    for match in _NUMBER.finditer(normalize_text(message)):
        prefix, number = match.group(1), match.group(2)
        if prefix not in _LABEL_WORDS:
            numbers.add(number.replace(",", "."))
    return numbers


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _statements(text: str) -> list[str]:
    """Các câu khẳng định (không kết thúc bằng '?')."""
    return [sentence for sentence in _sentences(text) if not sentence.endswith("?")]


def _is_not_socratic(text: str) -> bool:
    """Từ 2 câu trở lên mà dưới một nửa là câu hỏi."""
    sentences = _sentences(text)
    questions = len(sentences) - len(_statements(text))
    return len(sentences) >= MIN_SENTENCES_FOR_SOCRATIC_CHECK and questions * 2 < len(sentences)


def _describes_solution_steps(text: str) -> bool:
    """Câu khẳng định mô tả lời giải cụ thể (trường hợp cơ sở, giá trị trả về, bước đệ quy, các bước...)."""
    statements = _statements(text)
    joined = normalize_text(" ".join(statements))
    return bool(_SOLUTION_STEPS.search(joined)) or any(_RECURRENCE_CALL.search(s) for s in statements)


def _echoes_student_number(text: str, message: str) -> bool:
    """Câu khẳng định (không phải câu hỏi) nhắc lại số của sinh viên kèm từ xác nhận/phủ nhận."""
    numbers = _student_numbers(message)
    if not numbers:
        return False
    for sentence in _statements(text):
        normalized = normalize_text(sentence).replace(",", ".")
        has_number = any(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", normalized) for n in numbers)
        if has_number and _SENTENCE_CONFIRM_WORDS.search(normalized):
            return True
    return False


def _has_answer_leak(text: str, normalized: str, state: ModeratorState) -> bool:
    if _RESULT_PATTERN.search(normalized) or _FORMULA_RESULT.search(text):
        return True
    if state.get("intent") is not MessageIntent.SOLUTION_REQUEST:
        return False
    return bool(_CONFIRM_PATTERN.search(normalized)) or _echoes_student_number(text, state["input"].message)


def _has_code(text: str) -> bool:
    if _CODE_FENCE in text:
        return True
    if any(len(code) > INLINE_CODE_MAX_CHARS for code in _INLINE_CODE.findall(text)):
        return True
    return any(_CODE_LINE.search(line) or _CODE_ANYWHERE.search(line) for line in text.splitlines())


def _has_prompt_leak(text: str, normalized: str) -> bool:
    if DELIMITER_TAGS.search(text) or any(phrase in normalized for phrase in _PROMPT_LEAK_PHRASES):
        return True
    return '"intent"' in text or '"risk"' in text or any(example in normalized for example in _NORMALIZED_FEW_SHOT)


def _is_wrong_language(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if len(letters) < LANGUAGE_MIN_LETTERS:
        return False
    return sum(ord(char) > 127 for char in letters) / len(letters) < VIETNAMESE_MIN_RATIO


def check_output(text: str, state: ModeratorState) -> GuardResult:
    """Kiểm tra guidance; trả vi phạm kèm mã (thứ tự cố định), không gọi LLM."""
    normalized = normalize_text(text)
    checks = (
        ("answer_leak", _has_answer_leak(text, normalized, state)),
        ("code_leak", _has_code(text)),
        ("prompt_leak", _has_prompt_leak(text, normalized)),
        ("pii", bool(EMAIL_PATTERN.search(text) or PHONE_PATTERN.search(text))),
        ("toxic", bool(_INSULT.search(normalized))),
        ("too_long", len(text) > MAX_GUIDANCE_CHARS),
        ("wrong_language", _is_wrong_language(text)),
        ("not_socratic", _is_not_socratic(text)),
        ("solution_steps", _describes_solution_steps(text)),
    )
    violations = [code for code, hit in checks if hit]
    return GuardResult(ok=not violations, violations=violations, sanitized=None if violations else text)


def sanitize_reason(reason: str) -> str:
    """Làm sạch reason trước khi trả ra: bỏ delimiter nội bộ, ẩn PII, cắt còn tối đa MAX_REASON_CHARS."""
    cleaned = DELIMITER_TAGS.sub("", reason)
    cleaned = EMAIL_PATTERN.sub(REDACTED, cleaned)
    cleaned = PHONE_PATTERN.sub(REDACTED, cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > MAX_REASON_CHARS:
        cleaned = cleaned[: MAX_REASON_CHARS - 1].rstrip() + "…"
    return cleaned
