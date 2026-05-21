from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import sys
import time

from .actions import execute_action
from .audit import CleanAudit, recommendations, summarize_processes
from .config import default_policy, policy_path, write_default_policy
from .docker import EXPIRES_LABEL, MANAGED_LABEL, build_docker_run_command
from .events import log_event, read_events
from .leases import create_lease, load_leases, prune_dead_leases
from .policy import plan_actions, pressure_level
from .runner import build_run_spec, popen_run_spec
from .scanner import load_average, read_memory, scan_docker, scan_processes
from .util import fmt_kb, parse_ttl, run_cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zen", description="Calm CPU/RAM audit and cleanup for AI workflows.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show current pressure summary.")
    doctor_p = sub.add_parser("doctor", help="Explain pressure and likely offenders.")
    doctor_p.add_argument("--tier", choices=["safe", "normal", "aggressive"], default="normal")

    explain_p = sub.add_parser("explain", help="Explain cleanup action gates.")
    explain_p.add_argument("--tier", choices=["safe", "normal", "aggressive"], default="normal")
    explain_p.add_argument(
        "--allow-docker",
        action="store_true",
        help="Show Docker stops as executable when ownership gates pass.",
    )
    explain_p.add_argument("--json", action="store_true")

    ps_p = sub.add_parser("ps", help="Show hot processes.")
    ps_p.add_argument("--top", type=int, default=25)
    ps_p.add_argument("--sort", choices=["cpu", "rss", "swap"], default="cpu")

    sub.add_parser("swap", help="Show swap users.")
    swap_refresh_p = sub.add_parser(
        "swap-refresh",
        help="Safely refresh swap when RAM headroom is sufficient.",
    )
    swap_refresh_p.add_argument(
        "--execute",
        action="store_true",
        help="Run sudo -n swapoff -a followed by sudo -n swapon -a.",
    )
    swap_refresh_p.add_argument("--min-headroom-gb", type=float, default=2.0)
    swap_refresh_p.add_argument("--json", action="store_true")
    sub.add_parser("docker", help="Show containers and Zen classification.")
    events_p = sub.add_parser("events", help="Show recent Zen events.")
    events_p.add_argument("--limit", type=int, default=20)
    events_p.add_argument("--json", action="store_true")
    docker_run_p = sub.add_parser("docker-run", help="Run a Docker container with Zen ownership and TTL labels.")
    docker_run_p.add_argument("--ttl", required=True)
    docker_run_p.add_argument("--name")
    docker_run_p.add_argument("image")
    docker_run_p.add_argument("command", nargs=argparse.REMAINDER)
    watch_p = sub.add_parser("watch", help="Continuously print pressure and cleanup plan.")
    watch_p.add_argument("--interval", type=float, default=5.0)
    watch_p.add_argument("--tier", choices=["safe", "normal", "aggressive"], default="normal")

    reap_p = sub.add_parser("reap", help="Continuously enforce expired Zen leases.")
    reap_p.add_argument("--interval", type=float, default=5.0)
    reap_p.add_argument("--once", action="store_true", help="Run one reap pass and exit.")
    reap_p.add_argument("--force", action="store_true", help="Escalate expired lease cleanup to SIGKILL after SIGTERM.")

    clean_p = sub.add_parser("clean", help="Audit CPU/RAM and plan cleanup. Dry-run unless --execute is passed.")
    clean_p.add_argument("--tier", choices=["safe", "normal", "aggressive"], default="normal")
    clean_p.add_argument("--execute", action="store_true")
    clean_p.add_argument("--force", action="store_true", help="Escalate process cleanup to SIGKILL after SIGTERM.")
    clean_p.add_argument("--allow-docker", action="store_true", help="Allow stopping expired Zen-owned Docker containers during --execute.")
    clean_p.add_argument("--json", action="store_true", help="Print audit as JSON. Refuses to combine with --execute.")
    clean_p.add_argument("--verbose", action="store_true", help="Include command lines, cwd, and container names in JSON output.")

    run_p = sub.add_parser("run", help="Run a command under a Zen lease.")
    run_p.add_argument("--class", dest="klass", default="generic")
    run_p.add_argument("--ttl")
    run_p.add_argument("--cleanup")
    run_p.add_argument("--mem", help="Memory limit for systemd-backed runs, e.g. 2g or 750m.")
    run_p.add_argument("--cpu", type=float, help="CPU core limit for systemd-backed runs, e.g. 1.5.")
    run_p.add_argument("--pids", type=int, help="Process-count limit for systemd-backed runs.")
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
    if args.cmd == "explain":
        return cmd_explain(
            policy,
            tier=args.tier,
            allow_docker=args.allow_docker,
            json_output=args.json,
        )
    if args.cmd == "ps":
        return cmd_ps(policy, top=args.top, sort=args.sort)
    if args.cmd == "swap":
        return cmd_swap(policy)
    if args.cmd == "swap-refresh":
        return cmd_swap_refresh(
            execute=args.execute,
            min_headroom_gb=args.min_headroom_gb,
            json_output=args.json,
        )
    if args.cmd == "docker":
        return cmd_docker(policy)
    if args.cmd == "events":
        return cmd_events(limit=args.limit, json_output=args.json)
    if args.cmd == "docker-run":
        return cmd_docker_run(args)
    if args.cmd == "watch":
        return cmd_watch(policy, interval=args.interval, tier=args.tier)
    if args.cmd == "reap":
        return cmd_reap(policy, interval=args.interval, once=args.once, force=args.force)
    if args.cmd == "clean":
        return cmd_clean(policy, tier=args.tier, execute=args.execute, force=args.force, allow_docker=args.allow_docker, json_output=args.json, verbose=args.verbose)
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


