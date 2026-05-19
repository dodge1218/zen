# Zen TODO

- Add cgroup/systemd-run support for hard RAM/CPU ceilings on leased commands.
- Rename internal package/module paths from `ramlm` to `zen` once the public API settles.
- Add optional desktop notifications when pressure reaches red or black.
- Add a swap refresh helper that explains `sudo swapoff -a && sudo swapon -a`
  and refuses to run unless RAM headroom is adequate.
- Add a protected-tab/browser session snapshot hook before any browser cleanup.
- Add historical logging so we can answer "what grew swap?" after the fact.
