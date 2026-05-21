from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
import io
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from zen.actions import execute_action
from zen.audit import recommendations, summarize_processes
from zen.audit import CleanAudit
from zen.cli import cmd_events, cmd_explain, explain_action, reap_expired_leases
from zen.docker import EXPIRES_LABEL, MANAGED_LABEL, build_docker_run_command, docker_container_expired
from zen.events import event_path, log_event, read_events
from zen.leases import create_lease, lease_path, load_leases
from zen.models import Action, DockerContainer, MemoryInfo, ProcessInfo
from zen.policy import plan_actions
from zen.runner import build_run_spec, normalize_memory_max, systemd_properties_for_budget
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

    def test_reaper_stops_only_expired_owned_leases(self) -> None:
        owned = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        observe_only = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        self.addCleanup(_terminate, owned)
        self.addCleanup(_terminate, observe_only)
        create_lease(
            "owned-test",
            ["sleep", "30"],
            owned.pid,
            os.getpgid(owned.pid),
            ttl_seconds=0,
            cleanup=None,
            allow_kill=True,
        )
        create_lease(
            "observe-test",
            ["sleep", "30"],
            observe_only.pid,
            os.getpgid(observe_only.pid),
            ttl_seconds=0,
            cleanup=None,
            allow_kill=False,
        )

        results = reap_expired_leases(Policy())

        self.assertTrue(any("stopped lease:" in result for result in results))
        self.assertTrue(any("review only: lease:" in result for result in results))
        _wait_exited(owned)
        self.assertIsNone(observe_only.poll())

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

    def test_lease_creation_writes_event(self) -> None:
        create_lease(
            "event-test",
            ["sleep", "30"],
            os.getpid(),
            os.getpgid(os.getpid()),
            ttl_seconds=60,
            cleanup=None,
            allow_kill=False,
        )

        events = read_events()

        self.assertEqual(events[-1]["kind"], "lease_created")
        self.assertEqual(events[-1]["klass"], "event-test")

    def test_events_reader_skips_bad_lines_and_limits(self) -> None:
        path = event_path()
        path.write_text('{"kind":"first","ts":1}\nnot-json\n{"kind":"second","ts":2}\n')

        events = read_events(limit=2)

        self.assertEqual([event["kind"] for event in events], ["second"])

    def test_event_log_rotates_before_append(self) -> None:
        path = event_path()
        path.write_text('{"kind":"old","ts":1}\n' * 10)

        log_event("new", max_bytes=10, keep=2)

        self.assertEqual(read_events()[-1]["kind"], "new")
        self.assertTrue(path.with_name("events.jsonl.1").exists())
        self.assertIn('"kind":"old"', path.with_name("events.jsonl.1").read_text())

    def test_event_log_rotation_respects_keep_count(self) -> None:
        path = event_path()
        path.write_text("a" * 20)
        log_event("first", max_bytes=10, keep=2)
        path.write_text("b" * 20)
        log_event("second", max_bytes=10, keep=2)
        path.write_text("c" * 20)
        log_event("third", max_bytes=10, keep=2)

        self.assertTrue(path.with_name("events.jsonl.1").exists())
        self.assertTrue(path.with_name("events.jsonl.2").exists())
        self.assertFalse(path.with_name("events.jsonl.3").exists())

    def test_cmd_events_json_output(self) -> None:
        log_event("unit_test", value=1)

        with _capture_stdout() as captured:
            result = cmd_events(limit=10, json_output=True)

        self.assertEqual(result, 0)
        self.assertIn('"kind": "unit_test"', captured.getvalue())

    def test_concurrent_lease_creates_do_not_clobber_state(self) -> None:
        def create(index: int) -> None:
            create_lease(
                f"concurrent-{index}",
                ["sleep", "30"],
                os.getpid(),
                os.getpgid(os.getpid()),
                ttl_seconds=60,
                cleanup=None,
                allow_kill=False,
            )

        threads = [threading.Thread(target=create, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(load_leases()), 12)

    def test_corrupt_lease_file_is_quarantined(self) -> None:
        path = lease_path()
        path.write_text("{not valid json")

        leases = load_leases()

        self.assertEqual(leases, [])
        self.assertFalse(path.exists())
        corrupt_files = list(Path(self.tmp.name).glob("leases.json.corrupt-*"))
        self.assertEqual(len(corrupt_files), 1)
        self.assertEqual(corrupt_files[0].read_text(), "{not valid json")
        self.assertEqual(read_events()[-1]["kind"], "lease_store_corrupt")

    def test_create_lease_after_corruption_preserves_new_state(self) -> None:
        path = lease_path()
        path.write_text("{not valid json")

        create_lease(
            "after-corrupt",
            ["sleep", "30"],
            os.getpid(),
            os.getpgid(os.getpid()),
            ttl_seconds=60,
            cleanup=None,
            allow_kill=False,
        )

        self.assertEqual(len(load_leases()), 1)
        self.assertEqual(len(list(Path(self.tmp.name).glob("leases.json.corrupt-*"))), 1)

    def test_budget_properties_are_normalized_for_systemd(self) -> None:
        props = systemd_properties_for_budget({"mem": "1.5g", "cpu": 1.25, "pids": 12})

        self.assertEqual(props["MemoryMax"], str(int(1.5 * 1024**3)))
        self.assertEqual(props["CPUQuota"], "125%")
        self.assertEqual(props["TasksMax"], "12")

    def test_invalid_budget_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_memory_max("0g")
        with self.assertRaises(ValueError):
            systemd_properties_for_budget({"cpu": 0})
        with self.assertRaises(ValueError):
            systemd_properties_for_budget({"pids": -1})

    def test_budgeted_run_falls_back_when_systemd_disabled(self) -> None:
        old_value = os.environ.get("ZEN_DISABLE_SYSTEMD")
        os.environ["ZEN_DISABLE_SYSTEMD"] = "1"
        try:
            spec = build_run_spec(["echo", "ok"], {"mem": "64m"})
        finally:
            if old_value is None:
                os.environ.pop("ZEN_DISABLE_SYSTEMD", None)
            else:
                os.environ["ZEN_DISABLE_SYSTEMD"] = old_value

        self.assertEqual(spec.command, ["echo", "ok"])
        self.assertEqual(spec.runtime["backend"], "subprocess")
        self.assertFalse(spec.runtime["budgets_enforced"])

    def test_budgeted_run_uses_systemd_when_available(self) -> None:
        spec = build_run_spec(["echo", "ok"], {"mem": "64m", "cpu": 0.5, "pids": 4}, cwd="/tmp")

        if spec.runtime["backend"] == "subprocess":
            self.assertFalse(spec.runtime["budgets_enforced"])
            return
        self.assertEqual(spec.command[0], "systemd-run")
        self.assertIn("--scope", spec.command)
        self.assertIn("--working-directory", spec.command)
        self.assertTrue(spec.runtime["budgets_enforced"])
        self.assertEqual(spec.runtime["properties"]["MemoryMax"], str(64 * 1024**2))

    def test_docker_stop_blocked_without_allow_docker(self) -> None:
        action = Action(
            kind="docker-stop",
            target="fake-container",
            reason="test",
            command=["sh", "-c", f"touch {Path(self.tmp.name) / 'docker-ran'}"],
            meta={"owned_by_zen": True},
        )

        result = execute_action(action, allow_docker=False)

        self.assertIn("blocked docker stop", result)
        self.assertFalse((Path(self.tmp.name) / "docker-ran").exists())

    def test_non_owned_docker_stop_blocked_even_with_allow_docker(self) -> None:
        action = Action(
            kind="docker-stop",
            target="fake-container",
            reason="test",
            command=["sh", "-c", f"touch {Path(self.tmp.name) / 'docker-ran'}"],
        )

        result = execute_action(action, allow_docker=True)

        self.assertIn("blocked non-owned docker stop", result)
        self.assertFalse((Path(self.tmp.name) / "docker-ran").exists())

    def test_expired_zen_owned_container_can_plan_docker_stop(self) -> None:
        container = DockerContainer(
            container_id="abc123",
            name="zen-owned",
            image="busybox:latest",
            status="Up",
            labels={MANAGED_LABEL: "true", EXPIRES_LABEL: "1"},
        )

        actions = plan_actions({}, [container], Policy())

        self.assertEqual(actions[0].kind, "docker-stop")
        self.assertTrue(actions[0].meta["owned_by_zen"])
        self.assertEqual(actions[0].command, ["docker", "stop", "abc123"])

    def test_unexpired_zen_owned_container_is_not_stopped(self) -> None:
        container = DockerContainer(
            container_id="abc123",
            name="zen-owned",
            image="busybox:latest",
            status="Up",
            labels={MANAGED_LABEL: "true", EXPIRES_LABEL: str(time.time() + 3600)},
        )

        actions = plan_actions({}, [container], Policy())

        self.assertEqual(actions, [])

    def test_zen_owned_container_without_expiry_is_review_only(self) -> None:
        container = DockerContainer(
            container_id="abc123",
            name="zen-owned",
            image="busybox:latest",
            status="Up",
            labels={MANAGED_LABEL: "true"},
        )

        actions = plan_actions({}, [container], Policy())

        self.assertEqual(actions[0].kind, "review")
        self.assertEqual(actions[0].risk, "blocked")

    def test_disposable_container_heuristic_is_review_only(self) -> None:
        container = DockerContainer(
            container_id="abc123",
            name="not-owned",
            image="kindest/node:v1.35.0",
            status="Up",
        )

        actions = plan_actions({}, [container], Policy(), tier="aggressive")

        self.assertEqual(actions[0].kind, "review")
        self.assertEqual(actions[0].risk, "review")

    def test_docker_run_command_adds_zen_ttl_labels(self) -> None:
        command, labels = build_docker_run_command("busybox:latest", ["sleep", "30"], ttl_seconds=60, name="zen-test", now=100)

        self.assertEqual(command[:5], ["docker", "run", "-d", "--name", "zen-test"])
        self.assertIn("--label", command)
        self.assertEqual(labels[MANAGED_LABEL], "true")
        self.assertEqual(labels[EXPIRES_LABEL], "160")
        self.assertFalse(docker_container_expired(labels, now=159))
        self.assertTrue(docker_container_expired(labels, now=160))

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

    def test_explain_action_marks_review_as_review_only(self) -> None:
        action = Action(kind="review", target="pid:123", reason="possible ephemeral workload", risk="review")

        explanation = explain_action(action)

        self.assertEqual(explanation["status"], "review")
        self.assertFalse(explanation["gates"][0]["pass"])
        self.assertIn("never executed", explanation["gates"][0]["detail"])

    def test_explain_action_requires_docker_allow_flag(self) -> None:
        action = Action(
            kind="docker-stop",
            target="zen-owned",
            reason="expired Zen-owned container",
            risk="safe",
            meta={"owned_by_zen": True},
        )

        blocked = explain_action(action, allow_docker=False)
        executable = explain_action(action, allow_docker=True)

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(executable["status"], "executable")

    def test_explain_action_requires_owned_process_identity(self) -> None:
        blocked = Action(
            kind="kill-tree",
            target="lease:abc",
            reason="expired lease",
            risk="safe",
            meta={"owned_by_zen": True},
        )
        executable = Action(
            kind="kill-tree",
            target="lease:def",
            reason="expired lease",
            risk="safe",
            meta={"owned_by_zen": True, "identity": {"uid": 1}},
        )

        self.assertEqual(explain_action(blocked)["status"], "blocked")
        self.assertEqual(explain_action(executable)["status"], "executable")

    def test_cmd_explain_json_output(self) -> None:
        with _capture_stdout() as captured:
            result = cmd_explain(Policy(), tier="normal", allow_docker=False, json_output=True)

        self.assertEqual(result, 0)
        self.assertIn('"actions"', captured.getvalue())

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


@contextmanager
def _capture_stdout():
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        yield buffer


if __name__ == "__main__":
    unittest.main()
