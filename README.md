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
- dry-run cleanup by default
- protected browsers, terminals, desktop processes, and active LLM sessions
- leases with TTLs for agent/build/test work
- locked, atomic lease-state writes for concurrent agent runs
- observe-only adoption for already-running processes
- CPU/RAM/process-count budgets via systemd-run when available
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
zen clean                          # CPU/RAM audit + dry-run cleanup
zen clean --json                   # machine-readable audit, never executes
zen clean --execute                # execute only Zen-owned expired leases
zen clean --execute --allow-docker # additionally allow matching Docker stops
zen ps --top 25                    # hot processes
zen swap                           # processes using swap
zen docker                         # container classification
zen watch                          # live pressure loop
zen leases                         # active Zen leases
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
- Docker cleanup requires `--allow-docker`.
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

When a Zen-owned lease expires, `zen clean --execute` may stop its process
group. Before signaling, Zen re-checks the process UID, process group, session,
and Linux start-time tick recorded in the lease. Stale or hand-edited lease
state becomes review-only.

Budget metadata can be recorded now:

```bash
zen run --class eval --ttl 2h --mem 8g --cpu 4 --pids 128 -- command
```

When `systemd-run --user --scope` is available, Zen runs budgeted commands in a
transient systemd scope with `MemoryMax`, `CPUQuota`, and `TasksMax` properties.
If systemd is unavailable or disabled with `ZEN_DISABLE_SYSTEMD=1`, the command
still runs and the lease records that budgets were advisory.

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

The config can extend protected command patterns, disposable container names,
ephemeral workload patterns, and pressure thresholds.

## Tests

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Current safety coverage verifies:

- non-owned process kills are blocked before signal delivery
- forged/stale process identities are blocked before signal delivery
- adopted leases without `--allow-kill` survive cleanup
- Zen-owned expired leases can be stopped
- Docker stops require `--allow-docker`
- heuristic ephemeral matches are review-only
- `zen clean --json --execute` is rejected

## Roadmap

- direct cgroup v2 backend for hosts without user systemd
- process-count enforcement
- historical pressure logs
- desktop notifications
- fleet policy/reporting mode
- cgroup-owned Docker/container cleanup metadata

## Non-Goals

Zen does not create more RAM, replace Linux memory management, or magically make
large models smaller. It makes AI-agent compute accountable so abandoned work
stops squatting on CPUs, RAM, swap, browsers, Docker, and runners.
