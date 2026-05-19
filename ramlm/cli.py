from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from .actions import execute_action
from .audit import CleanAudit, recommendations, summarize_processes
from .config import default_policy, policy_path, write_default_policy
from .leases import create_lease, load_leases, prune_dead_leases
from .policy import plan_actions, pressure_level
from .scanner import load_average, read_memory, scan_docker, scan_processes
from .util import fmt_kb, parse_ttl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zen", description="Calm CPU/RAM audit and cleanup for AI workflows.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show current pressure summary.")
    doctor_p = sub.add_parser("doctor", help="Explain pressure and likely offenders.")
    doctor_p.add_argument("--tier", choices=["safe", "normal", "aggressive"], default="normal")

    ps_p = sub.add_parser("ps", help="Show hot processes.")
    ps_p.add_argument("--top", type=int, default=25)
    ps_p.add_argument("--sort", choices=["cpu", "rss", "swap"], default="cpu")

    sub.add_parser("swap", help="Show swap users.")
    sub.add_parser("docker", help="Show containers and Zen classification.")
    watch_p = sub.add_parser("watch", help="Continuously print pressure and cleanup plan.")
    watch_p.add_argument("--interval", type=float, default=5.0)
    watch_p.add_argument("--tier", choices=["safe", "normal", "aggressive"], default="normal")

    clean_p = sub.add_parser("clean", help="Audit CPU/RAM and plan cleanup. Dry-run unless --execute is passed.")
    clean_p.add_argument("--tier", choices=["safe", "normal", "aggressive"], default="normal")
    clean_p.add_argument("--execute", action="store_true")
    clean_p.add_argument("--force", action="store_true", help="Escalate process cleanup to SIGKILL after SIGTERM.")
    clean_p.add_argument("--allow-docker", action="store_true", help="Allow stopping matching Docker containers during --execute.")
    clean_p.add_argument("--json", action="store_true", help="Print audit as JSON. Refuses to combine with --execute.")

    run_p = sub.add_parser("run", help="Run a command under a Zen lease.")
    run_p.add_argument("--class", dest="klass", default="generic")
    run_p.add_argument("--ttl")
    run_p.add_argument("--cleanup")
    run_p.add_argument("--mem", help="Memory budget metadata, e.g. 2g or 750m. Advisory until cgroup enforcement lands.")
    run_p.add_argument("--cpu", type=float, help="CPU core budget metadata. Advisory until cgroup enforcement lands.")
    run_p.add_argument("--pids", type=int, help="Process-count budget metadata. Advisory until cgroup enforcement lands.")
    run_p.add_argument("--force", action="store_true", help="Start even when current pressure is red or black.")
    run_p.add_argument("command", nargs=argparse.REMAINDER)

    adopt_p = sub.add_parser("adopt", help="Attach a lease to an already-running process.")
    adopt_p.add_argument("pid", type=int)
    adopt_p.add_argument("--class", dest="klass", default="adopted")
    adopt_p.add_argument("--ttl")
    adopt_p.add_argument("--cleanup")
    adopt_p.add_argument("--mem", help="Memory budget metadata, e.g. 2g or 750m.")
    adopt_p.add_argument("--cpu", type=float, help="CPU core budget metadata.")
    adopt_p.add_argument("--pids", type=int, help="Process-count budget metadata.")
    adopt_p.add_argument("--allow-kill", action="store_true", help="Allow Zen to kill this adopted process after TTL.")

    config_p = sub.add_parser("config", help="Show or initialize Zen policy config.")
    config_p.add_argument("--init", action="store_true", help="Create ~/.config/zen/policy.json if missing.")
    config_p.add_argument("--overwrite", action="store_true", help="Overwrite config when used with --init.")
    config_p.add_argument("--path", type=Path, help="Use an alternate config path.")

    sub.add_parser("leases", help="List active leases.")

    args = parser.parse_args(argv)
    policy = default_policy()

    if args.cmd == "status":
        return cmd_status(policy)
    if args.cmd == "doctor":
        return cmd_doctor(policy, tier=args.tier)
    if args.cmd == "ps":
        return cmd_ps(policy, top=args.top, sort=args.sort)
    if args.cmd == "swap":
        return cmd_swap(policy)
    if args.cmd == "docker":
        return cmd_docker(policy)
    if args.cmd == "watch":
        return cmd_watch(policy, interval=args.interval, tier=args.tier)
    if args.cmd == "clean":
        return cmd_clean(policy, tier=args.tier, execute=args.execute, force=args.force, allow_docker=args.allow_docker, json_output=args.json)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "adopt":
        return cmd_adopt(policy, args)
    if args.cmd == "config":
        return cmd_config(args)
    if args.cmd == "leases":
        return cmd_leases()
    return 2


