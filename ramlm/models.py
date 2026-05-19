from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MemoryInfo:
    mem_total_kb: int = 0
    mem_available_kb: int = 0
    swap_total_kb: int = 0
    swap_free_kb: int = 0

    @property
    def swap_used_kb(self) -> int:
        return max(0, self.swap_total_kb - self.swap_free_kb)

    @property
    def swap_used_pct(self) -> float:
        if self.swap_total_kb <= 0:
            return 0.0
        return self.swap_used_kb / self.swap_total_kb * 100

    @property
    def mem_available_gb(self) -> float:
        return self.mem_available_kb / 1024 / 1024


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    pgid: int
    sid: int
    name: str
    state: str
    rss_kb: int
    swap_kb: int
    cpu_pct: float
    cmdline: str
    cwd: str | None = None
    children: list[int] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)

    @property
    def protected(self) -> bool:
        return "protect" in self.tags


@dataclass
class DockerContainer:
    container_id: str
    name: str
    image: str
    status: str


@dataclass
class Action:
    kind: str
    target: str
    reason: str
    command: list[str] | None = None
    pids: list[int] = field(default_factory=list)
    risk: str = "safe"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Lease:
    id: str
    klass: str
    command: list[str]
    pid: int
    pgid: int
    started_at: float
    ttl_seconds: int | None
    cwd: str
    cleanup: str | None = None
    allow_kill: bool = False
    budget: dict[str, Any] = field(default_factory=dict)

    @property
    def expired_at(self) -> float | None:
        if self.ttl_seconds is None:
            return None
        return self.started_at + self.ttl_seconds


StatePath = Path
