"""Persisted tutoring state and deterministic exit rules for a Study Room learner."""

import re

from pydantic import BaseModel, Field

from .rules import normalize_text


class SocraticSession(BaseModel):
    active: bool = True
    session_id: str
    sender_id: str
    original_question: str
    topic: str = ""
    turn_count: int = Field(ge=1)
    last_guidance: str | None = None


_STOP = re.compile(r"\b(dung (tro giang|huong dan|goi y)|khong can (tro giang|goi y)|stop tutoring|stop helping)\b")
_DONE = re.compile(r"\b(da hieu roi|hieu roi|tu giai duoc roi|lam duoc roi|i got it|i solved it)\b")


def exit_requested(message: str) -> bool:
    normalized = normalize_text(message)
    return bool(_STOP.search(normalized) or _DONE.search(normalized))
