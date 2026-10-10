"""Lọc trước khi gọi LLM: tin chat thường (chào, ok, hẹn giờ) không cần AI phân loại.

Chỉ bỏ qua LLM khi tin ngắn, không có dấu hiệu hỏi bài/đáp án/code và luật không bắt được gì.
Mọi trường hợp còn lại vẫn đi qua LLM như cũ, nên lọc trước chỉ giảm chi phí, không nới kiểm duyệt.
"""

import re

from .rules import RuleSignals, normalize_text

# Tin dài hơn mức này luôn gửi LLM (dễ chứa lời giải hoặc lách luật).
SHORT_MESSAGE_MAX_CHARS = 80

# So khớp trên chữ đã bỏ dấu (normalize_text) nên "bài", "bai" đều khớp.
_STUDY_CUES = re.compile(
    r"\b("
    r"bai|bai tap|de bai|de thi|bai thi|di thi|phong thi|dap an|dap so|loi giai|giai|ket qua|dung khong|sai o dau"
    r"|code|ham|bien|vong lap|cong thuc|query|truy van|sql|python|excel|pandas|join|group by"
    r"|lam sao|lam the nao|tai sao|vi sao|the nao|nhu nao|la gi|nghia la|khac gi"
    r"|giup|chi minh|chi toi|chi voi|huong dan|giai thich|kiem tra|check|xem giup|copy|chep"
    r"|nop|deadline|diem|quiz|test"
    r"|answer|solve|solution|homework|assignment|exam|explain|how|why|what|help"
    r")\b"
)
_CODE_OR_MATH = re.compile(r"[{}\[\];=<>`|\\]|\d\s*[-+*/^%]\s*\d|https?://|www\.|\bdef |\bselect\b|\bimport\b")


def needs_llm(message: str, signals: RuleSignals, socratic_active: bool = False) -> bool:
    """True nếu tin cần LLM phân loại; False nếu là chat thường, an toàn để chỉ dùng luật."""
    if signals.hard or signals.soft or signals.matched or socratic_active:
        return True
    text = message.strip()
    if len(text) > SHORT_MESSAGE_MAX_CHARS or "?" in text or "\n" in text:
        return True
    if _CODE_OR_MATH.search(text.casefold()):
        return True
    return bool(_STUDY_CUES.search(normalize_text(text)))
