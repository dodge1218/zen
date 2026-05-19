from __future__ import annotations

from dataclasses import dataclass

from .models import Action, DockerContainer, MemoryInfo, ProcessInfo


@dataclass
class ProcessBucket:
    name: str
    count: int = 0
    cpu_pct: float = 0.0
    rss_kb: int = 0
    swap_kb: int = 0


@dataclass
class Recommendation:
    level: str
    message: str


@dataclass
class CleanAudit:
    pressure: str
    load: tuple[float, float, float]
    memory: MemoryInfo
    buckets: list[ProcessBucket]
    recommendations: list[Recommendation]
    top_cpu: list[ProcessInfo]
    top_memory: list[ProcessInfo]
    actions: list[Action]
    containers: list[DockerContainer]

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "pressure": self.pressure,
            "load": {
                "1m": self.load[0],
                "5m": self.load[1],
                "15m": self.load[2],
            },
            "memory": {
                "mem_total_kb": self.memory.mem_total_kb,
                "mem_available_kb": self.memory.mem_available_kb,
                "swap_total_kb": self.memory.swap_total_kb,
                "swap_used_kb": self.memory.swap_used_kb,
                "swap_used_pct": self.memory.swap_used_pct,
            },
            "workloads": [bucket.__dict__ for bucket in self.buckets],
            "recommendations": [item.__dict__ for item in self.recommendations],
            "top_cpu": [_process_dict(proc) for proc in self.top_cpu],
            "top_memory": [_process_dict(proc) for proc in self.top_memory],
            "actions": [_action_dict(action) for action in self.actions],
            "containers": [container.__dict__ for container in self.containers],
        }


BUCKET_ORDER = (
    "agents",
    "browsers",
    "docker/kube",
    "terminals",
    "desktop",
    "build/tools",
    "kernel/system",
    "services",
    "other",
)


def summarize_processes(processes: list[ProcessInfo]) -> list[ProcessBucket]:
    buckets = {name: ProcessBucket(name) for name in BUCKET_ORDER}
    for proc in processes:
        bucket = buckets[_bucket_name(proc)]
        bucket.count += 1
        bucket.cpu_pct += proc.cpu_pct
        bucket.rss_kb += proc.rss_kb
        bucket.swap_kb += proc.swap_kb
    return sorted(buckets.values(), key=lambda b: (b.cpu_pct, b.rss_kb), reverse=True)


def recommendations(
    memory: MemoryInfo,
    buckets: list[ProcessBucket],
    actions: list[Action],
    containers: list[DockerContainer],
) -> list[Recommendation]:
    out: list[Recommendation] = []
    by_name = {bucket.name: bucket for bucket in buckets}
    if memory.swap_used_pct >= 50:
        out.append(Recommendation("watch", "Swap is high; expect lag even with free RAM. A swap refresh may help after load drops."))
    if by_name.get("agents") and by_name["agents"].cpu_pct >= 100:
        out.append(Recommendation("review", "Agent CPU is the top pressure source; inspect active Codex/Claude/OpenClaw runs before stopping anything."))
    if by_name.get("browsers") and by_name["browsers"].rss_kb >= 2 * 1024 * 1024:
        out.append(Recommendation("protect", "Browsers are large but protected; Zen will not close tabs or browser processes."))
    if any(action.kind == "docker-stop" for action in actions):
        out.append(Recommendation("optional", "A matching Docker/PoC container is present; Zen will only stop it with `--allow-docker`."))
    if any(action.kind == "review" for action in actions):
        out.append(Recommendation("review", "Some work is suspicious or expired but not owned by Zen; it is report-only."))
    if any(action.kind == "kill-tree" and action.meta.get("owned_by_zen") for action in actions):
        out.append(Recommendation("safe", "Expired Zen-owned leases can be cleaned with `zen clean --execute`."))
    if containers and by_name.get("docker/kube") and by_name["docker/kube"].cpu_pct >= 20:
        out.append(Recommendation("review", "Docker/Kubernetes is contributing CPU; check `zen docker` before allowing container cleanup."))
    if not out:
        out.append(Recommendation("ok", "No obvious unsafe pressure source found."))
    return out[:5]


def _process_dict(proc: ProcessInfo) -> dict:
    return {
        "pid": proc.pid,
        "ppid": proc.ppid,
        "pgid": proc.pgid,
        "name": proc.name,
        "state": proc.state,
        "rss_kb": proc.rss_kb,
        "swap_kb": proc.swap_kb,
        "cpu_pct": proc.cpu_pct,
        "cmdline": proc.cmdline,
        "cwd": proc.cwd,
        "tags": sorted(proc.tags),
        "protected": proc.protected,
    }


def _action_dict(action: Action) -> dict:
    return {
        "kind": action.kind,
        "target": action.target,
        "reason": action.reason,
        "command": action.command,
        "pids": action.pids,
        "risk": action.risk,
        "meta": action.meta,
    }


def _bucket_name(proc: ProcessInfo) -> str:
    cmd = proc.cmdline.lower()
    name = proc.name.lower()
    tags = proc.tags
    if "agent" in tags or any(part in cmd for part in ("codex", "claude", "cursor", "cline", "aider", "openai")):
        return "agents"
    if name in {"brave", "chrome", "chromium", "firefox"} or any(part in cmd for part in ("brave", "chrome", "chromium", "firefox")):
        return "browsers"
    if "container-work" in tags or any(part in cmd for part in ("docker", "containerd", "kube", "kind ", "etcd")):
        return "docker/kube"
    if any(part in name for part in ("terminal", "xterm", "konsole", "tilix")):
        return "terminals"
    if name in {"cinnamon", "xorg", "gnome-shell", "lightdm", "pipewire", "pulseaudio"}:
        return "desktop"
    if any(part in cmd for part in ("pnpm", "npm", "yarn", "pytest", "vitest", "tsc", "cargo", "go test", "forge test", "git ")):
        return "build/tools"
    if name in {"git", "rg", "tectonic", "make", "cmake", "ninja"}:
        return "build/tools"
    if _is_kernel_or_system(name):
        return "kernel/system"
    if name in {"python", "python3", "node", "nanobot", "ollama"}:
        return "services"
    return "other"


def _is_kernel_or_system(name: str) -> bool:
    if name.startswith(("kworker", "ksoftirqd", "kswapd", "rcu_", "migration", "idle_inject", "cpuhp")):
        return True
    return name in {
        "systemd",
        "dbus-daemon",
        "jfscommit",
        "jfsiod",
        "irqbalance",
        "networkmanager",
        "wpa_supplicant",
        "cron",
        "rsyslogd",
    }