def cmd_status(policy) -> int:
    memory = read_memory()
    load1, load5, load15 = load_average()
    level = pressure_level(memory, load1, policy)
    print(f"pressure: {level}")
    print(f"load: {load1:.2f} {load5:.2f} {load15:.2f}")
    print(f"ram available: {fmt_kb(memory.mem_available_kb)} / {fmt_kb(memory.mem_total_kb)}")
    print(f"swap used: {fmt_kb(memory.swap_used_kb)} / {fmt_kb(memory.swap_total_kb)} ({memory.swap_used_pct:.1f}%)")
    print(f"leases: {len(prune_dead_leases())}")
    return 0


def cmd_doctor(policy, tier: str) -> int:
    cmd_status(policy)
    processes = scan_processes(policy)
    containers = scan_docker(policy)
    print()
    print("top cpu:")
    _print_processes(sorted(processes.values(), key=lambda p: p.cpu_pct, reverse=True)[:10])
    print()
    print("top swap:")
    _print_processes(sorted(processes.values(), key=lambda p: p.swap_kb, reverse=True)[:10], include_swap=True)
    print()
    print("planned actions:")
    actions = plan_actions(processes, containers, policy, tier=tier)
    if not actions:
        print("  none")
    for action in actions:
        print(f"  [{action.risk}] {action.kind} {action.target} - {action.reason}")
    return 0


def cmd_ps(policy, top: int, sort: str) -> int:
    processes = list(scan_processes(policy).values())
    key = {"cpu": lambda p: p.cpu_pct, "rss": lambda p: p.rss_kb, "swap": lambda p: p.swap_kb}[sort]
    _print_processes(sorted(processes, key=key, reverse=True)[:top], include_swap=True)
    return 0


def cmd_swap(policy) -> int:
    processes = sorted(scan_processes(policy).values(), key=lambda p: p.swap_kb, reverse=True)
    _print_processes([p for p in processes if p.swap_kb > 0][:30], include_swap=True)
    return 0


def cmd_docker(policy) -> int:
    containers = scan_docker(policy)
    for c in containers:
        tags = []
        if c.name in policy.keep_container_names:
            tags.append("protect")
        if c.name in policy.poc_container_names or any(c.image.startswith(prefix) for prefix in policy.poc_container_images):
            tags.append("ephemeral")
        print(f"{c.name:36} {c.status:20} {c.image} {' '.join(tags)}")
    return 0


def cmd_watch(policy, interval: float, tier: str) -> int:
    try:
        while True:
            memory = read_memory()
            load1, load5, load15 = load_average()
            processes = scan_processes(policy)
            containers = scan_docker(policy)
            actions = plan_actions(processes, containers, policy, tier=tier)
            print(
                f"{time.strftime('%H:%M:%S')} pressure={pressure_level(memory, load1, policy)} "
                f"load={load1:.2f}/{load5:.2f}/{load15:.2f} "
                f"avail={fmt_kb(memory.mem_available_kb)} "
                f"swap={fmt_kb(memory.swap_used_kb)}/{fmt_kb(memory.swap_total_kb)} "
                f"actions={len(actions)}"
            )
            for action in actions[:5]:
                print(f"  [{action.risk}] {action.kind} {action.target} - {action.reason}")
            sys.stdout.flush()
            time.sleep(max(1.0, interval))
    except KeyboardInterrupt:
        return 130


