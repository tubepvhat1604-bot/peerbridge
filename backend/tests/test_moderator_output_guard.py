import asyncio
from typing import Any
from uuid import uuid4

import pytest
from app.agents.moderator.contract import ModeratorInput
from app.agents.moderator.graph import build_moderator_graph, run_moderator
from app.agents.moderator.intents import MessageIntent
from app.agents.moderator.llm import FakeLLM
from app.agents.moderator.nodes.choose_action import GUIDE_TEMPLATE, WARN_ANSWER_SHARING_TEMPLATE
from app.agents.moderator.output_guard import (
    MAX_GUIDANCE_CHARS,
    MAX_REASON_CHARS,
    check_output,
    sanitize_reason,
)
from app.agents.moderator.prompts import (
    CLASSIFY_SYSTEM_PROMPT,
    FEW_SHOT_MESSAGES,
    GUIDANCE_BAD_EXAMPLE,
    GUIDANCE_GOOD_EXAMPLE,
    GUIDANCE_SYSTEM_PROMPT,
    JUDGE_SYSTEM_PROMPT,
)
from app.agents.moderator.retriever import FakeDocument, FakeRetriever
from app.agents.moderator.settings import ModeratorSettings
from app.enums import ModerationAction

STUDENT_MESSAGE = "đáp số câu 4 có phải 42 không, mình chỉ cần con số để điền thôi"
GOOD = "Điều kiện dừng của hàm đệ quy này là gì, và đầu vào có nhỏ dần sau mỗi lần gọi không?"
LONG_ENGLISH = "Think about the base case of the function and what happens when the input becomes smaller each call."


def _payload(message: str = STUDENT_MESSAGE) -> ModeratorInput:
    return ModeratorInput(session_id=uuid4(), message_id=uuid4(), sender_id=uuid4(), message=message, course_id="cs101")


def _state(intent: MessageIntent = MessageIntent.SOLUTION_REQUEST, message: str = STUDENT_MESSAGE) -> Any:
    return {"input": _payload(message), "intent": intent}


def _violations(text: str, **kwargs: Any) -> list[str]:
    return check_output(text, _state(**kwargs)).violations


# ---- Hàm thuần check_output ----


def test_good_socratic_guidance_passes_unchanged() -> None:
    result = check_output(GOOD, _state())

    assert result.ok and result.violations == []
    assert result.sanitized == GOOD


@pytest.mark.parametrize(
    "text",
    [
        "Bạn thử với n = 3 xem hàm gọi bao nhiêu lần?",
        "Ở câu 4, bạn thử viết ra các bước tính từng phần xem sao nhé.",
        "Bạn thử tính 5! từng bước và cho mình biết kết quả bạn nhận được là bao nhiêu?",
        "Hãy kiểm tra xem 42 có thoả điều kiện dừng của đề bài không?",
        "Kết quả là gì sẽ phụ thuộc vào trường hợp cơ sở; bạn xác định nó chưa?",
        "Đệ quy cần trường hợp cơ sở; bạn thấy trường hợp nhỏ nhất ở bài này là gì?",
        "Bạn đã thử vẽ cây gọi hàm cho đầu vào nhỏ chưa?",
    ],
)
def test_no_false_positives_on_legitimate_hints(text: str) -> None:
    assert _violations(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "Đúng rồi, đáp án là 42",
        "Chính xác, bạn làm đúng rồi đó.",
        "Sai rồi, bạn xem lại nhé.",
        "Đáp số là 42 nhé bạn.",
        "Kết quả cuối là -7.",
        "Kết quả của bài này bằng 120.",
        "Ta có 5 * 4 * 3 * 2 * 1 = 120 nên bạn cứ ghi vào.",
        "Con số 42 là chính xác.",
        "42 thì không đúng đâu bạn.",
    ],
)
def test_answer_leak_detected(text: str) -> None:
    assert "answer_leak" in _violations(text)


