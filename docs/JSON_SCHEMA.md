# `zen clean --json` Schema

`zen clean --json` emits a read-only audit document. It cannot be combined with
`--execute`, so consumers can collect this payload from active developer
machines, CI runners, or agent workers without granting cleanup authority.
Command lines, cwd values, and container details are redacted by default. Use
`zen clean --json --verbose` only for trusted local debugging.

## Stability

Current schema version:

```text
1
```

Backwards-compatible additions may add fields. Removing fields or changing field
types requires a schema version bump.

## Top-Level Object

```json
{
  "schema_version": 1,
  "pressure": "yellow",
  "load": {},
  "memory": {},
  "workloads": [],
  "recommendations": [],
  "top_cpu": [],
  "top_memory": [],
  "actions": [],
  "containers": []
}
```

Fields:

- `schema_version`: integer schema version.
- `pressure`: one of `green`, `yellow`, `red`, `black`.
- `load`: load averages.
- `memory`: host memory and swap summary.
- `workloads`: grouped process buckets.
- `recommendations`: advisory messages. They do not bypass safety gates.
- `top_cpu`: top sampled CPU processes.
- `top_memory`: top RSS processes.
- `actions`: cleanup candidates. These are not executed in JSON mode.
- `containers`: visible Docker containers.

## `load`

```json
{
  "1m": 1.23,
  "5m": 2.34,
  "15m": 3.45
}
```

## `memory`

```json
{
  "mem_total_kb": 16119004,
  "mem_available_kb": 9000000,
  "swap_total_kb": 10485752,
  "swap_used_kb": 4000000,
  "swap_used_pct": 38.1
}
```

## `workloads[]`

```json
{
  "name": "agents",
  "count": 12,
  "cpu_pct": 142.3,
  "rss_kb": 1200000,
  "swap_kb": 800000
}
```

Known workload names:

- `agents`
- `browsers`
- `docker/kube`
- `terminals`
- `desktop`
- `build/tools`
- `kernel/system`
- `services`
- `other`

CPU can exceed `100.0` because it is summed across processes and CPU cores.

## `recommendations[]`

```json
{
  "level": "review",
  "message": "Agent CPU is the top pressure source; inspect active coding-agent runs before stopping anything."
}
```

Known levels:

- `ok`
- `watch`
- `review`
- `protect`
- `optional`
- `safe`

Recommendations are advisory. Execution is controlled only by action kind,
ownership metadata, `--execute`, `--allow-docker`, and `--allow-kill`.

## `top_cpu[]` / `top_memory[]`

```json
{
  "pid": 1234,
  "ppid": 1,
  "pgid": 1234,
  "name": "codex",
  "state": "S",
  "rss_kb": 100000,
  "swap_kb": 50000,
  "cpu_pct": 35.5,
  "cmdline": "<redacted>",
  "cwd": null,
  "tags": ["agent", "protect"],
  "protected": true
}
```

`cwd` may be `null` when the process directory is not readable.

## `actions[]`

```json
{
  "kind": "docker-stop",
  "target": "<redacted>",
  "reason": "PoC/ephemeral container: kindest/node:v1.35.0",
  "command": null,
  "pids": [],
  "risk": "safe",
  "meta": {}
}
```

Known action kinds:

- `review`: report-only; never executes.
- `kill-tree`: executable only for Zen-owned expired leases.
- `docker-stop`: executable only for expired Zen-owned containers when
  `--allow-docker` is present.

Known risk values:

- `safe`
- `normal`
- `review`
- `blocked`

## `containers[]`

```json
{
  "container_id": "<redacted>",
  "name": "<redacted>",
  "image": "<redacted>",
  "status": "Up 2 days"
}
```

Container presence in JSON does not imply Zen will stop it. Docker cleanup
requires Zen ownership/expiry labels and `zen clean --execute --allow-docker`.
