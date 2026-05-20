from __future__ import annotations

import signal
import time

from .models import Action
from .events import log_event
from .util import identity_matches, kill_process_group, kill_process_tree, run_cmd


def execute_action(action: Action, force: bool = False, allow_docker: bool = False) -> str:
    if action.kind == "review":
        log_event("action_review", target=action.target, reason=action.reason, risk=action.risk)
        return f"review only: {action.target}"
    if action.kind == "kill-tree":
        if not action.meta.get("owned_by_zen"):
            log_event("action_blocked", kind=action.kind, target=action.target, reason="non-owned process")
            return f"blocked non-owned process kill: {action.target}"
        identity = action.meta.get("identity")
        pgid = action.meta.get("pgid")
        if not action.pids or not identity or not identity_matches(action.pids[0], identity):
            log_event("action_blocked", kind=action.kind, target=action.target, reason="stale process identity")
            return f"blocked stale process identity: {action.target}"
        if not isinstance(pgid, int) or pgid <= 1:
            log_event("action_blocked", kind=action.kind, target=action.target, reason="unsafe process group")
            return f"blocked unsafe process group: {action.target}"
        unit = action.meta.get("runtime", {}).get("unit") if isinstance(action.meta.get("runtime"), dict) else None
        if unit:
            run_cmd(["systemctl", "--user", "stop", str(unit)], timeout=10)
        kill_process_group(pgid, signal.SIGTERM)
        for pid in action.pids:
            kill_process_tree(pid, signal.SIGTERM)
        time.sleep(2)
        if force:
            if not identity_matches(action.pids[0], identity):
                return f"stopped {action.target}"
            kill_process_group(pgid, signal.SIGKILL)
            for pid in action.pids:
                kill_process_tree(pid, signal.SIGKILL)
        log_event("action_executed", kind=action.kind, target=action.target, reason=action.reason)
        return f"stopped {action.target}"
    if action.kind == "docker-stop" and action.command:
        if not action.meta.get("owned_by_zen"):
            log_event("action_blocked", kind=action.kind, target=action.target, reason="non-owned docker")
            return f"blocked non-owned docker stop: {action.target}"
        if not allow_docker:
            log_event("action_blocked", kind=action.kind, target=action.target, reason="docker gate")
            return f"blocked docker stop without --allow-docker: {action.target}"
        result = run_cmd(action.command, timeout=30)
        if result.returncode != 0:
            return f"failed {action.target}: {result.stderr.strip()}"
        log_event("action_executed", kind=action.kind, target=action.target, reason=action.reason)
        return f"stopped container {action.target}"
    return f"unknown action {action.kind}:{action.target}"