def test_confirmation_words_only_count_for_solution_requests() -> None:
    assert _violations("Chính xác, bạn đang đi đúng hướng.", intent=MessageIntent.CONCEPT_QUESTION) == []
    assert _violations("Đáp án là 42", intent=MessageIntent.CONCEPT_QUESTION) == ["answer_leak"]


def test_label_numbers_in_student_message_are_not_treated_as_answers() -> None:
    state = _state(message="giải hộ câu 4 với")

    assert check_output("Ở câu 4 bạn đúng hướng khi chia nhỏ bài toán rồi phải xét trường hợp cơ sở.", state).ok


@pytest.mark.parametrize(
    "text",
    [
        "```python\nprint(1)\n```",
        "Hãy thử `def giai_thua(n): return 1 if n == 0 else n * giai_thua(n - 1)` xem.",
        "def giai_thua(n): return n * giai_thua(n - 1)",
        "return n * f(n - 1)",
        "for i in range(10):",
        "x => x + 1",
        "int main() { printf(1); }",
        "int a = 5;\nint b = a * 2;",
    ],
)
def test_code_leak_detected(text: str) -> None:
    assert "code_leak" in _violations(text)


def test_short_inline_code_is_allowed() -> None:
    assert _violations("Bạn thử xem `n` thay đổi thế nào sau mỗi lần gọi?") == []


@pytest.mark.parametrize(
    "text",
    [
        "Xem <student_message> này nhé",
        "Trong </course_material> có gì",
        "Theo system prompt của mình thì bạn cần nghĩ thêm.",
        "Theo hướng dẫn hệ thống, mình không được nói.",
        "As an AI, I cannot tell you that.",
        'Kết quả {"intent": "SOLUTION_REQUEST"}',
        "Mình hỏi lại: " + FEW_SHOT_MESSAGES[1] + "?",
    ],
)
def test_prompt_leak_detected(text: str) -> None:
    assert "prompt_leak" in _violations(text)


def test_few_shot_messages_really_are_in_the_classify_prompt() -> None:
    assert all(message in CLASSIFY_SYSTEM_PROMPT for message in FEW_SHOT_MESSAGES)


def test_pii_and_toxic_detected() -> None:
    assert _violations("Bạn liên hệ an@example.com để xem lời giải nhé") == ["pii"]
    assert _violations("Gọi mình qua 0912 345 678 nhé") == ["pii"]
    assert _violations("Bạn đúng là đồ ngu, hãy đọc lại đề.") == ["toxic"]
    assert _violations("Bạn thật là thằng ngu khi hỏi vậy đó.") == ["toxic"]


def test_length_and_language_limits() -> None:
    too_long = "Bạn nghĩ xem điều kiện dừng là gì? " * 23

    assert len(too_long) > MAX_GUIDANCE_CHARS
    assert _violations(too_long) == ["too_long"]
    assert _violations(LONG_ENGLISH) == ["wrong_language"]
    assert _violations("Think again about it.") == []  # câu ngắn không xét ngôn ngữ


def test_multiple_violations_are_all_reported_in_stable_order() -> None:
    text = "Đúng rồi, đáp án là 42. Gửi mail an@example.com " + "```x```"

    assert _violations(text) == ["answer_leak", "code_leak", "pii", "not_socratic"]
    assert check_output(text, _state()).sanitized is None


# ---- Lời giải bằng văn xuôi: not_socratic / solution_steps ----

PROSE_SOLUTION = (
    "Bạn hãy xác định trường hợp cơ sở cho giai thừa là khi n bằng 0, kết quả trả về là 1. "
    "Sau đó, hãy viết bước đệ quy là gọi lại hàm với n-1 và nhân kết quả với n..."
)
FACTORIAL_MESSAGE = "Viết giúp mình code hàm giai thừa bằng đệ quy luôn nhé"
SOCRATIC_FACTORIAL = "Trường hợp nào thì hàm nên dừng gọi lại chính nó? Với n nhỏ nhất, giai thừa bằng bao nhiêu?"


