from __future__ import annotations

import time
from typing import Any

from .audit import ProcessBucket
from .models import MemoryInfo, ProcessInfo


def build_pressure_snapshot(
    pressure: str,
    memory: MemoryInfo,
    load: tuple[float, float, float],
    buckets: list[ProcessBucket],
    processes: list[ProcessInfo],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ts": time.time(),
        "pressure": pressure,
        "load": {
            "1m": load[0],
            "5m": load[1],
            "15m": load[2],
        },
        "memory": {
            "mem_total_kb": memory.mem_total_kb,
            "mem_available_kb": memory.mem_available_kb,
            "swap_total_kb": memory.swap_total_kb,
            "swap_used_kb": memory.swap_used_kb,
            "swap_used_pct": memory.swap_used_pct,
        },
        "workloads": [bucket.__dict__ for bucket in buckets],
        "top_swap": [_process_summary(proc) for proc in _top_processes(processes, "swap_kb")],
        "top_rss": [_process_summary(proc) for proc in _top_processes(processes, "rss_kb")],
        "top_cpu": [_process_summary(proc) for proc in _top_processes(processes, "cpu_pct")],
    }


def history_delta(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    previous_memory = previous.get("memory", {})
    current_memory = current.get("memory", {})
    previous_workloads = _workload_map(previous)
    current_workloads = _workload_map(current)
    names = sorted(set(previous_workloads) | set(current_workloads))
    return {
        "seconds": current.get("ts", 0) - previous.get("ts", 0),
        "swap_used_kb": current_memory.get("swap_used_kb", 0) - previous_memory.get("swap_used_kb", 0),
        "mem_available_kb": current_memory.get("mem_available_kb", 0) - previous_memory.get("mem_available_kb", 0),
        "workloads": [
            {
                "name": name,
                "cpu_pct": current_workloads.get(name, {}).get("cpu_pct", 0)
                - previous_workloads.get(name, {}).get("cpu_pct", 0),
                "rss_kb": current_workloads.get(name, {}).get("rss_kb", 0)
                - previous_workloads.get(name, {}).get("rss_kb", 0),
                "swap_kb": current_workloads.get(name, {}).get("swap_kb", 0)
                - previous_workloads.get(name, {}).get("swap_kb", 0),
                "count": current_workloads.get(name, {}).get("count", 0)
                - previous_workloads.get(name, {}).get("count", 0),
            }
            for name in names
        ],
    }


def _top_processes(processes: list[ProcessInfo], field: str, limit: int = 5) -> list[ProcessInfo]:
    return sorted(processes, key=lambda proc: getattr(proc, field), reverse=True)[:limit]


def _process_summary(proc: ProcessInfo) -> dict[str, Any]:
    return {
        "pid": proc.pid,
        "name": proc.name,
        "rss_kb": proc.rss_kb,
        "swap_kb": proc.swap_kb,
        "cpu_pct": proc.cpu_pct,
        "tags": sorted(proc.tags),
        "protected": proc.protected,
    }


def _workload_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    workloads = snapshot.get("workloads", [])
    if not isinstance(workloads, list):
        return {}
    return {
        item["name"]: item
        for item in workloads
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
