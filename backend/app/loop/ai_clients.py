"""Bật AI cho các phần đã chừa cổng: chia việc trong plan (Data 2), xếp hạng ghép cặp (Data 1)."""
from __future__ import annotations

import asyncio
import json
import os

from ..agents.plan_coach.llm import PlanSettings
from ..agents.plan_coach.llm import provider as plan_provider
from .ai_budget import MeteredLLM, budget_left, record


class OpenAIJsonClient:
    """`JsonClient` của Data 1 dùng OpenAI (trả JSON). Ghi chi phí; hết trần thì báo lỗi để Data 1 tự quay về cách cũ."""

    def __init__(self, feature: str, model: str | None = None):
        from ..config import get_settings

        self.feature = feature
        self.model = model or os.environ.get("MATCH_RERANK_MODEL", "gpt-4.1-mini")
        self.api_key = get_settings().openai_api_key

    async def complete_json(self, system: str, user: str) -> dict:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY_MISSING")
        if budget_left() <= 0:
            raise ValueError("AI_DAILY_BUDGET_EXCEEDED")
        import openai

        client = openai.OpenAI(api_key=self.api_key, timeout=8, max_retries=0)
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=self.model, temperature=0, max_completion_tokens=400, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        if resp.usage:
            record(self.feature, self.model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
        return json.loads(resp.choices[0].message.content or "{}")


def get_team_reranker():
    """Thay `get_reranker` của Data 1: bật xếp hạng bằng AI khi có key và MATCH_RERANK_ENABLED=true."""
    if os.environ.get("MATCH_RERANK_ENABLED", "false").lower() != "true":
        return None
    from ..matching.reranking import StructuredReranker

    client = OpenAIJsonClient("match_rerank")
    return StructuredReranker(client) if client.api_key else None


def get_team_plan_service():
    """Thay `get_plan_service` của Data 2: ghi chi phí AI chia việc, hết trần thì dùng mẫu có sẵn."""
    from ..services.plans import PlanService

    settings = PlanSettings()
    if settings.llm_provider == "openai_compatible" and budget_left() <= 0:
        settings = settings.model_copy(update={"llm_provider": "template"})
    return PlanService(settings, llm_factory=lambda *a, **k: MeteredLLM(plan_provider(*a, **k), "plan_tasks"))