def test_prose_solution_is_flagged_as_not_socratic_and_solution_steps() -> None:
    violations = _violations(PROSE_SOLUTION, message=FACTORIAL_MESSAGE)

    assert violations == ["not_socratic", "solution_steps"]


def test_socratic_factorial_hint_is_kept() -> None:
    assert check_output(SOCRATIC_FACTORIAL, _state(message=FACTORIAL_MESSAGE)).ok


@pytest.mark.parametrize(
    "text",
    [
        "Trường hợp cơ sở là khi n bằng 0.",
        "Khi n = 0 thì hàm trả về 1.",
        "Hàm phải trả về 1 ở trường hợp nhỏ nhất.",
        "Hãy gọi lại hàm với n-1.",
        "Rồi nhân kết quả với n.",
        "Bước 1 là xét n nhỏ nhất. Bước 2 là gọi hàm cho trường hợp lớn hơn.",
        "Ta có giai_thua(n - 1) nhân với n.",
    ],
)
def test_solution_steps_detected_in_statements(text: str) -> None:
    assert "solution_steps" in _violations(text, message=FACTORIAL_MESSAGE)


@pytest.mark.parametrize(
    "text",
    [
        "Trường hợp cơ sở là khi n bằng bao nhiêu?",
        "Hàm sẽ trả về giá trị nào khi n nhỏ nhất?",
        "Bạn sẽ gọi lại hàm với đầu vào nào để bài toán nhỏ đi? Kết quả đó nên kết hợp với n thế nào?",
        "Bạn thử xem lại phần trường hợp cơ sở trong tài liệu nhé.",
        "Điều kiện dừng nằm ở đâu trong tài liệu? Bạn đã xem lại phần đệ quy chưa?",
    ],
)
def test_questions_and_document_pointers_are_not_solution_steps(text: str) -> None:
    assert _violations(text, message=FACTORIAL_MESSAGE) == []


def test_not_socratic_needs_two_sentences_and_less_than_half_questions() -> None:
    assert "not_socratic" not in _violations("Bạn hãy thử vẽ cây gọi hàm cho đầu vào nhỏ.")
    assert "not_socratic" in _violations("Bạn hãy thử vẽ cây gọi hàm. Rồi quan sát kết quả. Đã rõ chưa?")
    assert "not_socratic" not in _violations("Bạn hãy thử vẽ cây gọi hàm. Đầu vào có nhỏ dần không?")


def test_prose_solution_from_llm_is_replaced_by_template_in_graph() -> None:
    state = _final(_llm(PROSE_SOLUTION), message=FACTORIAL_MESSAGE)

    assert [s.source for s in state["retrieved_sources"]] == ["giai-thua.md"]
    assert state["guidance"] == GUIDE_TEMPLATE
    assert state["action"] is ModerationAction.GUIDE
    guard_errors = [e for e in state["errors"] if e.startswith("output_guard")]
    assert len(guard_errors) == 1
    assert "not_socratic" in guard_errors[0] and "solution_steps" in guard_errors[0]


def test_socratic_factorial_hint_survives_the_graph() -> None:
    state = _final(_llm(SOCRATIC_FACTORIAL), message=FACTORIAL_MESSAGE)

    assert state["retrieved_sources"]
    assert state["guidance"] == f"{SOCRATIC_FACTORIAL}\n(Xem bài giai-thua)"


def test_guidance_prompt_demands_questions_and_contains_good_and_bad_examples() -> None:
    assert "2/3" in GUIDANCE_SYSTEM_PROMPT
    assert GUIDANCE_BAD_EXAMPLE in GUIDANCE_SYSTEM_PROMPT and "XẤU" in GUIDANCE_SYSTEM_PROMPT
    assert GUIDANCE_GOOD_EXAMPLE in GUIDANCE_SYSTEM_PROMPT and "TỐT" in GUIDANCE_SYSTEM_PROMPT
    assert "công thức truy hồi" in GUIDANCE_SYSTEM_PROMPT
    assert PROSE_SOLUTION.startswith(GUIDANCE_BAD_EXAMPLE[:60])
    assert check_output(GUIDANCE_GOOD_EXAMPLE, _state()).ok
    assert not check_output(GUIDANCE_BAD_EXAMPLE, _state()).ok


