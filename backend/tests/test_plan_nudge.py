import asyncio

import pytest
from app.agents.plan_coach.coach import TEMPLATES
from app.agents.plan_coach.graph import CoachSelector
from app.agents.plan_coach.llm import FakeLLM


@pytest.mark.parametrize(
    "message",
    [
        "Bạn có thể xem phương án giảm tải và tự quyết định khi sẵn sàng.",
        "Nếu bạn muốn, xem phương án giảm tải và xác nhận khi sẵn sàng.",
    ],
)
def test_ai_writes_original_vietnamese_message_instead_of_template(message):
    result = asyncio.run(
        CoachSelector(FakeLLM([{"action": "replan", "message": message}])).select(["replan", "no_action"], "ELIGIBLE")
    )
    assert result["text"] == message and result["text"] != TEMPLATES["replan"]
    assert result["message_source"] == "ai" and result["mode"] == "v2"


@pytest.mark.parametrize(
    "packet",
    [
        {"action": "replan", "reason": "old selector schema"},
        {"action": "delete_plan", "message": "Bạn có thể xóa kế hoạch."},
        {"action": "replan", "message": "Bạn có thể xem phương án; plan đã đổi và đã gửi thành công."},
        {"action": "replan", "message": "Bạn có thể xem phương án lúc 19:00 ngày mai và xác nhận."},
        {"action": "replan", "message": "Bạn có thể xem phương án vì partner đã hoàn thành tất cả."},
        {"action": "replan", "message": "Bạn có thể xem phương án nhưng phải xác nhận ngay."},
        {"action": "replan", "message": "Please confirm this plan now."},
        {"action": "replan", "message": "Bạn có thể xem https://invented.test để xác nhận."},
        {"action": "replan", "message": "Bạn có thể " + "x" * 250},
        {"action": "replan", "message": 123},
        {"action": "no_action", "message": "Bạn có thể làm việc nhỏ ngay."},
        {"action": "replan", "message": "Bạn có thể xem phương án giảm tải và tự quyết định.", "db_tool": "write"},
    ],
)
def test_bad_schema_action_claim_pressure_schedule_or_language_falls_back(packet):
    result = asyncio.run(CoachSelector(FakeLLM([packet])).select(["replan", "no_action"], "ELIGIBLE"))
    assert result["mode"] == "v1_fallback" and result["text"] == TEMPLATES["replan"]
    assert result["message_source"] == "template"


def test_support_can_only_reference_the_authorized_concept_and_mutual_agreement():
    message = "Bạn có thể đề nghị hỗ trợ về sql.join khi hai bên cùng đồng ý."
    llm = FakeLLM([{"action": "offer_support", "message": message}])
    selector = CoachSelector(llm)
    assert asyncio.run(selector.select(["offer_support", "no_action"], "ELIGIBLE", "sql.join"))["text"] == message
    bad = FakeLLM([{"action": "offer_support", "message": message}])
    assert (
        asyncio.run(CoachSelector(bad).select(["offer_support", "no_action"], "ELIGIBLE", "python.loops"))["mode"]
        == "v1_fallback"
    )


def test_no_action_is_empty_and_does_not_request_a_message():
    llm = FakeLLM([])
    result = asyncio.run(CoachSelector(llm).select(["no_action"], "QUIET_HOURS"))
    assert not llm.calls and result["text"] == "" and result["message_source"] == "none"
