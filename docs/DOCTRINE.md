# Zen Doctrine

## Core Doctrine

Agent workloads must not be immortal.

Every AI-spawned process should have:

- owner
- task id
- class
- TTL
- resource budget
- cleanup policy
- audit trail

If a workload cannot declare those fields, it should be treated as unmanaged
risk.

## The Shift

Old world:

```text
Humans start jobs. Humans remember jobs.
```

New world:

```text
Agents start jobs. Agents spawn subjobs. Context disappears.
```

That shift breaks the old assumption that the person at the terminal knows what
is running and why.

## Local Principle

On a workstation, Zen should answer:

```text
What is melting the machine?
What is protected?
What is disposable?
What can be cleaned safely?
```

A local user should not need to understand Linux process trees to avoid killing
their browser, terminal, or active LLM session.

## Fleet Principle

At scale, Zen should answer:

```text
Which agent burned compute?
Which task owned it?
Was it still useful?
Why was it allowed to keep running?
What policy should stop it next time?
```

Fleet Zen is less about RAM and more about agent accountability.

## Market Doctrine

The market will initially misread the product as a memory cleaner. Correct that
immediately.

Zen is not:

- a RAM booster
- a cleaner app
- a replacement for the Linux kernel
- a generic task manager

Zen is:

- an agent workload lease manager
- a cleanup policy layer
- an observability layer for agent-spawned compute
- a bridge between AI tools and real infrastructure controls

## Why Existing Tools Are Not Enough

Systemd, cgroups, Docker, Kubernetes, and process managers already exist. The
gap is not enforcement machinery. The gap is that AI agent runtimes do not
consistently use that machinery with task-native metadata.

Zen should sit at the semantic layer:

```text
agent/task intent -> resource contract -> operating-system enforcement
```

## Safety Doctrine

Default posture:

- observe before acting
- dry-run before cleanup
- protect user state first
- never kill browsers by default
- never kill terminals by default
- never kill active LLM sessions by default
- prefer leased cleanup over heuristic cleanup

The product earns trust by not being clever with destructive actions.

## Developer Experience Doctrine

The vibe coder experience must be simple:

```bash
zen status
zen doctor
zen clean
```

The frontier developer experience must be composable:

```bash
zen run --class eval --ttl 2h --budget-mem 8g --budget-cpu 4 -- command
```

The same product must serve both:

- immediate "what is killing my machine?"
- long-term "how do we govern 10,000 agent jobs?"

## Open Source Doctrine

GitHub should communicate value within one screen:

1. AI agents spawn unmanaged work.
2. Unmanaged work burns memory, CPU, browsers, containers, runners, and money.
3. Zen gives agent work leases, budgets, visibility, and cleanup.
4. The CLI is local today.
5. The category is fleet agent resource governance tomorrow.

## Enterprise Doctrine

The enterprise buyer does not buy "less swap." They buy:

- fewer abandoned workers
- lower cloud burn
- resource attribution
- policy enforcement
- auditability
- safer autonomous agents
- incident response for agent-induced resource pressure

## Frontier Company Doctrine

Frontier companies need Zen because agent systems recursively create work.

Required primitives:

- per-agent accounting
- task-bound leases
- cgroup/container isolation
- budget-aware scheduling
- cleanup approvals
- reproducible audit logs
- integration hooks across shells, browsers, containers, CI, and model runtime

The mature product is a resource control plane for agentic compute.

## Category Claim

Zen should help define this category:

```text
Agent Runtime Governance
```

Alternative phrases:

- AgentOps resource control
- AI workload leases
- agent compute accountability
- safe reaping for autonomous dev environments

## Outreach Doctrine

Do not lead with:

- memory manager
- swap cleaner
- local CLI
- RAM optimizer

Lead with:

- agent workload leases
- TTL and cleanup policy for autonomous coding agents
- resource accounting for agent-spawned processes
- safe reaping for AI dev environments
- preventing abandoned agent jobs from burning cloud and devbox resources

## Top Buyer Classes

- AI coding agent companies
- frontier model labs
- enterprise agent platforms
- CI/self-hosted runner companies
- AI cloud/GPU providers
- browser automation companies
- security research organizations
- open-source agent framework maintainers

## One-Sentence Thesis

Zen makes AI agents lease memory and compute instead of squatting on it
forever.
