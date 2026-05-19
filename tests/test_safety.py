from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from zen.actions import execute_action
from zen.audit import recommendations, summarize_processes
from zen.audit import CleanAudit
from zen.leases import create_lease, load_leases
from zen.models import Action, DockerContainer, MemoryInfo, ProcessInfo
from zen.policy import plan_actions
from zen.config import Policy
from zen.util import process_identity


class SafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state = os.environ.get("ZEN_STATE_DIR")
        os.environ["ZEN_STATE_DIR"] = self.tmp.name

    def tearDown(self) -> None:
        if self.old_state is None:
            os.environ.pop("ZEN_STATE_DIR", None)
        else:
            os.environ["ZEN_STATE_DIR"] = self.old_state
        self.tmp.cleanup()

    def test_non_owned_kill_action_is_blocked(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        self.addCleanup(_terminate, proc)

        action = Action(kind="kill-tree", target=f"pid:{proc.pid}", reason="test", pids=[proc.pid])
        result = execute_action(action)

        self.assertIn("blocked non-owned process kill", result)
        self.assertIsNone(proc.poll())

    def test_adopted_lease_without_allow_kill_is_review_only(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        self.addCleanup(_terminate, proc)
        create_lease(
            "adopted-test",
            ["sleep", "30"],
            proc.pid,
            os.getpgid(proc.pid),
            ttl_seconds=0,
            cleanup=None,
            allow_kill=False,
        )
        processes = {
            proc.pid: _process_info(proc, "sleep 30")
        }

        actions = plan_actions(processes, [], Policy())

        self.assertEqual(actions[0].kind, "review")
        self.assertEqual(actions[0].risk, "blocked")
        self.assertIn("review only", execute_action(actions[0]))
        self.assertIsNone(proc.poll())

    def test_owned_expired_lease_can_be_stopped(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        self.addCleanup(_terminate, proc)
        create_lease(
            "owned-test",
            ["sleep", "30"],
            proc.pid,
            os.getpgid(proc.pid),
            ttl_seconds=0,
            cleanup=None,
            allow_kill=True,
        )
        processes = {
            proc.pid: _process_info(proc, "sleep 30")
        }

        actions = plan_actions(processes, [], Policy())
        self.assertEqual(actions[0].kind, "kill-tree")
        self.assertTrue(actions[0].meta["owned_by_zen"])

        result = execute_action(actions[0])
        self.assertIn("stopped", result)
        _wait_exited(proc)

    def test_owned_kill_with_forged_identity_is_blocked(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        self.addCleanup(_terminate, proc)

        identity = process_identity(proc.pid)
        identity["start_time_ticks"] = -1
        action = Action(
            kind="kill-tree",
            target=f"pid:{proc.pid}",
            reason="test",
            pids=[proc.pid],
            meta={"owned_by_zen": True, "pgid": os.getpgid(proc.pid), "identity": identity},
        )

        result = execute_action(action)

        self.assertIn("blocked stale process identity", result)
        self.assertIsNone(proc.poll())

    def test_expired_lease_with_stale_identity_is_review_only(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        self.addCleanup(_terminate, proc)
        lease = create_lease(
            "owned-test",
            ["sleep", "30"],
            proc.pid,
            os.getpgid(proc.pid),
            ttl_seconds=0,
            cleanup=None,
            allow_kill=True,
        )
        lease.identity["start_time_ticks"] = -1
        from zen.leases import save_leases

        save_leases([lease])

        actions = plan_actions({proc.pid: _process_info(proc, "sleep 30")}, [], Policy())

        self.assertEqual(actions[0].kind, "review")
        self.assertEqual(actions[0].risk, "blocked")
        self.assertIn("stale or unverifiable", actions[0].reason)

    def test_lease_budget_metadata_is_persisted(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        self.addCleanup(_terminate, proc)

        create_lease(
            "budget-test",
            ["sleep", "30"],
            proc.pid,
            os.getpgid(proc.pid),
            ttl_seconds=60,
            cleanup=None,
            allow_kill=True,
            budget={"mem": "2g", "cpu": 1.5, "pids": 12},
        )

        lease = load_leases()[0]

        self.assertEqual(lease.budget["mem"], "2g")
        self.assertEqual(lease.budget["cpu"], 1.5)
        self.assertEqual(lease.budget["pids"], 12)

    def test_docker_stop_blocked_without_allow_docker(self) -> None:
        action = Action(
            kind="docker-stop",
            target="fake-container",
            reason="test",
            command=["sh", "-c", f"touch {Path(self.tmp.name) / 'docker-ran'}"],
        )

        result = execute_action(action, allow_docker=False)

        self.assertIn("blocked docker stop", result)
        self.assertFalse((Path(self.tmp.name) / "docker-ran").exists())

    def test_ephemeral_heuristic_is_review_only(self) -> None:
        proc = ProcessInfo(
            pid=123,
            ppid=1,
            pgid=123,
            sid=123,
            name="node",
            state="S",
            rss_kb=0,
            swap_kb=0,
            cpu_pct=1,
            cmdline="pnpm -r build",
            tags={"ephemeral"},
        )

        actions = plan_actions({123: proc}, [], Policy())

        self.assertEqual(actions[0].kind, "review")
        self.assertEqual(actions[0].risk, "review")

    def test_process_summary_groups_agents_and_browsers(self) -> None:
        processes = [
            ProcessInfo(
                pid=1,
                ppid=0,
                pgid=1,
                sid=1,
                name="codex",
                state="S",
                rss_kb=1000,
                swap_kb=10,
                cpu_pct=4,
                cmdline="codex --yolo",
                tags={"agent"},
            ),
            ProcessInfo(
                pid=2,
                ppid=0,
                pgid=2,
                sid=2,
                name="brave",
                state="S",
                rss_kb=2000,
                swap_kb=20,
                cpu_pct=3,
                cmdline="brave",
                tags={"protect"},
            ),
        ]

        by_name = {bucket.name: bucket for bucket in summarize_processes(processes)}

        self.assertEqual(by_name["agents"].count, 1)
        self.assertEqual(by_name["browsers"].count, 1)
        self.assertEqual(by_name["agents"].cpu_pct, 4)

    def test_process_summary_groups_build_and_kernel(self) -> None:
        processes = [
            ProcessInfo(
                pid=1,
                ppid=0,
                pgid=1,
                sid=1,
                name="tectonic",
                state="S",
                rss_kb=1000,
                swap_kb=0,
                cpu_pct=5,
                cmdline="tectonic -X compile paper.tex",
            ),
            ProcessInfo(
                pid=2,
                ppid=0,
                pgid=2,
                sid=2,
                name="kswapd0",
                state="S",
                rss_kb=0,
                swap_kb=0,
                cpu_pct=7,
                cmdline="kswapd0",
            ),
        ]

        by_name = {bucket.name: bucket for bucket in summarize_processes(processes)}

        self.assertEqual(by_name["build/tools"].count, 1)
        self.assertEqual(by_name["kernel/system"].count, 1)

    def test_recommendations_preserve_browser_protection_and_docker_gate(self) -> None:
        buckets = summarize_processes(
            [
                ProcessInfo(
                    pid=1,
                    ppid=0,
                    pgid=1,
                    sid=1,
                    name="brave",
                    state="S",
                    rss_kb=3 * 1024 * 1024,
                    swap_kb=0,
                    cpu_pct=1,
                    cmdline="brave",
                    tags={"protect"},
                )
            ]
        )
        actions = [
            Action(
                kind="docker-stop",
                target="kind",
                reason="test",
                command=["docker", "stop", "kind"],
            )
        ]
        memory = MemoryInfo(mem_total_kb=10 * 1024 * 1024, mem_available_kb=2 * 1024 * 1024, swap_total_kb=10_000, swap_free_kb=1_000)

        messages = [item.message for item in recommendations(memory, buckets, actions, [])]

        self.assertTrue(any("Browsers are large but protected" in message for message in messages))
        self.assertTrue(any("--allow-docker" in message for message in messages))

    def test_clean_audit_json_shape(self) -> None:
        memory = MemoryInfo(mem_total_kb=10, mem_available_kb=5, swap_total_kb=10, swap_free_kb=9)
        audit = CleanAudit(
            pressure="green",
            load=(1.0, 2.0, 3.0),
            memory=memory,
            buckets=[],
            recommendations=[],
            top_cpu=[],
            top_memory=[],
            actions=[],
            containers=[],
        )

        data = audit.to_dict()

        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["pressure"], "green")
        self.assertEqual(data["load"]["1m"], 1.0)
        self.assertEqual(data["memory"]["swap_used_kb"], 1)
        self.assertIn("actions", data)


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    _wait_exited(proc)


def _wait_exited(proc: subprocess.Popen) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait(timeout=5)


def _process_info(proc: subprocess.Popen, cmdline: str) -> ProcessInfo:
    identity = process_identity(proc.pid)
    return ProcessInfo(
        pid=proc.pid,
        ppid=os.getpid(),
        pgid=os.getpgid(proc.pid),
        sid=os.getsid(proc.pid),
        uid=identity.get("uid"),
        start_time_ticks=identity.get("start_time_ticks"),
        name="sleep",
        state="S",
        rss_kb=0,
        swap_kb=0,
        cpu_pct=0,
        cmdline=cmdline,
    )


if __name__ == "__main__":
    unittest.main()
