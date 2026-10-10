"""Schema và loader cho dataset eval."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ....enums import ModerationAction
from ..intents import MessageIntent

EVAL_DIR = Path(__file__).resolve().parent
DATASET_PATH = EVAL_DIR / "dataset.jsonl"
RAG_QUERIES_PATH = EVAL_DIR / "rag_queries.jsonl"

Split = Literal["dev", "test", "holdout"]


class HistoryItem(BaseModel):
    """Một lượt chat trước đó; who='me' là người gửi tin đang xét, 'peer' là bạn học."""

    who: Literal["me", "peer"]
    content: str = Field(min_length=1)


class EvalCase(BaseModel):
    """Một tin nhắn có nhãn. Đúng nếu action thuộc {expected_action} ∪ acceptable_actions."""

    id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryItem] = Field(default_factory=list)
    course_id: str = Field(min_length=1)
    expected_action: ModerationAction
    acceptable_actions: list[ModerationAction] = Field(default_factory=list)
    expected_intent: MessageIntent
    category: str = Field(min_length=1)
    split: Split
    note: str = ""

    @property
    def allowed_actions(self) -> set[ModerationAction]:
        """Các action được coi là đúng."""
        return {self.expected_action, *self.acceptable_actions}


class RagQuery(BaseModel):
    """Một câu truy vấn RAG; expected_source=None nghĩa là câu không liên quan tài liệu."""

    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    expected_source: str | None = None
    expected_chunk_ids: list[str] = Field(default_factory=list)


def _load_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def load_dataset(path: Path = DATASET_PATH) -> list[EvalCase]:
    """Đọc và validate dataset."""
    return [EvalCase.model_validate(row) for row in _load_jsonl(path)]


def load_rag_queries(path: Path = RAG_QUERIES_PATH) -> list[RagQuery]:
    """Đọc và validate bộ câu hỏi RAG."""
    return [RagQuery.model_validate(row) for row in _load_jsonl(path)]


def filter_split(cases: list[EvalCase], split: str) -> list[EvalCase]:
    """Lọc theo split: 'dev', 'test' hoặc 'all'."""
    return cases if split == "all" else [case for case in cases if case.split == split]


def check_dataset(cases: list[EvalCase]) -> list[str]:
    """Trả danh sách vấn đề của dataset (rỗng nếu hợp lệ): id trùng, nhãn tự mâu thuẫn, category thiếu split."""
    problems: list[str] = []
    ids = [case.id for case in cases]
    problems += [f"id trùng: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for case in cases:
        if case.expected_action in case.acceptable_actions:
            problems.append(f"{case.id}: acceptable_actions chứa expected_action")
    splits: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        splits[case.category].add(case.split)
    problems += [f"category {c!r} chỉ có ở split {sorted(s)}" for c, s in splits.items() if len(s) < 2]
    return problems
