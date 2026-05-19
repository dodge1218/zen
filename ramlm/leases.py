from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from .config import state_dir
from .models import Lease


def lease_path() -> Path:
    return state_dir() / "leases.json"


def load_leases() -> list[Lease]:
    path = lease_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    leases: list[Lease] = []
    for item in data:
        try:
            leases.append(Lease(**item))
        except TypeError:
            continue
    return leases


def save_leases(leases: list[Lease]) -> None:
    lease_path().write_text(json.dumps([lease.__dict__ for lease in leases], indent=2) + "\n")


def create_lease(
    klass: str,
    command: list[str],
    pid: int,
    pgid: int,
    ttl_seconds: int | None,
    cleanup: str | None,
    cwd: str | None = None,
    allow_kill: bool = False,
    budget: dict | None = None,
) -> Lease:
    lease = Lease(
        id=str(uuid.uuid4()),
        klass=klass,
        command=command,
        pid=pid,
        pgid=pgid,
        started_at=time.time(),
        ttl_seconds=ttl_seconds,
        cwd=cwd or os.getcwd(),
        cleanup=cleanup,
        allow_kill=allow_kill,
        budget=budget or {},
    )
    leases = load_leases()
    leases.append(lease)
    save_leases(leases)
    return lease


def prune_dead_leases() -> list[Lease]:
    live: list[Lease] = []
    for lease in load_leases():
        try:
            os.kill(lease.pid, 0)
            live.append(lease)
        except ProcessLookupError:
            continue
        except PermissionError:
            live.append(lease)
    save_leases(live)
    return live
