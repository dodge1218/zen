# Zen

**Calm CPU/RAM audit and cleanup for AI-agent workflows.**

AI agents now spawn shells, browsers, Docker containers, test runners, repo
scans, local models, and nested agents. Those workloads often outlive the task
that created them. The result is familiar: hot CPUs, full swap, stuck browsers,
orphan containers, and no obvious answer to "what is safe to kill?"

Zen gives agent-spawned work a lifecycle:

```text
audit -> classify -> protect -> lease -> clean
```

The default command is intentionally boring:

```bash
zen clean
```

It audits CPU, RAM, swap, workload buckets, and cleanup candidates. It does not
change the machine.

## Why It Exists

Traditional developer machines assumed the human knew what was running. Agentic
developer workflows break that assumption: agents launch tools recursively, run
browser automation, start containers, kick off test/build loops, and leave
background work behind.

Zen is not a RAM booster or a generic process killer. It is a small local
control plane for agent workload hygiene.

## Features

- CPU/RAM/swap pressure audit
- process and Docker visibility
- workload buckets: agents, browsers, Docker/Kubernetes, terminals, desktop,
  build tools, services, kernel/system, and other work
- plain-English recommendations
- explainable cleanup gates for safe, blocked, and review-only actions
- dry-run cleanup by default
- protected browsers, terminals, desktop processes, and active LLM sessions
- leases with TTLs for agent/build/test work
- foreground TTL reaper for expired owned leases
- Docker container launcher with Zen ownership and TTL labels
- locked, atomic lease-state writes with corrupt-file quarantine
- rotating local JSONL event log for lifecycle and cleanup actions
- compact pressure history snapshots for after-the-fact swap review
- observe-only adoption for already-running processes
- CPU/RAM/process-count budgets via systemd-run when available
- guarded swap refresh helper with RAM-headroom checks
- machine-readable JSON output for automation
- safety tests that prove stale, forged, and non-owned process kills are blocked

## Install

From a checkout:

```bash
git clone https://github.com/dodge1218/zen.git
cd zen
python3 -m pip install -e .
```

Or run directly from the checkout:

```bash
PYTHONPATH=. python3 -m zen.cli clean
```

## Quick Start

```bash
zen status
zen clean
zen clean --json
zen clean --json --verbose
```

Example:

```text
CPU/RAM audit:
  pressure: yellow
  load: 4.21 3.80 3.10
  ram available: 8.4 GiB / 16.0 GiB
  swap used: 3.1 GiB / 10.0 GiB (31.0%)

  by workload:
    agents       cpu= 120.0% rss=  1.2 GiB swap=512.0 MiB procs=8
    browsers     cpu=  15.0% rss=  2.8 GiB swap=300.0 MiB procs=24
    docker/kube  cpu=  10.0% rss=600.0 MiB swap= 20.0 MiB procs=12

  recommendations:
    [review] Agent CPU is the top pressure source; inspect active runs before stopping anything.
    [protect] Browsers are large but protected; Zen will not close tabs or browser processes.
```

## Command Map

```bash
zen status                         # pressure summary
zen doctor                         # top offenders + cleanup plan
zen explain                        # explain why each cleanup action is gated
zen explain --json                 # machine-readable action gate report
zen clean                          # CPU/RAM audit + dry-run cleanup
zen clean --json                   # machine-readable audit, never executes
zen clean --execute                # execute only Zen-owned expired leases
zen clean --execute --allow-docker # additionally allow Zen-owned Docker stops
zen ps --top 25                    # hot processes
zen swap                           # processes using swap
zen swap-refresh                   # explain swapoff/swapon safety gates
zen swap-refresh --execute         # refresh swap only when RAM headroom is safe
zen docker                         # container classification
zen docker-run --ttl 30m IMAGE     # run labeled Docker container
zen docker-run --ttl 30m --mem 1g --cpu 1 --pids 128 IMAGE
zen watch                          # live pressure loop
zen reap                           # continuously enforce expired owned leases
zen reap --once                    # one TTL enforcement pass
zen leases                         # active Zen leases
zen events                         # recent lifecycle/cleanup events
zen history --record               # record one pressure history snapshot
zen history --json                 # show recent pressure history
zen report                         # redacted host report for fleet collection
zen run --ttl 30m -- command       # run command under a killable Zen lease
zen adopt PID --ttl 30m            # observe-only lease for existing process
zen config --init                  # create editable policy config
```

## Safety Model

Zen can report unknown work, but it can only kill owned work.

Default safety rules:

- `zen clean` is dry-run.
- `zen clean --json` is read-only and cannot be combined with `--execute`.
- `zen clean --execute` can kill only expired leases with verified process
  identity.
