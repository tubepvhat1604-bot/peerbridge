"""Create immutable run artifacts; existing evidence and ratings are never replaced."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def new_run_path(parent: Path, label: str) -> Path:
    return parent / f"{label}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:12]}"


def claim_run(output: Path) -> None:
    # mkdir is the atomic claim: even an empty existing directory belongs to another run.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)


def write_text(path: Path, value: str) -> None:
    # Exclusive creation also protects individual artifacts in a newly claimed directory.
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(value)


def write_json(path: Path, value) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
