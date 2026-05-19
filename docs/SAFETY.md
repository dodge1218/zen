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

## Docker Contract

Docker cleanup is blocked by default, even under `--execute`.

This command audits and reports matching containers:

```bash
zen clean --execute
```

This command allows Docker stops:

```bash
zen clean --execute --allow-docker
```

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
- The known kind PoC container was not stopped by `zen clean --execute` because
  `--allow-docker` was not present.
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
