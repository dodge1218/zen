# Zen Product Requirements Document

## One-Line Product

Zen is a calm CPU/RAM audit and resource control plane
that gives AI-agent workloads leases, TTLs, resource budgets, cleanup policy,
and observability.

## Problem

AI agents now spawn real workloads:

- shells
- browser automation
- Docker containers
- test runners
- repo scanners
- local model processes
- nested agent sessions
- CI and eval workers

Most of those workloads do not carry durable lifecycle metadata. Once started,
they often outlive the task, user, tab, terminal, PR, or evaluation run that
created them.

The result is predictable:

- local machines fall into swap thrash
- browsers crash before users can save state
- containers remain alive after PoCs finish
- CI runners burn compute on stale work
- platform teams cannot attribute resource use to a task or agent
- users cannot tell what is safe to kill

Existing tools can kill processes, enforce cgroups, or schedule containers. They
do not provide an agent-native lifecycle contract across local shells, browser
workers, Docker, coding agents, and CI-style tasks.

## Target Users

### Primary

- AI coding agent companies
- frontier model labs building agent runtimes
- enterprise agent platform teams
- CI/self-hosted runner operators
- security research teams using agents, browsers, Docker, and PoCs

### Secondary

- power users running local coding agents
- GPU workstation owners
- open-source agent framework maintainers
- browser automation teams
- cloud providers selling AI developer infrastructure

### Not The First Target

Zen is not initially for teams whose primary problem is saturating giant managed
GPU clusters such as 8x H200 training boxes. Those users need schedulers,
orchestrators, quota systems, and GPU telemetry first.

Zen's first wedge is the messy agent workstation/devbox/runner layer: many
small-to-medium CPU/RAM/browser/Docker/tool processes, lots of human context,
and high risk from killing the wrong workflow.

## User Personas

### Brutally Practical Vibe Coder

This user wants one answer:

```text
Why is my machine melting, and what can I kill without losing my tabs or active agents?
```

Needs:

- instant status
- obvious dry-run cleanup
- browser/terminal protection
- no YAML required for first use
- clear "safe to execute" command

### Frontier Runtime Engineer

This user wants agent infrastructure primitives:

- per-agent process accounting
- TTL leases
- resource budgets
- cgroup/Kubernetes enforcement
- audit logs
- policy controls
- integrations with model/tool runtimes

### Platform / FinOps Owner

This user wants to reduce spend:

- abandoned runner detection
- cost attribution by agent/task/user/repo
- automatic cleanup of expired work
- reports for waste and prevented burn
- team-level policy enforcement

### Security Researcher

This user wants to keep high-churn workflows safe:

- preserve browsers and terminals
- identify PoC containers
- clean repo scan/build/test leftovers
- avoid killing active security research work
- keep a trail of what was cleaned and why

## Product Goals

1. Make agent-spawned workloads accountable.
2. Keep local and fleet machines responsive under AI workload churn.
3. Prevent stale agents from burning CPU, RAM, swap, Docker, browser, and GPU
   resources.
4. Give users safe cleanup without requiring deep Linux process knowledge.
5. Establish leases as the default lifecycle primitive for AI agents.

## Non-Goals

- Replace Linux memory management.
- Promise magical RAM compression.
- Kill arbitrary user processes.
- Replace Kubernetes, systemd, Docker, or cgroups.
- Become a generic consumer "PC cleaner."

## MVP Requirements

### CLI

Required commands:

- `zen status`
- `zen doctor`
- `zen ps`
- `zen swap`
- `zen docker`
- `zen clean`
- `zen clean --json`
- `zen clean --execute`
- `zen run --ttl ... -- command`
- `zen adopt PID --ttl ...`
- `zen config --init`
- `zen leases`
- `zen watch`

The human-facing command should be `zen`, for example:

```bash
zen clean
```

`zen clean` must feel like a safe audit command, not a dangerous cleaner.

### Scanner

Must collect:

