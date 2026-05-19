from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass


@dataclass
class RunSpec:
    command: list[str]
    runtime: dict[str, object]


def build_run_spec(command: list[str], budget: dict, cwd: str | None = None) -> RunSpec:
    if not budget:
        return RunSpec(command=command, runtime={"backend": "subprocess", "budgets_enforced": False})
    if os.environ.get("ZEN_DISABLE_SYSTEMD") == "1":
        return RunSpec(
            command=command,
            runtime={
                "backend": "subprocess",
                "budgets_enforced": False,
                "fallback_reason": "systemd disabled by ZEN_DISABLE_SYSTEMD",
            },
        )
    if not shutil.which("systemd-run"):
        return RunSpec(
            command=command,
            runtime={
                "backend": "subprocess",
                "budgets_enforced": False,
                "fallback_reason": "systemd-run unavailable",
            },
        )
    properties = systemd_properties_for_budget(budget)
    if not properties:
        return RunSpec(command=command, runtime={"backend": "subprocess", "budgets_enforced": False})
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
    return subprocess.Popen(spec.command, start_new_session=True)


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