def cmd_clean(policy, tier: str, execute: bool, force: bool, allow_docker: bool, json_output: bool) -> int:
    if json_output and execute:
        print("zen clean --json cannot be combined with --execute", file=sys.stderr)
        return 2
    audit = build_clean_audit(policy, tier=tier)
    if json_output:
        print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
        return 0
    print_clean_audit(audit, execute=execute, force=force, allow_docker=allow_docker)
    return 0


def build_clean_audit(policy, tier: str) -> CleanAudit:
    memory = read_memory()
    load1, load5, load15 = load_average()
    processes = scan_processes(policy)
    containers = scan_docker(policy)
    actions = plan_actions(processes, containers, policy, tier=tier)
    buckets = summarize_processes(list(processes.values()))
    return CleanAudit(
        pressure=pressure_level(memory, load1, policy),
        load=(load1, load5, load15),
        memory=memory,
        buckets=buckets,
        recommendations=recommendations(memory, buckets, actions, containers),
        top_cpu=sorted(processes.values(), key=lambda p: p.cpu_pct, reverse=True)[:5],
        top_memory=sorted(processes.values(), key=lambda p: p.rss_kb, reverse=True)[:5],
        actions=actions,
        containers=containers,
    )


def print_clean_audit(audit: CleanAudit, execute: bool, force: bool, allow_docker: bool) -> None:
    print("CPU/RAM audit:")
    print(f"  pressure: {audit.pressure}")
    print(f"  load: {audit.load[0]:.2f} {audit.load[1]:.2f} {audit.load[2]:.2f}")
    print(f"  ram available: {fmt_kb(audit.memory.mem_available_kb)} / {fmt_kb(audit.memory.mem_total_kb)}")
    print(f"  swap used: {fmt_kb(audit.memory.swap_used_kb)} / {fmt_kb(audit.memory.swap_total_kb)} ({audit.memory.swap_used_pct:.1f}%)")
    print()
    print("  by workload:")
    _print_buckets(audit.buckets[:8])
    print()
    print("  recommendations:")
    _print_recommendations(audit.recommendations)
    print()
    print("  top cpu:")
    _print_processes(audit.top_cpu)
    print("  top memory:")
    _print_processes(audit.top_memory, include_swap=True)
    print()
    if not audit.actions:
        print("No cleanup actions found.")
        return
    for action in audit.actions:
        print(f"{_action_label(action, execute, allow_docker)} [{action.risk}] {action.kind} {action.target} - {action.reason}")
        if action.meta.get("cmdline"):
            print(f"      {action.meta['cmdline']}")
        if execute:
            print(f"      -> {execute_action(action, force=force, allow_docker=allow_docker)}")
    if not execute:
        print()
        print("Dry run only. Add --execute to perform these actions.")


def cmd_run(args) -> int:
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("zen run requires a command", file=sys.stderr)
        return 2
    policy = default_policy()
    memory = read_memory()
    load1, _, _ = load_average()
    level = pressure_level(memory, load1, policy)
    if level in {"red", "black"} and not args.force:
        print(f"refusing to start lease while pressure is {level}; pass --force to override", file=sys.stderr)
        return 75
    ttl = parse_ttl(args.ttl)
    proc = subprocess.Popen(command, start_new_session=True)
    lease = create_lease(args.klass, command, proc.pid, os.getpgid(proc.pid), ttl, args.cleanup, allow_kill=True, budget=_budget_from_args(args))
    print(f"lease {lease.id} pid={lease.pid} pgid={lease.pgid} class={lease.klass}")
    if lease.budget:
        print(f"budget advisory: {_format_budget(lease.budget)}")
    try:
        return proc.wait()
    finally:
        prune_dead_leases()