- `zen adopt PID` is observe-only unless `--allow-kill` is explicit.
- Docker cleanup requires both Zen ownership labels and `--allow-docker`.
- Heuristic matches are review-only; they are never enough to kill a process.
- Browsers, terminals, desktop/session processes, and active LLM sessions are
  protected by default.

The safety suite validates these invariants with real subprocesses.

## Leases

Launch future work with a TTL:

```bash
zen run --class test --ttl 30m -- pytest
zen run --class agent-scan --ttl 45m -- codex exec "scan this repository"
```

When a Zen-owned lease expires, `zen clean --execute` or `zen reap` may stop
its process group. Before signaling, Zen re-checks the process UID, process
group, session, and Linux start-time tick recorded in the lease. Stale or
hand-edited lease state becomes review-only.

Run the foreground reaper when you want TTLs enforced continuously:

```bash
zen reap --interval 5
```

`zen reap` only executes expired lease actions. Heuristic process matches and
Docker/container actions remain out of scope.

Launch Docker work with Zen labels:

```bash
zen docker-run --ttl 30m --name test-db postgres:16
zen docker-run --ttl 30m --mem 1g --cpu 1 --pids 128 redis:7
```

Only expired containers launched with Zen ownership and expiry labels are
eligible for `zen clean --execute --allow-docker`.

Inspect recent lifecycle and cleanup events:

```bash
zen events
zen events --json --limit 50
```

Record and inspect pressure history when you want evidence for what changed
over time:

```bash
zen history --record
zen history
zen history --json --limit 20
```

History snapshots are compact and redacted by design: pressure, memory/swap,
workload buckets, and top process summaries without command lines or cwd.

Generate a redacted machine report for fleet collection or support handoff:

```bash
zen report > zen-report.json
```

Reports include host pressure, workload buckets, cleanup candidates, leases,
recent events, and recent history. Host name, lease commands, cwd values, and
audit command lines are redacted by default. Use `--verbose` only for trusted
local debugging.

Refresh swap only after Zen proves enough RAM is available to absorb swapped
pages plus a headroom buffer:

```bash
zen swap-refresh
zen swap-refresh --execute
```

Execution uses `sudo -n swapoff -a` followed by `sudo -n swapon -a`, so it
fails fast instead of hanging on a password prompt.

Run the reaper through systemd user units:

```bash
cp packaging/systemd/zen-reap.service ~/.config/systemd/user/
systemctl --user enable --now zen-reap.service
```

The same folder includes a timer for periodic `zen history --record` snapshots.
Details: [docs/SYSTEMD.md](docs/SYSTEMD.md)

Budget metadata can be recorded now:

```bash
zen run --class eval --ttl 2h --mem 8g --cpu 4 --pids 128 -- command
```

When `systemd-run --user --scope` is available, Zen runs budgeted commands in a
transient systemd scope with `MemoryMax`, `CPUQuota`, and `TasksMax` properties.
If systemd is unavailable or disabled with `ZEN_DISABLE_SYSTEMD=1`, Zen tries a
direct cgroup v2 backend when the current cgroup is delegated and writable. If
neither backend is available, the command still runs and the lease records that
budgets were advisory. Set `ZEN_DISABLE_CGROUP=1` to force advisory fallback.

## JSON Output

```bash
zen clean --json
```

The JSON payload includes pressure, load, memory/swap, workload buckets,
recommendations, top CPU, top memory, cleanup candidates, and containers.
Potentially sensitive local details are redacted by default; pass
`--verbose` only when the output will stay local.

Schema: [docs/JSON_SCHEMA.md](docs/JSON_SCHEMA.md)

## Configuration

Create an editable policy file:

```bash
zen config --init
```

Default path:

```text
~/.config/zen/policy.json
```

The config can extend protected command patterns, disposable container review
patterns, ephemeral workload patterns, and pressure thresholds.

## Tests

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Current safety coverage verifies:

- non-owned process kills are blocked before signal delivery
- forged/stale process identities are blocked before signal delivery
- adopted leases without `--allow-kill` survive cleanup
- Zen-owned expired leases can be stopped
- `zen reap` stops expired owned leases but leaves observe-only leases alive
- Docker stops require Zen ownership plus expiry labels and `--allow-docker`
- lifecycle and cleanup events are written to `events.jsonl`
- pressure history snapshots are written to `history.jsonl`
- heuristic ephemeral matches are review-only
- `zen clean --json --execute` is rejected
- swap refresh refuses to execute without enough RAM headroom

## Non-Goals

Zen does not create more RAM, replace Linux memory management, or magically make
large models smaller. It makes AI-agent compute accountable so abandoned work
stops squatting on CPUs, RAM, swap, browsers, Docker, and runners.
