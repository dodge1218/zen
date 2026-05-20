from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import state_dir


def event_path() -> Path:
    return state_dir() / "events.jsonl"


def log_event(event_kind: str, **fields: Any) -> None:
    event = {
        "ts": time.time(),
        "kind": event_kind,
        **fields,
    }
    path = event_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def read_events(limit: int | None = None) -> list[dict[str, Any]]:
    path = event_path()
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    selected = lines[-limit:] if limit is not None and limit >= 0 else lines
    for line in selected:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events
