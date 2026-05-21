# Market And Competitor Map

This file intentionally separates Zen/RamLM from ContextClaw.

Zen/RamLM is hardware and workload hygiene: CPU, RAM, swap, Docker, cgroups,
leases, TTLs, and safe cleanup of agent-spawned work.

ContextClaw is context hygiene: ongoing control of prompt/context growth,
receipts, cold storage, model spend, and leak prevention inside agent workflows.

They are related because the same users feel both pains, but they should not be
combined in positioning.

## Zen/RamLM Competitors And Adjacent Projects

### Generic Linux Resource Control

- `systemd-run`, systemd scopes, systemd slices
- cgroups v2 direct filesystem controls
- `cgexec`, `cgset`, and libcgroup-style tooling
- `lmt` and similar cgroup-v2 resource-limit wrappers
- Docker, Podman, Kubernetes resource limits
- JupyterHub/SystemdSpawner-style per-user or per-session limits
- HPC/user fair-share systems such as Arbiter-style resource managers

Assessment: mature primitives, not agent-native products. They enforce
resources, but they do not understand AI-agent task lifecycle, stale runs,
browser/terminal protection, Docker TTL labels, or safe cleanup explanation.

### System And Process Monitors

- `top`, `htop`, `btop`
- `atop`
- `glances`
- `denet`
- Prometheus/node-exporter/Grafana style host monitoring
- Netdata and local observability dashboards

Assessment: strong visibility, weak intent. They show what is hot, but they do
not answer "what is safe to stop?" for agent-spawned work.

### AI Coding Agent Monitors

- AgentWatch
- AgentGlance
- lazyagent
- agentpulse
- agentop
- AI Usage Monitor

Assessment: closer to the user pain. These focus on agent sessions, status,
tokens, costs, approvals, and dashboards. Most do not act as an OS-level local
resource lifecycle and cleanup plane.

### Token And Cost Trackers

- Token Tracker
- Token Use
- ccusage
- TokenBBQ
- budi
- OpenCode Monitor

Assessment: competes more with ContextClaw than Zen/RamLM. Useful for spend and
usage attribution, but not enough for a machine that is melting from orphaned
processes, Docker containers, browsers, and swap.

### AI-Agent Resource Research

- AgentRM-style OS-inspired resource managers for LLM agent systems
- AgentCgroup-style work on OS resources for AI agents
- AgentSight/eBPF-style system observability for agents
- AIOS and agent operating-system research

Assessment: validates the category. Research is likely ahead on framing and
benchmarks, but not necessarily on a small usable local CLI for developers.

## ContextClaw Competitors And Adjacent Projects

### LLM Observability And Eval Platforms

- LangSmith
- Langfuse
- Helicone
- Braintrust
- Laminar
- Lunary
- Portkey
- OpenObserve LLM observability
- OpenTelemetry/OpenInference-based tracing stacks

Assessment: mature category for apps, traces, evals, and teams. ContextClaw
should avoid competing head-on as "another observability dashboard." Its sharper
lane is local-first agent context governance and workflow receipts.

### Agent Memory And Context Systems

- Mem0
- Letta
- MemoryOS
- MemMachine
- MemFactory
- Pieces-style developer memory
- RAG/chunking/memory frameworks embedded in agent stacks

Assessment: overlaps with long-term memory, retrieval, and personalization.
ContextClaw's distinction should be control, compression, receipts, cold
storage, spend reduction, and preventing context leaks rather than trying to be
the agent's semantic memory.

### AI Coding Usage And Session Tools

- Token Tracker
- Token Use
- ccusage
- TokenBBQ
- budi
- AgentGlance
- AgentWatch
- lazyagent
- agentpulse

Assessment: these overlap on local session visibility, cost, and workflow
monitoring. ContextClaw needs stronger claims around intervention: what it
prevents, trims, archives, or routes differently.

## Positioning Implications

Zen/RamLM should be framed as:

> Local resource hygiene for AI-agent workflows. See, lease, limit, and safely
> clean up agent-spawned CPU/RAM/swap/Docker work without killing browsers,
> terminals, or active sessions.

ContextClaw should be framed as:

> Local-first context governance for AI-agent workflows. Keep context useful,
> auditable, and cheap by routing, compressing, archiving, and proving what was
> kept or dropped.

The shared umbrella can be "AI workflow hygiene," but the products solve
different failure modes:

- Zen/RamLM catches the 50 GB download, runaway tests, orphan Docker, swap
  pressure, and zombie subagent shells.
- ContextClaw catches runaway context, repeated prompt bloat, expensive
  forgotten history, hidden state leakage, and bad handoffs.

## GTM Notes

Best initial wedge for Zen/RamLM:

- Linux power users running multiple AI coding agents locally.
- Developers who keep browsers, Docker, terminals, and subagents open all day.
- AI security researchers and audit-heavy developers who run lots of throwaway
  tools.
- DevOps/SRE people who understand cgroups but want agent-specific lifecycle
  policy.
- Local-first AI tool builders looking for integrations.

Best initial wedge for ContextClaw:

- Heavy Claude/Codex/Gemini/OpenCode users with obvious token/context waste.
- People building repeatable agent workflows, skills, or SOPs.
- AI coding teams that need local receipts and context discipline before
  adopting heavier observability platforms.

Content angle:

> I went from a 250% overclocked ThinkPad meltdown to roughly 1.2 cores used
> while keeping 11 terminals, Discord, Brave, Chrome browser automations, and
> multiple subagents open.

That story should lead with before/after screenshots, `zen clean`, `zen
explain`, `zen history`, and concrete numbers. The credibility comes from the
machine surviving a messy real workflow, not from claiming to invent cgroups.