def cmd_explain(policy, tier: str, allow_docker: bool, json_output: bool) -> int:
    processes = scan_processes(policy)
    containers = scan_docker(policy)
    actions = plan_actions(processes, containers, policy, tier=tier)
    explanations = [explain_action(action, allow_docker=allow_docker) for action in actions]
    if json_output:
        print(json.dumps({"actions": explanations}, indent=2, sort_keys=True))
        return 0
    if not explanations:
        print("No cleanup actions found.")
        return 0
    for item in explanations:
        print(f"{item['status'].upper():11} [{item['risk']}] {item['kind']} {item['target']}")
        print(f"  reason: {item['reason']}")
        for gate in item["gates"]:
            state = "pass" if gate["pass"] else "fail"
            print(f"  {state}: {gate['name']} - {gate['detail']}")
    return 0


def explain_action(action, allow_docker: bool = False) -> dict:
    gates: list[dict] = []

    def add_gate(name: str, passed: bool, detail: str) -> None:
        gates.append({"name": name, "pass": passed, "detail": detail})

    status = "blocked"
    if action.kind == "review":
        add_gate("heuristic-only", False, "review actions are never executed automatically")
        status = "review"
    elif action.kind == "kill-tree":
        owned = bool(action.meta.get("owned_by_zen"))
        has_identity = bool(action.meta.get("identity"))
        add_gate("zen-owned", owned, "process action must come from a Zen lease")
        add_gate(
            "identity-recorded",
            has_identity,
            "UID, process group, session, and start time are rechecked before signaling",
        )
        status = "executable" if owned and has_identity else "blocked"
    elif action.kind == "docker-stop":
        owned = bool(action.meta.get("owned_by_zen"))
        add_gate("zen-owned", owned, "container must have Zen ownership labels")
        add_gate("docker-enabled", allow_docker, "caller must pass --allow-docker")
        status = "executable" if owned and allow_docker else "blocked"
    else:
        add_gate("known-action", False, "unknown action kinds are blocked")

    return {
        "kind": action.kind,
        "target": action.target,
        "reason": action.reason,
        "risk": action.risk,
        "status": status,
        "gates": gates,
    }


def cmd_ps(policy, top: int, sort: str) -> int:
    processes = list(scan_processes(policy).values())
    key = {"cpu": lambda p: p.cpu_pct, "rss": lambda p: p.rss_kb, "swap": lambda p: p.swap_kb}[sort]
    _print_processes(sorted(processes, key=key, reverse=True)[:top], include_swap=True)
    return 0