def cmd_adopt(policy, args) -> int:
    processes = scan_processes(policy)
    proc = processes.get(args.pid)
    if not proc:
        print(f"pid {args.pid} is not running or is not visible", file=sys.stderr)
        return 1
    ttl = parse_ttl(args.ttl)
    command = _command_for_lease(proc.cmdline)
    lease = create_lease(args.klass, command, proc.pid, proc.pgid, ttl, args.cleanup, cwd=proc.cwd, allow_kill=args.allow_kill, budget=_budget_from_args(args))
    print(f"adopted lease {lease.id} pid={lease.pid} pgid={lease.pgid} class={lease.klass}")
    if lease.budget:
        print(f"budget advisory: {_format_budget(lease.budget)}")
    if not args.allow_kill:
        print("note: this is observe-only; expired cleanup will not kill it without --allow-kill")
    if proc.protected:
        print("note: process is protected; expired lease cleanup will not kill it unless policy changes")
    return 0


def cmd_config(args) -> int:
    path = args.path or policy_path()
    if args.init:
        created = write_default_policy(path, overwrite=args.overwrite)
        print(f"policy config: {created}")
        return 0
    print(f"policy config: {path}")
    if path.exists():
        print(path.read_text(), end="")
    else:
        print("not found; run `zen config --init` to create one")
    return 0


def cmd_leases() -> int:
    leases = prune_dead_leases()
    now = time.time()
    if not leases:
        print("No leases.")
        return 0
    for lease in leases:
        remaining = "none"
        if lease.expired_at:
            remaining = f"{int(lease.expired_at - now)}s"
        budget = f" budget={_format_budget(lease.budget)}" if lease.budget else ""
        print(f"{lease.id} pid={lease.pid} pgid={lease.pgid} class={lease.klass} ttl_remaining={remaining}{budget} cmd={' '.join(lease.command)}")
    return 0


def _command_for_lease(cmdline: str) -> list[str]:
    if not cmdline:
        return ["<unknown>"]
    try:
        parsed = shlex.split(cmdline)
    except ValueError:
        return [cmdline]
    return parsed or [cmdline]


def _budget_from_args(args) -> dict:
    budget = {}
    if getattr(args, "mem", None):
        budget["mem"] = args.mem
    if getattr(args, "cpu", None) is not None:
        budget["cpu"] = args.cpu
    if getattr(args, "pids", None) is not None:
        budget["pids"] = args.pids
    return budget


def _format_budget(budget: dict) -> str:
    parts = []
    for key in ("mem", "cpu", "pids"):
        if key in budget:
            parts.append(f"{key}={budget[key]}")
    return ",".join(parts)


def _print_processes(processes, include_swap: bool = False) -> None:
    for p in processes:
        tags = ",".join(sorted(p.tags)) or "-"
        swap = f" swap={fmt_kb(p.swap_kb)}" if include_swap else ""
        print(f"{p.pid:>7} cpu={p.cpu_pct:>5.1f}% rss={fmt_kb(p.rss_kb):>10}{swap:>16} {p.name:<18} tags={tags} {p.cmdline[:120]}")


def _print_buckets(buckets) -> None:
    for bucket in buckets:
        if bucket.count == 0:
            continue
        print(
            f"    {bucket.name:<12} cpu={bucket.cpu_pct:>6.1f}% "
            f"rss={fmt_kb(bucket.rss_kb):>9} swap={fmt_kb(bucket.swap_kb):>9} procs={bucket.count}"
        )


def _print_recommendations(items) -> None:
    for item in items:
        print(f"    [{item.level}] {item.message}")


def _action_label(action, execute: bool, allow_docker: bool) -> str:
    if not execute:
        return "DRY "
    if action.kind == "review":
        return "REVIEW"
    if action.kind == "docker-stop" and not allow_docker and not action.meta.get("owned_by_zen"):
        return "BLOCK"
    if action.kind == "kill-tree" and not action.meta.get("owned_by_zen"):
        return "BLOCK"
    return "EXEC"


if __name__ == "__main__":
    raise SystemExit(main())
