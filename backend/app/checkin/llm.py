"""Gọi mô hình vision.

- OpenAIVision: gọi OpenAI (Chat Completions), ép structured output qua tool_choice.
- FakeVision: không gọi mạng; dùng cho dev, test, demo offline. Hỗ trợ "thẻ ép kết quả"
  trong ghi chú để thử từng trạng thái giao diện: #low, #notstudy, #fail, #multi.
"""
from __future__ import annotations

import base64
import io
import json
import time
from abc import ABC, abstractmethod
from functools import lru_cache

from .config import get_settings
from .prompts import SYSTEM_PROMPT, TOOL_NAME, build_tool, build_user_text
from .schemas import ConceptRef, LLMUsage, VisionResult


class LLMError(RuntimeError):
    pass


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = get_settings().price_table.get(model, (0.0, 0.0))
    return round(input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out, 6)


def _truncate_words(text: str, n: int) -> str:
    words = text.split()
    return text if len(words) <= n else " ".join(words[:n]).rstrip(",;:") + "…"


def sanitize(result: VisionResult, allowed: list[str]) -> VisionResult:
    """Không tin hoàn toàn LLM: lọc concept ngoài danh sách, cắt độ dài, ép nhất quán."""
    seen: list[str] = []
    for c in result.concepts:
        if c in allowed and c not in seen:
            seen.append(c)
    result.concepts = seen[:3]
    result.description = _truncate_words(result.description, 30)
    result.summary_for_partner = _truncate_words(result.summary_for_partner, 24)
    if not result.is_study:
        result.concepts = []
        result.summary_for_partner = ""
    if result.is_study and not result.concepts:
        result.confidence = min(result.confidence, 0.39)
    return result


class VisionLLM(ABC):
    @abstractmethod
    def analyze(
        self,
        *,
        image: bytes | None,
        media_type: str,
        learner_name: str,
        concepts: list[ConceptRef],
        note: str | None,
        model: str | None = None,
    ) -> tuple[VisionResult, LLMUsage]: ...


def _is_reasoning_model(model: str) -> bool:
    """Dòng gpt-5 / o-series: không nhận temperature, cần thêm token cho phần suy luận."""
    return model.startswith(("gpt-5", "o1", "o3", "o4"))


class OpenAIVision(VisionLLM):
    def __init__(self) -> None:
        import openai

        s = get_settings()
        if not s.api_key:
            raise LLMError("Thiếu OPENAI_API_KEY (hoặc đặt LLM_PROVIDER=fake để chạy thử)")
        self.client = openai.OpenAI(api_key=s.api_key, timeout=s.llm_timeout_seconds, max_retries=2)

    def analyze(self, *, image, media_type, learner_name, concepts, note, model=None):
        s = get_settings()
        model = model or (s.vision_model if image else s.text_model)
        allowed = [c.id for c in concepts]
        content: list[dict] = []
        if image:
            data_url = f"data:{media_type};base64,{base64.b64encode(image).decode()}"
            content.append({"type": "image_url", "image_url": {"url": data_url, "detail": s.image_detail}})
        content.append({"type": "text", "text": build_user_text(learner_name, concepts, note, bool(image))})

        params: dict = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
            "tools": [build_tool(allowed)],
            "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        }
        if _is_reasoning_model(model):
            params.update(max_completion_tokens=2000, reasoning_effort="low")
        else:
            params.update(max_completion_tokens=400, temperature=0)

        t0 = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(**params)
        except Exception as e:  # lỗi mạng, timeout, quota…
            raise LLMError(f"{type(e).__name__}: {e}") from e
        latency = int((time.perf_counter() - t0) * 1000)

        calls = (resp.choices[0].message.tool_calls or []) if resp.choices else []
        call = next((c for c in calls if c.function.name == TOOL_NAME), None)
        if call is None:
            raise LLMError("Mô hình không trả về kết quả có cấu trúc")
        try:
            result = VisionResult.model_validate(json.loads(call.function.arguments))
        except Exception as e:
            raise LLMError(f"Kết quả sai cấu trúc: {e}") from e

        usage = LLMUsage(
            model=model,
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
            cost_usd=estimate_cost(model, resp.usage.prompt_tokens, resp.usage.completion_tokens),
            latency_ms=latency,
        )
        return sanitize(result, allowed), usage


class FakeVision(VisionLLM):
    """Kết quả giả định, có tính quyết định (deterministic)."""

    def analyze(self, *, image, media_type, learner_name, concepts, note, model=None):
        note_l = (note or "").lower()
        if "#fail" in note_l:
            raise LLMError("Lỗi giả lập (#fail)")
        allowed = [c.id for c in concepts]

        is_study = True
        if "#notstudy" in note_l:
            is_study = False
        elif image is not None and _looks_blank(image):
            is_study = False

        picked: list[str] = []
        for c in concepts:  # khớp theo từ khóa trong ghi chú
            keys = {c.id.split(".")[-1].replace("_", " "), c.name.lower()}
            if any(k and k in note_l for k in keys):
                picked.append(c.id)
        if not picked and concepts:
            picked = [concepts[0].id]
        if "#multi" in note_l and len(concepts) >= 2:
            picked = [concepts[0].id, concepts[1].id]

        confidence = 0.86
        if "#low" in note_l:
            confidence = 0.55
        names = {c.id: c.name for c in concepts}
        first = names.get(picked[0], "bài học") if picked else "bài học"
        result = VisionResult(
            is_study=is_study,
            concepts=picked if is_study else [],
            description=f"Đang học {first}" if is_study else "Ảnh không liên quan đến việc học",
            confidence=confidence if is_study else 0.9,
            summary_for_partner=f"{learner_name} vừa học {first}." if is_study else "",
        )
        tokens_in = 1700 if image else 300
        usage = LLMUsage(model="fake", input_tokens=tokens_in, output_tokens=120, cost_usd=0.0, latency_ms=5)
        return sanitize(result, allowed), usage


def _looks_blank(image: bytes) -> bool:
    """Ảnh gần như một màu (ví dụ chụp nhầm) -> coi là không phải ảnh học."""
    from PIL import Image, ImageStat

    try:
        img = Image.open(io.BytesIO(image)).convert("L").resize((64, 64))
        return ImageStat.Stat(img).stddev[0] < 4
    except Exception:
        return False


@lru_cache
def get_llm() -> VisionLLM:
    return OpenAIVision() if get_settings().llm_provider == "openai" else FakeVision()

