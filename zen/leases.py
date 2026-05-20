from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .config import state_dir
from .models import Lease
from .util import process_identity


def lease_path() -> Path:
    return state_dir() / "leases.json"


def lock_path() -> Path:
    return state_dir() / "leases.lock"


def load_leases() -> list[Lease]:
    with _locked(exclusive=False):
        return _read_leases_unlocked()


def _read_leases_unlocked() -> list[Lease]:
    path = lease_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except OSError:
        return []
    except json.JSONDecodeError as exc:
        corrupt_path = _quarantine_corrupt_lease_file(path)
        print(f"warning: quarantined corrupt Zen lease store {path} -> {corrupt_path}: {exc}", file=sys.stderr)
        return []
    leases: list[Lease] = []
    for item in data:
        try:
            leases.append(Lease(**item))
        except TypeError:
            continue
    return leases


def save_leases(leases: list[Lease]) -> None:
    with _locked(exclusive=True):
        _write_leases_unlocked(leases)


def _write_leases_unlocked(leases: list[Lease]) -> None:
    path = lease_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([lease.__dict__ for lease in leases], indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".leases.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


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
    runtime: dict | None = None,
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
        identity=process_identity(pid),
        runtime=runtime or {},
    )
    with _locked(exclusive=True):
        leases = _read_leases_unlocked()
        leases.append(lease)
        _write_leases_unlocked(leases)
    return lease


def prune_dead_leases() -> list[Lease]:
    live: list[Lease] = []
    with _locked(exclusive=True):
        leases = _read_leases_unlocked()
        for lease in leases:
            try:
                os.kill(lease.pid, 0)
                live.append(lease)
            except ProcessLookupError:
                continue
            except PermissionError:
                live.append(lease)
        _write_leases_unlocked(live)
    return live


def _quarantine_corrupt_lease_file(path: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}.corrupt-{stamp}")
    counter = 0
    while candidate.exists():
        counter += 1
        candidate = path.with_name(f"{path.name}.corrupt-{stamp}-{counter}")
    try:
        os.replace(path, candidate)
    except OSError:
        return path
    return candidate


@contextmanager
def _locked(exclusive: bool):
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
