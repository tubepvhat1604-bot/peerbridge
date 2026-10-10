"""Nguồn dữ liệu đo tiến độ cho Data 1 (port `MeasurementSource`): plan ACTIVE của Data 2 + check-in của AI Vision."""
from __future__ import annotations

from datetime import UTC, datetime

from ..agents.plan_coach.contract import ItemStatus
from ..checkin.db import session_factory
from ..checkin.models import Checkin
from ..db import database
from ..metrics.adapters import InputUnavailableError
from ..metrics.contracts import FinalizedCheckin, MeasurementInput, PairContext, PlanWorkload
from ..metrics.time import study_date
from ..repositories.plans import PlanRepository


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def plan_workload(
    pair_id: int, members: tuple[int, int], as_of: datetime | None = None
) -> tuple[list[PlanWorkload], dict[int, int]]:
    """Các việc đã xếp lịch trong plan ACTIVE của từng người; trả kèm phiên bản plan.

    Có `as_of` thì bỏ các việc chưa xong mà khung giờ chưa kết thúc, để vừa lập plan xong không bị tính là chậm.
    """
    items: list[PlanWorkload] = []
    versions: dict[int, int] = {}
    with database() as db:
        repo = PlanRepository(db)
        for uid in members:
            row = repo.active(pair_id, uid)
            if row is None:
                continue
            plan = repo.hydrated(row)
            versions[uid] = plan.plan_version
            for i in plan.items:
                if i.status == ItemStatus.DEFERRED or i.scheduled_start is None:
                    continue
                end = _aware(i.scheduled_end or i.scheduled_start)
                if as_of is not None and i.completed_at is None and end > as_of:
                    continue
                items.append(PlanWorkload(
                    id=i.id, user_id=uid, pair_id=pair_id, concept_id=i.concept_id, estimated_minutes=i.est_minutes,
                    due_date=study_date(i.scheduled_start), completed_at=_aware(i.completed_at),
                ))
    return items, versions


def finalized_checkins(pair_id: int, members: tuple[int, int]) -> list[FinalizedCheckin]:
    with session_factory()() as s:
        rows = s.query(Checkin).filter(Checkin.pair_id == pair_id, Checkin.user_id.in_(members)).all()
    out = []
    for r in rows:
        created = _aware(r.created_at)
        finalized = _aware(r.completed_at)
        if r.status == "done" and finalized is None:
            continue
        if finalized is not None and finalized < created:
            finalized = created
        out.append(FinalizedCheckin(id=r.id, user_id=r.user_id, pair_id=pair_id, plan_item_id=r.plan_item_id,
                                    status=r.status, created_at=created, finalized_at=finalized))
    return out


class TeamMeasurementSource:
    def load(self, pair: PairContext, known_at: datetime) -> MeasurementInput:
        members = (pair.user_a, pair.user_b)
        items, versions = plan_workload(pair.pair_id, members, known_at)
        if len(versions) < 2:
            raise InputUnavailableError("Cả hai bạn cần có kế hoạch trước khi đo tiến độ")
        checkins = finalized_checkins(pair.pair_id, members)
        revision = f"team.v1:p{'-'.join(str(versions[m]) for m in members)}:c{len(checkins)}"
        return MeasurementInput(pair=pair, source_revision=revision, plans_ready=True, history_complete=True,
                                plan_items=items, checkins=checkins)


def get_team_measurement_source() -> TeamMeasurementSource:
    return TeamMeasurementSource()
