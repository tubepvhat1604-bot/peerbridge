"""CLI chạy thử moderator.

Chạy: python -m app.agents.moderator.cli --course-id demo-course "nội dung tin nhắn"
"""

import argparse
import asyncio
import sys
import time
from uuid import uuid4

from . import moderate_message, warmup_moderator
from .contract import ModeratorInput, ModeratorOutput


def main(argv: list[str] | None = None) -> None:
    """Kiểm duyệt một tin nhắn bằng settings thật (LLM + retriever theo .env) và in JSON."""
    parser = argparse.ArgumentParser(description="Chạy thử Socratic Moderator")
    parser.add_argument("message")
    parser.add_argument("--course-id", default="demo-course")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    payload = ModeratorInput(
        session_id=uuid4(),
        message_id=uuid4(),
        sender_id=uuid4(),
        message=args.message,
        course_id=args.course_id,
    )
    output = asyncio.run(_run(payload))
    print(output.model_dump_json(indent=2))


async def _run(payload: ModeratorInput) -> ModeratorOutput:
    start = time.perf_counter()
    ready = await warmup_moderator()
    load_seconds = time.perf_counter() - start
    start = time.perf_counter()
    output = await moderate_message(payload)
    process_seconds = time.perf_counter() - start
    print(f"Thời gian nạp model/khởi tạo: {load_seconds:.2f}s{'' if ready else ' (warmup lỗi, xem log)'}")
    print(f"Thời gian xử lý tin nhắn: {process_seconds:.2f}s")
    return output


if __name__ == "__main__":
    main()
