import json
import re
from typing import Any

import httpx

from ..config import get_settings
from .state import AgentIntent


def offline_response(intent: AgentIntent, profile: dict[str, Any], tool_result: dict[str, Any]) -> str:
    name = profile.get("display_name", "bạn")
    if intent == "safety":
        return "Nếu thấy không an toàn: dừng chia sẻ thông tin cá nhân hoặc tiền bạc, lưu bằng chứng, sau đó chặn và báo cáo tài khoản. Nếu có nguy hiểm trực tiếp, hãy liên hệ cơ quan chức năng địa phương."
    if intent == "matches":
        recommendations = tool_result.get("recommendations", [])
        if not recommendations:
            return "Hiện chưa còn hồ sơ mới để gợi ý. Bạn có thể bổ sung sở thích và lịch rảnh rồi thử lại."
        details = "; ".join(
            f"{item['name']} ({item['score']}%): {', '.join(item['reasons'][:2])}" for item in recommendations
        )
        return f"{name} hiện có {tool_result.get('match_count', 0)} kết nối. Gợi ý nổi bật: {details}."
    if intent == "profile":
        missing = tool_result.get("missing", [])
        if missing:
            return f"Hồ sơ của bạn hoàn thiện khoảng {tool_result.get('completeness', 0)}%. Nên bổ sung: {', '.join(missing)}. Tránh ghi số điện thoại hoặc địa chỉ riêng."
        return "Hồ sơ đã đủ các phần chính. Bạn có thể làm bio cụ thể hơn bằng cách nói hoạt động muốn cùng người khác trải nghiệm."
    if intent == "conversation":
        people = tool_result.get("matched_people", [])
        if people:
            person = people[0]
            interest = person.get("interests", ["một sở thích chung"])[0] if person.get("interests") else "một sở thích chung"
            return f"Bạn có thể nhắn {person['name']}: “Mình thấy bạn thích {interest}. Điều gì khiến bạn bắt đầu sở thích đó?” Câu hỏi cụ thể sẽ dễ trả lời hơn lời chào chung chung."
        return "Khi có match, hãy mở đầu bằng một chi tiết trong hồ sơ của họ và đặt câu hỏi cụ thể, nhẹ nhàng."
    return "Mình có thể xem độ hoàn thiện hồ sơ, tìm người phù hợp, gợi ý câu bắt chuyện hoặc hướng dẫn an toàn."


async def generate_response(
    message: str,
    intent: AgentIntent,
    profile: dict[str, Any],
    tool_result: dict[str, Any],
    memory: list[dict[str, str]],
) -> tuple[str, str]:
    fallback = offline_response(intent, profile, tool_result)
    settings = get_settings()
    if not settings.openai_api_key:
        return fallback, "offline"

    safe_profile = {
        key: profile.get(key)
        for key in ("display_name", "age", "city", "occupation", "bio", "intent", "interests", "available_times")
    }
    prompt = (
        "Bạn là trợ lý kết nối an toàn của ứng dụng Đồng Điệu. Trả lời bằng tiếng Việt, tối đa 180 từ. "
        "Không tiết lộ dữ liệu riêng tư, không suy diễn thuộc tính nhạy cảm, không hứa hẹn một match chắc chắn. "
        f"Intent: {intent}\nHồ sơ: {json.dumps(safe_profile, ensure_ascii=False)}\n"
        f"Kết quả tool: {json.dumps(tool_result, ensure_ascii=False)}\n"
        f"Lịch sử gần đây: {json.dumps(memory[-6:], ensure_ascii=False)}\nNgười dùng: {message}"
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": settings.openai_model, "input": prompt, "store": False, "max_output_tokens": 300},
            )
            response.raise_for_status()
            data = response.json()
        output = data.get("output_text", "")
        if not output:
            output = "".join(
                content.get("text", "")
                for item in data.get("output", [])
                for content in item.get("content", [])
                if content.get("type") == "output_text"
            )
        return re.sub(r"\s{3,}", "  ", output).strip() or fallback, "openai"
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return fallback, "offline-fallback"

