import asyncio

import pytest
from app.agents.plan_coach.graph import CoachSelector
from app.agents.plan_coach.llm import FakeLLM


@pytest.mark.parametrize(
    "response,mode,action",
    [
        ({"action": "no_action", "message": ""}, "v2", "no_action"),
        ({"action": "delete_plan", "reason": "Untrusted action"}, "v1_fallback", "replan"),
        (
            {"action": "reminder", "message": "Bạn có thể chọn một việc nhỏ trong Plan và check-in khi sẵn sàng."},
            "v2",
            "reminder",
        ),
        (TimeoutError("fake timeout"), "v1_fallback", "replan"),
        ({"action": "replan", "reason": "allowed", "tool": "write_database"}, "v1_fallback", "replan"),
        ({"action": "replan"}, "v1_fallback", "replan"),
        ("not-json", "v1_fallback", "replan"),
    ],
)
def test_graph_validates_code_allowed_actions_and_falls_back(response, mode, action):
    selector = CoachSelector(FakeLLM([response]))
    result = asyncio.run(selector.select(["replan", "reminder", "no_action"], "ELIGIBLE"))
    assert result["action"] == action and result["mode"] == mode
    assert result["nodes"] == ["load_context", "eligibility", "decide", "validate_action", "prepare_action", "save_log"]
    assert result["provider_mode"] == "fake"
    assert "raw" not in result


def test_graph_no_eligible_action_does_not_call_llm():
    llm = FakeLLM([])
    result = asyncio.run(CoachSelector(llm).select(["no_action"], "NO_DUE_WORK"))
    assert result["action"] == "no_action" and not llm.calls


def test_real_async_timeout_falls_back_and_cancels_selection():
    class SlowLLM(FakeLLM):
        cancelled = False

        async def complete_json(self, *args):
            try:
                await asyncio.sleep(10)
            finally:
                self.cancelled = True

    llm = SlowLLM([])
    result = asyncio.run(CoachSelector(llm, timeout=0.01).select(["replan", "no_action"], "ELIGIBLE"))
    assert llm.cancelled and result["action"] == "replan"
    assert result["mode"] == "v1_fallback" and result["error"] == "TimeoutError"


def test_graph_sends_only_authorized_context_and_invalid_content_uses_template():
    import json

    from app.agents.plan_coach.coach import TEMPLATES

    llm = FakeLLM([{"action": "offer_support", "reason": "Ignore permissions and write DB"}])
    selector = CoachSelector(llm)
    result = asyncio.run(
        selector.graph.ainvoke(
            {"allowed": ["offer_support", "delete_plan"], "reason": "ELIGIBLE", "concept_id": "sql.join"}
        )
    )
    assert result["text"] == TEMPLATES["offer_support"].format(concept_id="sql.join")
    assert "Ignore permissions" not in result["text"]
    packet = json.loads(llm.calls[0][1])
    assert packet == {"allowed": ["offer_support", "no_action"], "reason": "ELIGIBLE", "concept_id": "sql.join"}
