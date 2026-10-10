"""Node choose_action: bảng policy thuần Python, không gọi LLM.

Thứ tự ưu tiên (dòng đầu khớp thì dừng):
  1. risk_score >= risk_escalate_threshold -> ESCALATE
  2. HARMFUL                               -> BLOCK
  3. ACADEMIC_DISHONESTY                   -> ESCALATE
  4. ANSWER_SHARING                        -> WARN nếu risk < ANSWER_SHARING_BLOCK_RISK, ngược lại BLOCK
  5. SOLUTION_REQUEST                      -> GUIDE
  6. CONCEPT_QUESTION, SOCIAL              -> ALLOW
  7. OFF_TOPIC                             -> WARN nếu risk >= OFF_TOPIC_WARN_RISK, ngược lại ALLOW
"""

from ....enums import ModerationAction
from ..intents import MessageIntent
from ..state import ModeratorState

ANSWER_SHARING_BLOCK_RISK = 0.6
OFF_TOPIC_WARN_RISK = 0.4

GUIDE_TEMPLATE = (
    "Mình không thể giải hộ, nhưng mình sẽ đồng hành cùng bạn từng bước. "
    "Bạn đã thử hướng nào rồi và đang vướng ở bước nào?"
)
WARN_ANSWER_SHARING_TEMPLATE = (
    "Vui lòng không đăng đáp án hoặc lời giải hoàn chỉnh. Hãy giải thích hướng tư duy để bạn học cùng tự làm được."
)
WARN_OFF_TOPIC_TEMPLATE = "Tin nhắn này có vẻ lạc khỏi nội dung buổi học. Hãy quay lại chủ đề môn học nhé."


def decide_action(intent: MessageIntent, risk_score: float, escalate_threshold: float) -> tuple[ModerationAction, str]:
    """Trả (action, lý do policy). Hàm thuần, dễ test riêng."""
    if risk_score >= escalate_threshold:
        return ModerationAction.ESCALATE, f"risk {risk_score:.2f} >= ngưỡng escalate {escalate_threshold:.2f}"
    if intent is MessageIntent.HARMFUL:
        return ModerationAction.BLOCK, "nội dung gây hại (xúc phạm/quấy rối/lộ thông tin cá nhân)"
    if intent is MessageIntent.ACADEMIC_DISHONESTY:
        return ModerationAction.ESCALATE, "nghi ngờ gian lận học thuật, cần Admin xem xét"
    if intent is MessageIntent.ANSWER_SHARING:
        if risk_score >= ANSWER_SHARING_BLOCK_RISK:
            return ModerationAction.BLOCK, "chia sẻ đáp án với rủi ro cao"
        return ModerationAction.WARN, "có dấu hiệu chia sẻ đáp án"
    if intent is MessageIntent.SOLUTION_REQUEST:
        return ModerationAction.GUIDE, "xin đáp án, chuyển sang hướng dẫn Socratic"
    if intent is MessageIntent.OFF_TOPIC and risk_score >= OFF_TOPIC_WARN_RISK:
        return ModerationAction.WARN, "lạc chủ đề với rủi ro đáng chú ý"
    return ModerationAction.ALLOW, "tin nhắn an toàn"


def template_guidance(action: ModerationAction, intent: MessageIntent) -> str | None:
    if action is ModerationAction.GUIDE:
        return GUIDE_TEMPLATE
    if action is ModerationAction.WARN:
        return WARN_OFF_TOPIC_TEMPLATE if intent is MessageIntent.OFF_TOPIC else WARN_ANSWER_SHARING_TEMPLATE
    return None


def choose_action(state: ModeratorState, escalate_threshold: float) -> dict:
    """Áp policy lên intent + risk_score; ESCALATE luôn kéo theo needs_human_review."""
    intent, risk_score = state["intent"], state["risk_score"]
    action, policy_reason = decide_action(intent, risk_score, escalate_threshold)
    if state.get("classification_unavailable") and not state["rule_signals"].hard:
        action, policy_reason = ModerationAction.ESCALATE, "classifier unavailable; manual review required"
    detail = f"intent={intent.value}, risk={risk_score:.2f}: {policy_reason}"
    if state.get("reason"):
        detail = f"{detail} ({state['reason']})"
    return {
        "action": action,
        "reason": detail,
        "guidance": template_guidance(action, intent),
        "needs_human_review": action is ModerationAction.ESCALATE,
        "retrieved_sources": [],
    }
