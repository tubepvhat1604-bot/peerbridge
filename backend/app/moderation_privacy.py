"""Operator retention/erasure utility; preserves decisions but removes textual payloads."""
import argparse
from datetime import UTC, datetime

from .db import database


def erase_before(cutoff: str) -> int:
    parsed = datetime.fromisoformat(cutoff)
    if parsed.tzinfo is None:
        raise ValueError("Retention cutoff must include timezone")
    cutoff = parsed.astimezone(UTC).isoformat()
    with database() as connection:
        ids = [row[0] for row in connection.execute("SELECT id FROM chat_messages WHERE created_at < ?", (cutoff,))]
        for message_id in ids:
            connection.execute("UPDATE chat_messages SET content = '[REMOVED]' WHERE id = ?", (message_id,))
            connection.execute("UPDATE moderation_events SET reason = 'Retained decision; content removed', guidance = NULL, context = '{}' WHERE message_id = ?", (message_id,))
            connection.execute("UPDATE instructor_reviews SET notes = '' WHERE moderation_event_id IN (SELECT id FROM moderation_events WHERE message_id = ?)", (message_id,))
    return len(ids)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, help="Explicit ISO-8601 cutoff with timezone")
    args = parser.parse_args()
    print(f"Erased text for {erase_before(args.before)} messages")


if __name__ == "__main__":
    main()
