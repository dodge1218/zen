# Safety Guarantees

Zen must be useful to people running expensive active workflows. That means
the default command must not brick a browser session, terminal session, live
agent, Docker service, or research run.

## Default Contract

The normal command is:

```bash
zen clean
```

It performs a CPU/RAM audit and prints a cleanup plan. It does not mutate
anything.

The audit includes:

- pressure level
- load averages
- RAM and swap usage
- workload buckets
- protected top CPU/memory users
- recommendations
- cleanup candidates

Recommendations are advisory. They do not bypass the execution gates below.

Machine-readable audit mode is also read-only:

```bash
zen clean --json
```

Zen refuses to combine JSON reporting with execution:

```bash
zen clean --json --execute
```

## Execute Contract

Even with:

```bash
zen clean --execute
```

process kills are allowed only when all of these are true:

- the action targets an expired lease
- the lease was created by `zen run`, or adopted with explicit `--allow-kill`
- the lease has `allow_kill=true`
- the target process is not protected
- the current process identity matches the lease identity
- the target process group is valid and not a system group

This means heuristic matches are never enough to kill a process.

## Reaper Contract

`zen reap` is the foreground TTL enforcement loop:

```bash
zen reap --interval 5
```

It executes only expired lease actions that already satisfy the process
ownership checks above. It does not execute heuristic process actions and does
not execute Docker actions.

## Adopt Contract

This is observe-only by default:

```bash
zen adopt PID --ttl 20m
```

When the TTL expires, Zen reports the stale process but does not kill it.

To make an adopted process killable, the user must explicitly opt in:

```bash
zen adopt PID --ttl 20m --allow-kill
```

## Budget Contract

Budget flags on `zen run` are enforced only when Zen can launch the command via:

```bash
systemd-run --user --scope
```

In that mode Zen applies:

- `--mem` as `MemoryMax`
- `--cpu` as `CPUQuota`
- `--pids` as `TasksMax`

If systemd-run is unavailable or `ZEN_DISABLE_SYSTEMD=1` is set, Zen still
starts the command and records the budget as advisory in lease runtime metadata.
The CLI prints whether the budget was `enforced` or `advisory`.

## Lease Store Contract

Lease state is written with an exclusive file lock and atomic rename. Concurrent
Zen invocations should not clobber each other's lease records. If the lease
store cannot be parsed as JSON, Zen moves it aside as
`leases.json.corrupt-*`, warns on stderr, and starts from an empty lease set.
That fails closed for cleanup because corrupted lease ownership is not trusted.

## Event Log Contract

Zen writes local JSONL lifecycle events to:

```text
~/.local/state/zen/events.jsonl
```

The log records lease creation, dead-lease pruning, corrupt lease quarantine,
blocked actions, and executed actions. It is local operational evidence, not a
remote telemetry stream.

## Docker Contract

Docker cleanup is blocked by default, even under `--execute`.

This command audits and reports matching containers:

```bash
zen clean --execute
```

This command allows Docker stops only for containers carrying Zen ownership
metadata:

```bash
zen clean --execute --allow-docker
```

The required label is:

```text
io.github.dodge1218.zen.managed=true
```

Zen-owned containers also need a valid expired label:

```text
io.github.dodge1218.zen.expires_at=<unix timestamp>
```

`zen docker-run --ttl ...` applies these labels automatically. Name/image
matches from policy are review-only. They do not become executable Docker stops.

## Protected Workflows

Zen protects these by default:

- Brave
- Chrome / Chromium
- terminal emulators
- desktop/session processes
- Ollama
- active Codex and Claude sessions

## Sandbox Test Evidence

Validated by automated tests in `tests/test_safety.py`:

- An adopted `sleep` process without `--allow-kill` survived
  cleanup execution.
- A `sleep` process started by `zen run --ttl 1s` was stopped after expiry.
- The TTL reaper stopped an expired owned lease while leaving an expired
  observe-only lease alive.
- Corrupt lease state was quarantined instead of trusted.
- Lease creation and corrupt-state handling wrote local events.
- Non-owned Docker stops were blocked, even when `--allow-docker` was present.
- Unexpired Zen-owned containers were not stopped.
- Disposable-looking containers produced review actions, not executable stops.
- A synthetic non-owned kill action was blocked before signal delivery.
- A forged/stale process identity was blocked before signal delivery.
- A stale leased process identity became review-only instead of executable.
- Heuristic ephemeral process matches produced review actions, not kill actions.
- `zen clean --json --execute` is rejected.

Run:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

The invariant:

```text
Zen can report unknown work, but it can only kill owned work.
```
