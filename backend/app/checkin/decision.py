"""Quyết định trạng thái sau khi có kết quả AI (CONTEXT.md mục 8.5). Thuần logic, không I/O.

Quy tắc:
- Lỗi gọi AI -> failed, đưa các mục tuần này để người dùng chọn tay.
- Không phải ảnh học -> not_study (vẫn cho người dùng tự xác nhận nếu AI nhầm).
- Gom các mục plan chưa xong khớp concept AI thấy, theo từng concept (mỗi concept lấy mục hạn gần nhất).
  * Đúng 1 concept khớp và confidence >= cao  -> done (mục hạn gần nhất của concept đó).
  * Có khớp và confidence >= thấp (hoặc khớp >= 2 concept) -> needs_confirm, tối đa 3 lựa chọn.
  * Confidence < thấp hoặc không khớp mục nào -> needs_confirm, đưa các mục tuần này.
- Không có mục plan nào đang mở: ảnh học rõ -> done không gắn mục; còn lại -> needs_confirm.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import CheckinStatus
from .schemas import OptionOut, PlanItemRef, VisionResult


@dataclass
class Decision:
    status: str
    plan_item_id: str | None = None  # mục AI đề xuất / tự gắn
    options: list[OptionOut] = field(default_factory=list)


def _opt(item: PlanItemRef, names: dict[str, str]) -> OptionOut:
    return OptionOut(plan_item_id=item.id, label=item.label, concept_name=names.get(item.concept_id))


def decide(
    result: VisionResult | None,
    open_items: list[PlanItemRef],
    concept_names: dict[str, str],
    *,
    high: float = 0.75,
    low: float = 0.40,
    max_confirm: int = 3,
    max_week: int = 6,
) -> Decision:
    by_due = sorted(open_items, key=lambda i: (i.due_date, i.label))
    week_options = [_opt(i, concept_names) for i in by_due[:max_week]]

    if result is None:
        return Decision(CheckinStatus.FAILED, None, week_options)

    if not result.is_study:
        return Decision(CheckinStatus.NOT_STUDY, None, week_options)

    # Mục hạn gần nhất cho từng concept khớp, theo thứ tự nổi bật AI trả về.
    matched: list[PlanItemRef] = []
    for concept_id in result.concepts:
        candidates = [i for i in by_due if i.concept_id == concept_id]
        if candidates:
            matched.append(candidates[0])

    if not open_items:
        if result.confidence >= high:
            return Decision(CheckinStatus.DONE, None, [])
        return Decision(CheckinStatus.NEEDS_CONFIRM, None, [])

    if len(matched) == 1 and result.confidence >= high:
        return Decision(CheckinStatus.DONE, matched[0].id, [])

    if matched and (result.confidence >= low or len(matched) >= 2):
        chosen = matched[:max_confirm]
        chosen_ids = {i.id for i in chosen}
        for item in by_due:  # thêm mục khác cho đủ lựa chọn
            if len(chosen) >= max_confirm:
                break
            if item.id not in chosen_ids:
                chosen.append(item)
                chosen_ids.add(item.id)
        return Decision(CheckinStatus.NEEDS_CONFIRM, matched[0].id, [_opt(i, concept_names) for i in chosen])

    return Decision(CheckinStatus.NEEDS_CONFIRM, matched[0].id if matched else None, week_options)
