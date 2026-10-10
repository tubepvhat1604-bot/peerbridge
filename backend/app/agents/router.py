from .state import AgentIntent


def detect_intent(message: str) -> AgentIntent:
    normalized = message.casefold()
    routes: tuple[tuple[AgentIntent, tuple[str, ...]], ...] = (
        ("safety", ("quấy rối", "lừa đảo", "báo cáo", "report", "không an toàn", "chặn")),
        ("conversation", ("nhắn gì", "mở đầu", "bắt chuyện", "trả lời sao", "nói chuyện thế nào")),
        ("matches", ("gợi ý", "phù hợp", "match", "kết nối", "tìm người", "ai hợp")),
        ("profile", ("hồ sơ", "bio", "giới thiệu", "sở thích", "profile")),
        ("conversation", ("trò chuyện", "tin nhắn")),
    )
    for intent, keywords in routes:
        if any(keyword in normalized for keyword in keywords):
            return intent
    return "general"

