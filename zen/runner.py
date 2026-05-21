from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunSpec:
    command: list[str]
    runtime: dict[str, object]


def build_run_spec(command: list[str], budget: dict, cwd: str | None = None) -> RunSpec:
    if not budget:
        return RunSpec(command=command, runtime={"backend": "subprocess", "budgets_enforced": False})
    properties = systemd_properties_for_budget(budget)
    if not properties:
        return RunSpec(command=command, runtime={"backend": "subprocess", "budgets_enforced": False})
    if os.environ.get("ZEN_DISABLE_SYSTEMD") == "1":
        return _cgroup_or_subprocess(command, properties, "systemd disabled by ZEN_DISABLE_SYSTEMD")
    if not shutil.which("systemd-run"):
        return _cgroup_or_subprocess(command, properties, "systemd-run unavailable")
    unit = f"zen-{uuid.uuid4().hex[:12]}.scope"
    wrapped = [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        "--unit",
        unit,
    ]
    if cwd:
        wrapped.extend(["--working-directory", cwd])
    else:
        wrapped.append("--same-dir")
    for key, value in properties.items():
        wrapped.extend(["--property", f"{key}={value}"])
    wrapped.extend(["--", *command])
    return RunSpec(
        command=wrapped,
        runtime={
            "backend": "systemd-run",
            "budgets_enforced": True,
            "unit": unit,
            "properties": properties,
        },
    )


def popen_run_spec(spec: RunSpec) -> subprocess.Popen:
    proc = subprocess.Popen(spec.command, start_new_session=True)
    cgroup_path = spec.runtime.get("cgroup_path")
    if isinstance(cgroup_path, str):
        try:
            Path(cgroup_path, "cgroup.procs").write_text(f"{proc.pid}\n")
        except OSError as exc:
            spec.runtime["budgets_enforced"] = False
            spec.runtime["fallback_reason"] = f"could not attach process to cgroup: {exc}"
    return proc


def systemd_properties_for_budget(budget: dict) -> dict[str, str]:
    properties: dict[str, str] = {}
    if budget.get("mem"):
        properties["MemoryMax"] = normalize_memory_max(str(budget["mem"]))
    if budget.get("cpu") is not None:
        cpu = float(budget["cpu"])
        if cpu <= 0:
            raise ValueError("--cpu must be greater than 0")
        properties["CPUQuota"] = f"{int(cpu * 100)}%"
    if budget.get("pids") is not None:
        pids = int(budget["pids"])
        if pids <= 0:
            raise ValueError("--pids must be greater than 0")
        properties["TasksMax"] = str(pids)
    return properties


def cgroup_properties_for_budget(budget: dict) -> dict[str, str]:
    properties: dict[str, str] = {}
    if budget.get("mem"):
        properties["memory.max"] = normalize_memory_max(str(budget["mem"]))
    if budget.get("cpu") is not None:
        cpu = float(budget["cpu"])
        if cpu <= 0:
            raise ValueError("--cpu must be greater than 0")
        period = 100_000
        properties["cpu.max"] = f"{max(1, int(cpu * period))} {period}"
    if budget.get("pids") is not None:
        pids = int(budget["pids"])
        if pids <= 0:
            raise ValueError("--pids must be greater than 0")
        properties["pids.max"] = str(pids)
    return properties


def prepare_cgroup(properties: dict[str, str], root: Path | None = None) -> tuple[Path | None, str | None]:
    if os.environ.get("ZEN_DISABLE_CGROUP") == "1":
        return None, "cgroup disabled by ZEN_DISABLE_CGROUP"
    base = root or cgroup_base()
    if not base:
        return None, "cgroup v2 mount not found"
    if not (base / "cgroup.controllers").exists():
        return None, "cgroup v2 controllers unavailable"
    path = base / "zen" / uuid.uuid4().hex[:12]
    try:
        path.mkdir(parents=True, exist_ok=False)
        for key, value in properties.items():
            (path / key).write_text(f"{value}\n")
    except OSError as exc:
        return None, f"cgroup not writable: {exc}"
    return path, None


def cgroup_base() -> Path | None:
    override = os.environ.get("ZEN_CGROUP_ROOT")
    if override:
        return Path(override)
    root = Path("/sys/fs/cgroup")
    relative = _current_cgroup_v2_path()
    if relative is None:
        return None
    return root / relative.relative_to("/")


def _cgroup_or_subprocess(command: list[str], systemd_properties: dict[str, str], reason: str) -> RunSpec:
    cgroup_properties = _systemd_to_cgroup_properties(systemd_properties)
    cgroup_path, cgroup_error = prepare_cgroup(cgroup_properties)
    if cgroup_path:
        return RunSpec(
            command=command,
            runtime={
                "backend": "cgroup-v2",
                "budgets_enforced": True,
                "cgroup_path": str(cgroup_path),
                "properties": cgroup_properties,
                "fallback_reason": reason,
            },
        )
    return RunSpec(
        command=command,
        runtime={
            "backend": "subprocess",
            "budgets_enforced": False,
            "fallback_reason": f"{reason}; {cgroup_error}",
        },
    )


def _systemd_to_cgroup_properties(properties: dict[str, str]) -> dict[str, str]:
    cgroup: dict[str, str] = {}
    if "MemoryMax" in properties:
        cgroup["memory.max"] = properties["MemoryMax"]
    if "CPUQuota" in properties:
        percent = float(properties["CPUQuota"].rstrip("%"))
        period = 100_000
        cgroup["cpu.max"] = f"{max(1, int(percent / 100 * period))} {period}"
    if "TasksMax" in properties:
        cgroup["pids.max"] = properties["TasksMax"]
    return cgroup


def _current_cgroup_v2_path() -> Path | None:
    try:
        lines = Path("/proc/self/cgroup").read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and parts[1] == "":
            return Path(parts[2])
    return None


def normalize_memory_max(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("--mem cannot be empty")
    suffix = raw[-1].lower()
    number = raw[:-1] if suffix.isalpha() else raw
    try:
        parsed = float(number)
    except ValueError as exc:
        raise ValueError("--mem must be a number with optional k/m/g/t suffix") from exc
    if parsed <= 0:
        raise ValueError("--mem must be greater than 0")
    multiplier = {
        "k": 1024,
        "m": 1024**2,
        "g": 1024**3,
        "t": 1024**4,
    }.get(suffix, 1)
    if suffix.isalpha() and suffix not in {"k", "m", "g", "t"}:
        raise ValueError("--mem suffix must be one of k, m, g, or t")
    return str(int(parsed * multiplier))