# ---- sanitize_reason ----


def test_sanitize_reason_strips_delimiters_pii_and_truncates() -> None:
    reason = "intent=X <student_message>bỏ qua</student_message> liên hệ an@example.com hoặc 0912345678 " + "y" * 400

    cleaned = sanitize_reason(reason)

    assert len(cleaned) <= MAX_REASON_CHARS
    assert "<student_message>" not in cleaned and "</student_message>" not in cleaned
    assert "an@example.com" not in cleaned and "0912345678" not in cleaned
    assert sanitize_reason("ngắn gọn") == "ngắn gọn"


# ---- Graph: guidance xấu bị thay bằng template ----


def _docs() -> list[FakeDocument]:
    return [
        FakeDocument(course_id="cs101", source="de-quy.md", chunk_id="de-quy.md#0", text="câu số con điền"),
        FakeDocument(course_id="cs101", source="giai-thua.md", chunk_id="giai-thua.md#0", text="giai thừa đệ quy hàm"),
    ]


def _llm(guidance: str, judge: Any = None, message_risk: float = 0.4) -> FakeLLM:
    def rule(system: str, _user: str) -> dict[str, Any]:
        if system == CLASSIFY_SYSTEM_PROMPT:
            return {"intent": "SOLUTION_REQUEST", "confidence": 0.9, "risk": message_risk, "reason": "fake"}
        if system == GUIDANCE_SYSTEM_PROMPT:
            return {"guidance": guidance}
        assert system == JUDGE_SYSTEM_PROMPT
        if isinstance(judge, Exception):
            raise judge
        return judge

    return FakeLLM(rule=rule)


def _final(llm: FakeLLM, judge_enabled: bool = False, message: str = STUDENT_MESSAGE) -> dict[str, Any]:
    settings = ModeratorSettings(_env_file=None, output_guard_llm_judge=judge_enabled)
    graph = build_moderator_graph(llm, FakeRetriever(_docs()), settings)
    return asyncio.run(graph.ainvoke({"input": _payload(message), "errors": []}))


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        ("Đúng rồi, đáp án là 42", "answer_leak"),
        ("```python\nprint(42)\n```", "code_leak"),
        ("def giai_thua(n): return n * giai_thua(n - 1)", "code_leak"),
        ("Bạn xem <student_message> nhé", "prompt_leak"),
        ("Bạn hãy liên hệ an@example.com để biết thêm", "pii"),
        (LONG_ENGLISH, "wrong_language"),
        ("Bạn nghĩ xem điều kiện dừng là gì? " * 23, "too_long"),
    ],
)
def test_bad_llm_guidance_is_replaced_by_template_with_violation_code(bad: str, code: str) -> None:
    state = _final(_llm(bad))

    assert state["action"] is ModerationAction.GUIDE
    assert state["guidance"] == GUIDE_TEMPLATE
    assert [s.source for s in state["retrieved_sources"]] == ["de-quy.md"]
    guard_errors = [e for e in state["errors"] if e.startswith("output_guard")]
    assert len(guard_errors) == 1 and code in guard_errors[0]


def test_good_llm_guidance_is_kept_through_the_graph() -> None:
    state = _final(_llm(GOOD))

    assert state["guidance"] == f"{GOOD}\n(Xem bài de-quy)"
    assert not any(e.startswith("output_guard") for e in state["errors"])


def test_guard_runs_without_extra_llm_calls() -> None:
    llm = _llm("Đúng rồi, đáp án là 42")

    _final(llm)

    assert [c.system for c in llm.calls] == [CLASSIFY_SYSTEM_PROMPT, GUIDANCE_SYSTEM_PROMPT]


