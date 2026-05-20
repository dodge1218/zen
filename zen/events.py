from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import state_dir

DEFAULT_MAX_EVENT_BYTES = 5 * 1024 * 1024
DEFAULT_KEEP_ROTATED = 3


def event_path() -> Path:
    return state_dir() / "events.jsonl"


def log_event(event_kind: str, max_bytes: int = DEFAULT_MAX_EVENT_BYTES, keep: int = DEFAULT_KEEP_ROTATED, **fields: Any) -> None:
    event = {
        "ts": time.time(),
        "kind": event_kind,
        **fields,
    }
    path = event_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(path, max_bytes=max_bytes, keep=keep)
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


def _rotate_if_needed(path: Path, max_bytes: int, keep: int) -> None:
    if max_bytes <= 0 or keep <= 0:
        return
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
    except OSError:
        return
    oldest = path.with_name(f"{path.name}.{keep}")
    try:
        if oldest.exists():
            oldest.unlink()
        for index in range(keep - 1, 0, -1):
            src = path.with_name(f"{path.name}.{index}")
            if src.exists():
                src.replace(path.with_name(f"{path.name}.{index + 1}"))
        path.replace(path.with_name(f"{path.name}.1"))
    except OSError:
        return
