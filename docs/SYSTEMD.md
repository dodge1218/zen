# Systemd User Units

Zen can run its TTL reaper as a user service or as a periodic user timer.

The sample units live in:

```text
packaging/systemd/
```

They use `/usr/bin/env zen`, so `zen` must be on the user service manager's
`PATH`. If it is not, edit `ExecStart` after copying the unit files.

## Continuous Reaper

```bash
mkdir -p ~/.config/systemd/user
cp packaging/systemd/zen-reap.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now zen-reap.service
```

Check status:

```bash
systemctl --user status zen-reap.service
journalctl --user -u zen-reap.service -n 50
```

## Periodic One-Shot Reaper

Use this if you prefer a timer over a continuously running process:

```bash
mkdir -p ~/.config/systemd/user
cp packaging/systemd/zen-reap-once.service packaging/systemd/zen-reap.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now zen-reap.timer
```

Check status:

```bash
systemctl --user list-timers 'zen-*'
journalctl --user -u zen-reap-once.service -n 50
```

## Periodic History Snapshots

Use this when you want a compact local trail for answering "what grew swap?"
after the fact:

```bash
mkdir -p ~/.config/systemd/user
cp packaging/systemd/zen-history.service packaging/systemd/zen-history.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now zen-history.timer
```

The sample timer records one `zen history --record` snapshot every five minutes.
Check status:

```bash
systemctl --user list-timers 'zen-*'
journalctl --user -u zen-history.service -n 50
```

## Login Sessions

User services normally run while the user manager is active. On systems where
you want the reaper to keep running without an open login session, enable user
linger:

```bash
loginctl enable-linger "$USER"
```

## Safety

The reaper executes only expired Zen lease actions. It does not execute
heuristic process actions and does not execute Docker actions.

The history timer records pressure metadata only. It does not execute cleanup.
