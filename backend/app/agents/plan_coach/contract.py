from datetime import datetime, time
from enum import StrEnum
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ItemStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    DEFERRED = "DEFERRED"
    COMPLETED = "COMPLETED"


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must include a timezone offset")
    return value


def timezone_name(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unknown IANA timezone") from None
    return value


class Availability(Contract):
    id: str = Field(min_length=1, max_length=80)
    day_of_week: int = Field(ge=0, le=6)  # Monday = 0
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def ordered(self):
        if self.start_time.tzinfo or self.end_time.tzinfo or self.end_time <= self.start_time:
            raise ValueError("Use local times with end_time > start_time; split overnight windows")
        return self


class Concept(Contract):
    id: str = Field(min_length=1, max_length=100)
    track: Literal["sql", "python", "english", "ai"]
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    action: str = Field(min_length=5, max_length=600)
    expected_output: str = Field(min_length=3, max_length=500)
    est_minutes: int = Field(ge=30, le=90)
    resource_ids: list[str] = Field(default_factory=list)


class Member(Contract):
    user_id: int = Field(gt=0)
    goal: str = Field(min_length=3, max_length=500)
    deadline: datetime | None = None
    concept_ids: list[str] = Field(min_length=1, max_length=100)
    known_concept_ids: list[str] = Field(default_factory=list, max_length=100)
    can_help_concept_ids: list[str] = Field(default_factory=list, max_length=100)
    committed_minutes_per_week: int = Field(ge=0, le=10080)
    availability: list[Availability] = Field(default_factory=list, max_length=50)
    timezone: str = "Asia/Ho_Chi_Minh"
    location: str = Field(default="Góc học tập của tôi", min_length=1, max_length=160)

    _timezone = field_validator("timezone")(timezone_name)
    _deadline = field_validator("deadline")(lambda v: aware(v) if v else v)

    @model_validator(mode="after")
    def unique_windows(self):
        if len({s.id for s in self.availability}) != len(self.availability):
            raise ValueError("Availability IDs must be unique")
        for i, left in enumerate(self.availability):
            for right in self.availability[i + 1 :]:
                if (
                    left.day_of_week == right.day_of_week
                    and left.start_time < right.end_time
                    and right.start_time < left.end_time
                ):
                    raise ValueError("Availability windows must not overlap")
        return self


class BusyInterval(Contract):
    start: datetime
    end: datetime
    _start = field_validator("start")(aware)
    _end = field_validator("end")(aware)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Busy interval must have end after start")
        return self


class PlannerInput(Contract):
    pair_id: int = Field(gt=0)
    members: list[Member] = Field(min_length=2, max_length=2)
    concepts: list[Concept] = Field(min_length=1, max_length=150)
    resources: dict[str, str] = Field(default_factory=dict)
    planning_start: datetime
    horizon_days: int = Field(default=7, ge=1, le=28)
    plan_version: int = Field(default=1, gt=0)
    catalog_source: str = "demo"
    busy_intervals: dict[int, list[BusyInterval]] = Field(default_factory=dict)

    _start = field_validator("planning_start")(aware)

    @model_validator(mode="after")
    def distinct_members(self):
        if self.members[0].user_id == self.members[1].user_id:
            raise ValueError("Two distinct pair members are required")
        return self


class Task(Contract):
    user_id: int = Field(gt=0)
    concept_id: str = Field(min_length=1)
    action: str = Field(min_length=5, max_length=600)
    expected_output: str = Field(min_length=3, max_length=500)
    est_minutes: int = Field(ge=30, le=90)
    resource_ids: list[str] = Field(default_factory=list)


class TaskBatch(Contract):
    tasks: list[Task] = Field(max_length=300)


class Issue(Contract):
    code: str
    message: str
    user_id: int | None = None
    concept_id: str | None = None
    item_id: str | None = None


class PlanItem(Task):
    id: str = Field(default_factory=lambda: str(uuid4()))
    pair_id: int = Field(gt=0)
    plan_version: int = Field(gt=0)
    status: ItemStatus
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    slot_id: str | None = None
    if_then_text: str | None = None
    defer_reason: str | None = None
    completed_at: datetime | None = None


class PersonalPlan(Contract):
    user_id: int
    pair_id: int
    plan_version: int
    items: list[PlanItem] = Field(default_factory=list)
    deferred_items: list[PlanItem] = Field(default_factory=list)
    partial: bool = False
    warnings: list[Issue] = Field(default_factory=list)


class PlannerOutput(Contract):
    pair_id: int
    plans: list[PersonalPlan]
    warnings: list[Issue] = Field(default_factory=list)
    peer_sessions: list[dict] = Field(default_factory=list)
    peer_session_reason: str = "OPTIONAL_NOT_REQUESTED"


class CompletionEvent(Contract):
    event_id: str = Field(min_length=1, max_length=120)
    plan_item_id: str
    pair_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    plan_version: int = Field(gt=0)
    confirmed_at: datetime
    confirmed: Literal[True]
    _confirmed_at = field_validator("confirmed_at")(aware)

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("AI Vision must explicitly confirm with boolean true")
        return value


class MetricSnapshot(Contract):
    pair_id: int
    as_of: datetime
    source: str
    plan_versions: dict[int, int]
    pacing: dict[int, float | None]
    due_count: dict[int, int]
    last_checkin: dict[int, datetime | None]
    gap: float | None = Field(default=None, ge=0, le=1)
    lagging_user_id: int | None = None
    _as_of = field_validator("as_of")(aware)

    @model_validator(mode="after")
    def bounded(self):
        for p in self.pacing.values():
            if p is not None and not 0 <= p <= 1:
                raise ValueError("Pacing must be between 0 and 1 or null")
        for stamp in self.last_checkin.values():
            if stamp is not None:
                aware(stamp)
        if any(count < 0 for count in self.due_count.values()):
            raise ValueError("due_count must be non-negative")
        return self


class GenerateRequest(Contract):
    pair_id: int = Field(gt=0)
    members: list[Member] = Field(min_length=2, max_length=2)
    horizon_days: int = Field(default=7, ge=1, le=28)


class ReplanRequest(Contract):
    expected_version: int = Field(gt=0)
    reduce_load: bool = True
    reason: str = Field(default="Giảm tải và dùng thời gian còn lại", min_length=3, max_length=300)


class AcceptRequest(Contract):
    expected_version: int = Field(gt=0)
