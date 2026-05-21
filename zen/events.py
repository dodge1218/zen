from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import state_dir

DEFAULT_MAX_EVENT_BYTES = 5 * 1024 * 1024
DEFAULT_KEEP_ROTATED = 3
DEFAULT_MAX_HISTORY_BYTES = 10 * 1024 * 1024


def event_path() -> Path:
    return state_dir() / "events.jsonl"


def history_path() -> Path:
    return state_dir() / "history.jsonl"


def log_event(
    event_kind: str,
    max_bytes: int = DEFAULT_MAX_EVENT_BYTES,
    keep: int = DEFAULT_KEEP_ROTATED,
    **fields: Any,
) -> None:
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


def log_history(
    snapshot: dict[str, Any],
    max_bytes: int = DEFAULT_MAX_HISTORY_BYTES,
    keep: int = DEFAULT_KEEP_ROTATED,
) -> None:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(path, max_bytes=max_bytes, keep=keep)
    with path.open("a") as handle:
        handle.write(json.dumps(snapshot, sort_keys=True) + "\n")


def read_events(limit: int | None = None) -> list[dict[str, Any]]:
    path = event_path()
    return _read_jsonl(path, limit=limit)


def read_history(limit: int | None = None) -> list[dict[str, Any]]:
    return _read_jsonl(history_path(), limit=limit)


def _read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    if limit == 0:
        selected = []
    elif limit is not None and limit > 0:
        selected = lines[-limit:]
    else:
        selected = lines
    for line in selected:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


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