def cmd_swap(policy) -> int:
    processes = sorted(scan_processes(policy).values(), key=lambda p: p.swap_kb, reverse=True)
    _print_processes([p for p in processes if p.swap_kb > 0][:30], include_swap=True)
    return 0


def cmd_swap_refresh(execute: bool, min_headroom_gb: float, json_output: bool) -> int:
    plan = plan_swap_refresh(read_memory(), min_headroom_gb=min_headroom_gb)
    if json_output:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0 if not execute or plan["executable"] else 75
    print("Swap refresh plan:")
    print(f"  status: {plan['status']}")
    print(f"  swap used: {fmt_kb(plan['swap_used_kb'])}")
    print(f"  ram available: {fmt_kb(plan['mem_available_kb'])}")
    print(f"  required available: {fmt_kb(plan['required_available_kb'])}")
    print(
        f"  command: {' '.join(plan['commands'][0])} && "
        f"{' '.join(plan['commands'][1])}"
    )
    print(f"  reason: {plan['reason']}")
    if not execute:
        print("Dry run only. Add --execute to refresh swap.")
        return 0
    if not plan["executable"]:
        print("Refusing to refresh swap because the safety gate failed.", file=sys.stderr)
        return 75
    off = run_cmd(plan["commands"][0], timeout=300)
    if off.returncode != 0:
        if off.stderr.strip():
            print(off.stderr.strip(), file=sys.stderr)
        print("swapoff failed; swap was not refreshed", file=sys.stderr)
        return off.returncode or 1
    on = run_cmd(plan["commands"][1], timeout=60)
    if on.returncode != 0:
        if on.stderr.strip():
            print(on.stderr.strip(), file=sys.stderr)
        print("swapon failed after swapoff; inspect swap configuration immediately", file=sys.stderr)
        return on.returncode or 1
    log_event(
        "swap_refreshed",
        swap_used_kb=plan["swap_used_kb"],
        mem_available_kb=plan["mem_available_kb"],
    )
    print("Swap refreshed.")
    return 0


def plan_swap_refresh(memory, min_headroom_gb: float = 2.0) -> dict:
    headroom_kb = max(0, int(min_headroom_gb * 1024 * 1024))
    required_available_kb = memory.swap_used_kb + headroom_kb
    commands = [["sudo", "-n", "swapoff", "-a"], ["sudo", "-n", "swapon", "-a"]]
    if memory.swap_total_kb <= 0:
        status = "skipped"
        executable = False
        reason = "no swap is configured"
    elif memory.swap_used_kb <= 0:
        status = "skipped"
        executable = False
        reason = "swap is already empty"
    elif memory.mem_available_kb < required_available_kb:
        status = "blocked"
        executable = False
        reason = "available RAM must cover current swap usage plus headroom"
    else:
        status = "ready"
        executable = True
        reason = "available RAM can absorb swapped pages with the requested headroom"
    return {
        "status": status,
        "executable": executable,
        "reason": reason,
        "swap_total_kb": memory.swap_total_kb,
        "swap_used_kb": memory.swap_used_kb,
        "mem_available_kb": memory.mem_available_kb,
        "min_headroom_gb": min_headroom_gb,
        "required_available_kb": required_available_kb,
        "commands": commands,
    }


def cmd_docker(policy) -> int:
    containers = scan_docker(policy)
    for c in containers:
        tags = []
        if c.name in policy.keep_container_names:
            tags.append("protect")
        if c.labels.get(MANAGED_LABEL) == "true":
            tags.append("owned")
        if c.name in policy.poc_container_names or any(c.image.startswith(prefix) for prefix in policy.poc_container_images):
            tags.append("review")
        print(f"{c.name:36} {c.status:20} {c.image} {' '.join(tags)}")
    return 0


