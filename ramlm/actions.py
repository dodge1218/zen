from __future__ import annotations

import signal
import time

from .models import Action
from .util import kill_process_tree, run_cmd


def execute_action(action: Action, force: bool = False, allow_docker: bool = False) -> str:
    if action.kind == "review":
        return f"review only: {action.target}"
    if action.kind == "kill-tree":
        if not action.meta.get("owned_by_zen"):
            return f"blocked non-owned process kill: {action.target}"
        for pid in action.pids:
            kill_process_tree(pid, signal.SIGTERM)
        time.sleep(2)
        if force:
            for pid in action.pids:
                kill_process_tree(pid, signal.SIGKILL)
        return f"stopped {action.target}"
    if action.kind == "docker-stop" and action.command:
        if not allow_docker and not action.meta.get("owned_by_zen"):
            return f"blocked docker stop without --allow-docker: {action.target}"
        result = run_cmd(action.command, timeout=30)
        if result.returncode != 0:
            return f"failed {action.target}: {result.stderr.strip()}"
        return f"stopped container {action.target}"
    return f"unknown action {action.kind}:{action.target}"
