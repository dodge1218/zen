from __future__ import annotations

import os
from pathlib import Path

from .config import Policy
from .models import DockerContainer, MemoryInfo, ProcessInfo
from .util import parse_stat, read_text, run_cmd


def read_memory() -> MemoryInfo:
    fields: dict[str, int] = {}
    for line in read_text(Path("/proc/meminfo")).splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if parts and parts[0].isdigit():
            fields[key] = int(parts[0])
    return MemoryInfo(
        mem_total_kb=fields.get("MemTotal", 0),
        mem_available_kb=fields.get("MemAvailable", 0),
        swap_total_kb=fields.get("SwapTotal", 0),
        swap_free_kb=fields.get("SwapFree", 0),
    )


def load_average() -> tuple[float, float, float]:
    try:
        return os.getloadavg()
    except OSError:
        return (0.0, 0.0, 0.0)


def scan_processes(policy: Policy) -> dict[int, ProcessInfo]:
    raw: dict[int, ProcessInfo] = {}
    total_jiffies_1 = _total_jiffies()
    proc_times_1 = _proc_times()
    # A tiny sampling window keeps status fast while still finding hot processes.
    import time

    time.sleep(0.15)
    total_jiffies_2 = _total_jiffies()
    proc_times_2 = _proc_times()
    total_delta = max(1, total_jiffies_2 - total_jiffies_1)

    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        stat = read_text(entry / "stat")
        if not stat:
            continue
        try:
            name, state, ppid, pgid, sid = parse_stat(stat)
        except ValueError:
            continue
        status = _status_fields(entry / "status")
        cmdline = _cmdline(entry / "cmdline") or name
        cwd = _cwd(entry)
        cpu_pct = 0.0
        if pid in proc_times_1 and pid in proc_times_2:
            cpu_pct = (proc_times_2[pid] - proc_times_1[pid]) / total_delta * (os.cpu_count() or 1) * 100
        info = ProcessInfo(
            pid=pid,
            ppid=ppid,
            pgid=pgid,
            sid=sid,
            name=name,
            state=state,
            rss_kb=status.get("VmRSS", 0),
            swap_kb=status.get("VmSwap", 0),
            cpu_pct=cpu_pct,
            cmdline=cmdline,
            cwd=cwd,
        )
        tag_process(info, policy)
        raw[pid] = info
    for proc in raw.values():
        parent = raw.get(proc.ppid)
        if parent:
            parent.children.append(proc.pid)
    _protect_current_invocation(raw)
    return raw


def tag_process(proc: ProcessInfo, policy: Policy) -> None:
    lower_cmd = proc.cmdline.lower()
    lower_name = proc.name.lower()
    if lower_name in {n.lower() for n in policy.protect_names}:
        proc.tags.add("protect")
    if any(s.lower() in lower_cmd for s in policy.protect_cmd_substrings):
        proc.tags.add("protect")
    if any(s.lower() in lower_cmd for s in policy.ephemeral_cmd_substrings):
        proc.tags.add("ephemeral")
    if proc.cwd and any(proc.cwd.startswith(prefix) for prefix in policy.ephemeral_cwd_prefixes):
        proc.tags.add("ephemeral")
    if "docker" in lower_cmd or "kind " in lower_cmd or "kube" in lower_cmd:
        proc.tags.add("container-work")
    if any(part in lower_cmd for part in ("codex", "claude", "cursor", "cline", "aider", "openai")):
        proc.tags.add("agent")


def _protect_current_invocation(processes: dict[int, ProcessInfo]) -> None:
    current_pid = os.getpid()
    current_pgid = os.getpgid(current_pid)
    for proc in processes.values():
        if proc.pid == current_pid or proc.pgid == current_pgid:
            proc.tags.update({"protect", "self"})
    pid = current_pid
    seen: set[int] = set()
    while pid in processes and pid not in seen:
        seen.add(pid)
        proc = processes[pid]
        proc.tags.update({"protect", "self"})
        pid = proc.ppid


def scan_docker(policy: Policy) -> list[DockerContainer]:
    result = run_cmd(
        ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}"],
        timeout=5,
    )
    if result.returncode != 0:
        return []
    containers: list[DockerContainer] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        containers.append(DockerContainer(parts[0], parts[1], parts[2], parts[3]))
    return containers


def _status_fields(path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in read_text(path).splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if parts and parts[0].isdigit():
            out[key] = int(parts[0])
    return out


def _cmdline(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data.replace(b"\x00", b" ").decode(errors="replace").strip()


def _cwd(entry: Path) -> str | None:
    try:
        return os.readlink(entry / "cwd")
    except OSError:
        return None


def _proc_times() -> dict[int, int]:
    out: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        stat = read_text(entry / "stat")
        if not stat:
            continue
        left = stat.rfind(")")
        if left == -1:
            continue
        fields = stat[left + 2 :].split()
        try:
            out[int(entry.name)] = int(fields[11]) + int(fields[12])
        except (IndexError, ValueError):
            continue
    return out


def _total_jiffies() -> int:
    line = read_text(Path("/proc/stat")).splitlines()[0]
    return sum(int(part) for part in line.split()[1:] if part.isdigit())