- memory totals
- swap usage
- load averages
- process tree
- process RSS
- per-process swap
- sampled CPU
- process command line
- process cwd where readable
- Docker container names/images/status

### Classifier

Must classify:

- protected desktop/session processes
- protected browsers
- protected terminal sessions
- protected active LLM sessions
- agent processes
- known ephemeral build/test/PoC work
- known protected containers
- known disposable PoC containers

### Lease System

`zen run` must:

- start a command in a distinct process group
- record command, pid, pgid, class, cwd, start time, and TTL
- record CPU, memory, and process-count budgets when provided
- enforce budgets through `systemd-run --user --scope` when available
- clean dead leases from state
- refuse to start new leased work under red/black pressure unless forced

`zen adopt` must:

- attach lease metadata to an already-running process
- record pid, pgid, command, class, cwd, start time, and TTL
- warn when the adopted process is currently protected
- preserve the invariant that protected processes are not killed by cleanup
- default to observe-only unless `--allow-kill` is explicit

### Safety Guarantee

Default cleanup must not be able to brick active workflows.

Required invariant:

```text
Zen can report unknown work, but it can only kill owned work.
```

`zen clean --execute` may kill only expired `zen run` leases or adopted leases
that were explicitly created with `--allow-kill`. Heuristic matches must remain
review-only. Docker stops require `--allow-docker`.

### Policy Config

Zen must support an editable user policy file:

```text
~/.config/zen/policy.json
```

The config must allow users to extend or override:

- protected process names
- protected command substrings
- ephemeral command substrings
- ephemeral cwd prefixes
- disposable container names/images
- protected container names
- pressure thresholds

### Cleanup

`zen clean` must:

- be dry-run by default
- support `--json` for machine-readable reporting
- reject `--json --execute`
- print pressure, load, RAM, swap, workload buckets, recommendations, top CPU,
  top memory, and cleanup candidates
- print planned actions and reasons
- avoid protected processes
- stop expired leased process groups
- stop known disposable containers
- require `--execute` to mutate system state

## Future Requirements

### Enforcement

- direct cgroup v2 memory limits
- direct CPU quotas
- direct process count caps
- wall-clock TTL enforcement
- Kubernetes/job backend
- Docker/container backend

### Accounting

- per-user usage
- per-agent usage
- per-task usage
- per-repo usage
- prevented-spend estimates
- historical pressure timelines

### Integrations

- Codex
- Claude Code
- Cursor/Windsurf/Cline-style IDE agents
- GitHub Actions self-hosted runners
- Buildkite/CircleCI/GitLab runners
- browser automation stacks
- Docker and Compose
- Kubernetes
- Slack/Discord/desktop notifications

### Fleet Product

- central policy server
- local agents on each host
- team-level dashboards
- audit logs
- cleanup approvals
- budget policy by user/team/repo
- anomaly detection for stuck agent loops

## Success Metrics

Local:

- time to identify top RAM/swap offenders
- number of protected active sessions preserved
- number of stale workloads cleaned safely
- reduction in manual process hunting

Fleet:

- compute hours saved
- stale runner/container lifetime reduction
- percentage of agent jobs launched with leases
- resource attribution coverage
- incident MTTR reduction for agent-induced pressure

## Positioning

Bad positioning:

```text
RAM cleaner
swap optimizer
process killer
```

Good positioning:

```text
agent workload leases
resource accounting for AI agents
safe reaping for autonomous dev environments
runtime governance for agentic compute
```

## Ideal First-Screen GitHub Message

```text
AI agents spawn processes, browsers, containers, and test runners.
Most of those jobs have no owner, TTL, or cleanup policy.
Zen gives them leases.
```

## Target Outreach Thesis

The right buyer already has agent-spawned compute waste. The email should not
sell a local utility. It should sell a missing runtime primitive:

```text
Every agent job should have an owner, TTL, resource budget, and cleanup policy.
Zen is the open-source reference implementation.
```