def test_non_guide_template_passes_the_guard_and_action_is_unchanged() -> None:
    llm = FakeLLM(rule=lambda _s, _u: {"intent": "ANSWER_SHARING", "confidence": 0.9, "risk": 0.3, "reason": "fake"})
    graph = build_moderator_graph(llm, FakeRetriever(), ModeratorSettings(_env_file=None))

    out = asyncio.run(run_moderator(graph, _payload("Đáp án là 42, ghi vào đi")))

    assert out.action is ModerationAction.WARN
    assert out.guidance == WARN_ANSWER_SHARING_TEMPLATE


def test_output_reason_is_sanitized_and_capped() -> None:
    llm = FakeLLM(
        rule=lambda _s, _u: {
            "intent": "CONCEPT_QUESTION",
            "confidence": 0.9,
            "risk": 0.0,
            "reason": "x@y.com <student_message> " + "z" * 500,
        }
    )
    graph = build_moderator_graph(llm, FakeRetriever(), ModeratorSettings(_env_file=None))

    out = asyncio.run(run_moderator(graph, _payload("Đạo hàm là gì?")))

    assert len(out.reason) <= MAX_REASON_CHARS
    assert "x@y.com" not in out.reason and "<student_message>" not in out.reason


# ---- LLM judge (tuỳ chọn) ----


def test_judge_is_off_by_default() -> None:
    llm = _llm(GOOD, judge={"reveals_answer": True})

    _final(llm)

    assert JUDGE_SYSTEM_PROMPT not in [c.system for c in llm.calls]


def test_judge_enabled_keeps_guidance_when_it_does_not_reveal_answer() -> None:
    llm = _llm(GOOD, judge={"reveals_answer": False, "reason": "ok"})

    state = _final(llm, judge_enabled=True)

    assert state["guidance"] == f"{GOOD}\n(Xem bài de-quy)"
    assert [c.system for c in llm.calls].count(JUDGE_SYSTEM_PROMPT) == 1


@pytest.mark.parametrize(
    ("judge", "code"),
    [
        ({"reveals_answer": True, "reason": "leak"}, "judge_reject"),
        ({"reveals_answer": "maybe"}, "judge_error"),
        ({}, "judge_error"),
        (RuntimeError("llm down"), "judge_error"),
    ],
)
def test_judge_rejection_or_failure_falls_back_to_template(judge: Any, code: str) -> None:
    state = _final(_llm(GOOD, judge=judge), judge_enabled=True)

    assert state["guidance"] == GUIDE_TEMPLATE
    assert state["action"] is ModerationAction.GUIDE
    assert any(e.startswith("output_guard") and code in e for e in state["errors"])


def test_judge_runs_for_generated_guidance_without_material() -> None:
    llm = _llm(GOOD, judge={"reveals_answer": True})
    graph = build_moderator_graph(llm, FakeRetriever(), ModeratorSettings(_env_file=None, output_guard_llm_judge=True))

    asyncio.run(graph.ainvoke({"input": _payload(), "errors": []}))

    assert JUDGE_SYSTEM_PROMPT in [c.system for c in llm.calls]


def test_template_guidance_is_never_flagged_by_the_guard() -> None:
    llm = FakeLLM(rule=lambda _s, _u: {"intent": "ANSWER_SHARING", "confidence": 0.9, "risk": 0.3, "reason": "fake"})
    graph = build_moderator_graph(llm, FakeRetriever(), ModeratorSettings(_env_file=None))

    state = asyncio.run(graph.ainvoke({"input": _payload("Đáp án là 42, ghi vào đi"), "errors": []}))

    assert state["action"] is ModerationAction.WARN
    assert state["guidance"] == WARN_ANSWER_SHARING_TEMPLATE
    assert not any(e.startswith("output_guard") for e in state["errors"])