def cmd_docker_run(args) -> int:
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    ttl = parse_ttl(args.ttl)
    if ttl is None:
        print("zen docker-run requires --ttl", file=sys.stderr)
        return 2
    try:
        run_args, labels = build_docker_run_command(args.image, command, ttl, name=args.name)
    except ValueError as exc:
        print(f"invalid docker-run: {exc}", file=sys.stderr)
        return 2
    result = run_cmd(run_args, timeout=60)
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        return result.returncode
    container_id = result.stdout.strip()
    log_event("docker_container_started", container_id=container_id, image=args.image, ttl=args.ttl, expires_at=labels[EXPIRES_LABEL])
    print(f"container {container_id}")
    print(f"ttl={args.ttl} expires_at={labels[EXPIRES_LABEL]}")
    return 0


def cmd_events(limit: int, json_output: bool) -> int:
    events = read_events(limit=max(0, limit))
    if json_output:
        print(json.dumps(events, indent=2, sort_keys=True))
        return 0
    if not events:
        print("No events.")
        return 0
    for event in events:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(event.get("ts", 0))))
        kind = event.get("kind", "unknown")
        details = " ".join(f"{key}={value}" for key, value in event.items() if key not in {"ts", "kind"})
        print(f"{ts} {kind} {details}".rstrip())
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


def cmd_reap(policy, interval: float, once: bool, force: bool) -> int:
    try:
        while True:
            results = reap_expired_leases(policy, force=force)
            if results:
                for result in results:
                    print(f"{time.strftime('%H:%M:%S')} {result}")
            elif once:
                print("No expired executable leases.")
            sys.stdout.flush()
            if once:
                return 0
            time.sleep(max(1.0, interval))
    except KeyboardInterrupt:
        return 130


def reap_expired_leases(policy, force: bool = False) -> list[str]:
    processes = scan_processes(policy)
    actions = [
        action
        for action in plan_actions(processes, [], policy, tier="safe")
        if action.target.startswith("lease:")
    ]
    results: list[str] = []
    for action in actions:
        if action.kind == "kill-tree":
            results.append(execute_action(action, force=force, allow_docker=False))
        elif action.kind == "review":
            results.append(f"review only: {action.target} - {action.reason}")
    return results


def cmd_clean(policy, tier: str, execute: bool, force: bool, allow_docker: bool, json_output: bool, verbose: bool) -> int:
    if json_output and execute:
        print("zen clean --json cannot be combined with --execute", file=sys.stderr)
        return 2
    audit = build_clean_audit(policy, tier=tier)
    if json_output:
        print(json.dumps(audit.to_dict(redact=not verbose), indent=2, sort_keys=True))
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
    budget = _budget_from_args(args)
    try:
        spec = build_run_spec(command, budget, cwd=os.getcwd())
    except ValueError as exc:
        print(f"invalid budget: {exc}", file=sys.stderr)
        return 2
    proc = popen_run_spec(spec)
    lease = create_lease(
        args.klass,
        command,
        proc.pid,
        os.getpgid(proc.pid),
        ttl,
        args.cleanup,
        allow_kill=True,
        budget=budget,
        runtime=spec.runtime,
    )
    print(f"lease {lease.id} pid={lease.pid} pgid={lease.pgid} class={lease.klass}")
    if lease.budget:
        status = "enforced" if lease.runtime.get("budgets_enforced") else "advisory"
        print(f"budget {status}: {_format_budget(lease.budget)}")
        if lease.runtime.get("fallback_reason"):
            print(f"budget fallback: {lease.runtime['fallback_reason']}")
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
        runtime = ""
        if lease.runtime:
            enforced = "enforced" if lease.runtime.get("budgets_enforced") else "advisory"
            runtime = f" backend={lease.runtime.get('backend')} budgets={enforced}"
        print(f"{lease.id} pid={lease.pid} pgid={lease.pgid} class={lease.klass} ttl_remaining={remaining}{budget}{runtime} cmd={' '.join(lease.command)}")
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
    if action.kind == "docker-stop" and (not allow_docker or not action.meta.get("owned_by_zen")):
        return "BLOCK"
    if action.kind == "kill-tree" and not action.meta.get("owned_by_zen"):
        return "BLOCK"
    return "EXEC"


if __name__ == "__main__":
    raise SystemExit(main())
