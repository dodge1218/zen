from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Iterable


def fmt_kb(kb: int) -> str:
    value = float(kb)
    units = ["KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def run_cmd(args: list[str], timeout: int = 5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


def parse_ttl(value: str | None) -> int | None:
    if not value:
        return None
    value = value.strip().lower()
    unit = value[-1]
    number = value[:-1] if unit.isalpha() else value
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit, 1)
    return int(float(number) * mult)


def kill_process_tree(root: int, sig: int = signal.SIGTERM) -> None:
    for child in child_pids(root):
        kill_process_tree(child, sig=sig)
    try:
        os.kill(root, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass


def child_pids(pid: int) -> list[int]:
    children: list[int] = []
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        stat = read_text(entry / "stat")
        if not stat:
            continue
        try:
            _, _, ppid = parse_stat(stat)[:3]
        except ValueError:
            continue
        if ppid == pid:
            children.append(int(entry.name))
    return children


def parse_stat(stat: str) -> tuple[str, str, int, int, int]:
    name, state, ppid, pgid, sid, _ = parse_stat_with_start_time(stat)
    return name, state, ppid, pgid, sid


def parse_stat_with_start_time(stat: str) -> tuple[str, str, int, int, int, int | None]:
    left = stat.rfind(")")
    if left == -1:
        raise ValueError("bad stat")
    name = stat[stat.find("(") + 1 : left]
    fields = stat[left + 2 :].split()
    state = fields[0]
    ppid = int(fields[1])
    pgid = int(fields[2])
    sid = int(fields[3])
    try:
        start_time = int(fields[19])
    except (IndexError, ValueError):
        start_time = None
    return name, state, ppid, pgid, sid, start_time


def process_identity(pid: int) -> dict[str, int | str | None]:
    stat = read_text(Path(f"/proc/{pid}/stat"))
    if not stat:
        return {}
    try:
        name, _, _, pgid, sid, start_time = parse_stat_with_start_time(stat)
    except (IndexError, ValueError):
        return {}
    uid = None
    for line in read_text(Path(f"/proc/{pid}/status")).splitlines():
        if line.startswith("Uid:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                uid = int(parts[1])
            break
    return {
        "pid": pid,
        "uid": uid,
        "pgid": pgid,
        "sid": sid,
        "start_time_ticks": start_time,
        "name": name,
    }


def identity_matches(pid: int, expected: dict | None) -> bool:
    if not expected:
        return False
    current = process_identity(pid)
    if not current:
        return False
    required_keys = ("uid", "pgid", "sid", "start_time_ticks")
    for key in required_keys:
        if expected.get(key) is None or current.get(key) != expected.get(key):
            return False
    return True


def kill_process_group(pgid: int, sig: int = signal.SIGTERM) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass


def unique_ints(values: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
