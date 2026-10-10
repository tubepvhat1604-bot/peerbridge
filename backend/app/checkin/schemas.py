"""Pydantic schema: kết quả AI và dữ liệu API."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, field_validator

ALLOWED_EMOJIS = ["🔥", "👏", "💪", "😮", "❤️"]


# ---------- Kết quả từ LLM ----------
class VisionResult(BaseModel):
    is_study: bool
    concepts: list[str] = Field(default_factory=list)
    description: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    summary_for_partner: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("description", "summary_for_partner", mode="before")
    @classmethod
    def _strip(cls, v):
        return (v or "").strip()


class LLMUsage(BaseModel):
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


# ---------- Ngữ cảnh đưa cho AI ----------
class ConceptRef(BaseModel):
    id: str
    name: str
    description: str | None = None


class PlanItemRef(BaseModel):
    id: str
    concept_id: str
    label: str
    due_date: dt.date


# ---------- API ----------
class OptionOut(BaseModel):
    plan_item_id: str
    label: str
    concept_name: str | None = None


class ReactionOut(BaseModel):
    user_id: int
    display_name: str
    emoji: str | None = None
    comment: str | None = None
    relative: str


class CheckinOut(BaseModel):
    id: str
    status: str
    kind: str
    owner_id: int
    owner_name: str
    image_url: str | None = None
    note: str | None = None
    created_at: dt.datetime
    relative: str
    headline: str
    description: str | None = None
    concept_names: list[str] = Field(default_factory=list)
    partner_summary: str | None = None
    bridge: str | None = None
    plan_item_label: str | None = None
    options: list[OptionOut] = Field(default_factory=list)
    reactions: list[ReactionOut] = Field(default_factory=list)


class ConfirmIn(BaseModel):
    # None = "Mình học thứ khác" (vẫn tính check-in, không gắn mục plan).
    plan_item_id: str | None = None


class TextCheckinIn(BaseModel):
    plan_item_id: str | None = Field(default=None, max_length=160)
    id: str
    note: str = Field(min_length=3)


class ReactionIn(BaseModel):
    emoji: str | None = None
    comment: str | None = None

    @field_validator("emoji")
    @classmethod
    def _emoji(cls, v):
        if v is not None and v not in ALLOWED_EMOJIS:
            raise ValueError("Biểu tượng không hợp lệ")
        return v


class PersonProgress(BaseModel):
    user_id: int
    display_name: str
    pacing: float | None = None
    done_items: int = 0
    total_items: int = 0
    checked_in_today: bool = False


class FeedOut(BaseModel):
    provider_mode: str = "fake"
    pair_id: int
    me: PersonProgress
    partner: PersonProgress
    streak: int
    partner_latest: CheckinOut | None = None
    my_latest: CheckinOut | None = None
    my_pending: list[CheckinOut] = Field(default_factory=list)
    history: list[CheckinOut] = Field(default_factory=list)
    can_nudge: bool = True
    nudge_hint: str | None = None
