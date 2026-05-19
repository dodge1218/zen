from __future__ import annotations

import time

from .config import Policy
from .leases import prune_dead_leases
from .models import Action, DockerContainer, MemoryInfo, ProcessInfo


def pressure_level(memory: MemoryInfo, load1: float, policy: Policy) -> str:
    t = policy.thresholds
    if memory.swap_used_pct >= t.black_swap_pct or memory.mem_available_gb <= 1:
        return "black"
    if memory.swap_used_pct >= t.red_swap_pct or memory.mem_available_gb <= t.red_available_gb or load1 >= t.red_load_1m:
        return "red"
    if memory.swap_used_pct >= t.yellow_swap_pct or memory.mem_available_gb <= t.yellow_available_gb or load1 >= t.yellow_load_1m:
        return "yellow"
    return "green"


def plan_actions(
    processes: dict[int, ProcessInfo],
    containers: list[DockerContainer],
    policy: Policy,
    tier: str = "normal",
) -> list[Action]:
    actions: list[Action] = []
    actions.extend(_expired_lease_actions(processes))
    actions.extend(_ephemeral_process_actions(processes, tier=tier))
    actions.extend(_docker_actions(containers, policy, tier=tier))
    return _dedupe_actions(actions)


def _expired_lease_actions(processes: dict[int, ProcessInfo]) -> list[Action]:
    actions: list[Action] = []
    now = time.time()
    for lease in prune_dead_leases():
        if lease.expired_at and lease.expired_at <= now:
            proc = processes.get(lease.pid)
            if proc and proc.protected:
                continue
            if lease.allow_kill:
                if not proc or not _lease_identity_matches(lease.identity, proc):
                    actions.append(
                        Action(
                            kind="review",
                            target=f"lease:{lease.id}",
                            reason=f"expired {lease.klass} lease has stale or unverifiable process identity",
                            pids=[lease.pid],
                            risk="blocked",
                            meta={
                                "pgid": lease.pgid,
                                "command": " ".join(lease.command),
                                "lease_id": lease.id,
                                "budget": lease.budget,
                            },
                        )
                    )
                    continue
                actions.append(
                    Action(
                        kind="kill-tree",
                        target=f"lease:{lease.id}",
                        reason=f"expired {lease.klass} lease",
                        pids=[lease.pid],
                        risk="safe",
                        meta={
                            "pgid": lease.pgid,
                            "command": " ".join(lease.command),
                            "owned_by_zen": True,
                            "lease_id": lease.id,
                            "budget": lease.budget,
                            "identity": lease.identity,
                            "runtime": lease.runtime,
                        },
                    )
                )
            else:
                actions.append(
                    Action(
                        kind="review",
                        target=f"lease:{lease.id}",
                        reason=f"expired {lease.klass} lease without kill permission",
                        pids=[lease.pid],
                        risk="blocked",
                        meta={"pgid": lease.pgid, "command": " ".join(lease.command), "budget": lease.budget},
                    )
                )
    return actions


def _lease_identity_matches(identity: dict, proc: ProcessInfo) -> bool:
    if not identity:
        return False
    checks = {
        "uid": proc.uid,
        "pgid": proc.pgid,
        "sid": proc.sid,
        "start_time_ticks": proc.start_time_ticks,
    }
    for key, value in checks.items():
        if identity.get(key) is None or identity.get(key) != value:
            return False
    return True


def _ephemeral_process_actions(processes: dict[int, ProcessInfo], tier: str) -> list[Action]:
    actions: list[Action] = []
    roots: list[ProcessInfo] = []
    for proc in processes.values():
        if "ephemeral" not in proc.tags or proc.protected:
            continue
        parent = processes.get(proc.ppid)
        if parent and "ephemeral" in parent.tags and not parent.protected:
            continue
        roots.append(proc)
    for proc in sorted(roots, key=lambda p: p.cpu_pct + p.rss_kb / 1024 / 1024, reverse=True):
        actions.append(
            Action(
                kind="review",
                target=f"pid:{proc.pid}",
                reason=f"possible ephemeral workload: {proc.name}",
                pids=[proc.pid],
                risk="review",
                meta={"cmdline": proc.cmdline[:300], "cwd": proc.cwd},
            )
        )
    return actions


def _docker_actions(containers: list[DockerContainer], policy: Policy, tier: str) -> list[Action]:
    actions: list[Action] = []
    for container in containers:
        if container.name in policy.keep_container_names:
            continue
        name_match = container.name in policy.poc_container_names
        image_match = any(container.image.startswith(prefix) for prefix in policy.poc_container_images)
        if name_match or (tier == "aggressive" and image_match):
            actions.append(
                Action(
                    kind="docker-stop",
                    target=container.name,
                    reason=f"PoC/ephemeral container: {container.image}",
                    command=["docker", "stop", container.name],
                    risk="safe" if name_match else "normal",
                )
            )
    return actions


def _dedupe_actions(actions: list[Action]) -> list[Action]:
    seen: set[tuple[str, str]] = set()
    out: list[Action] = []
    for action in actions:
        key = (action.kind, action.target)
        if key in seen:
            continue
        seen.add(key)
        out.append(action)
    return out
