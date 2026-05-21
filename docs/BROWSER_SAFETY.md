# Browser Safety

Zen treats browsers as protected user context, not disposable workload.

The project should not add automatic browser cleanup by default. Browser tabs,
profiles, automation sessions, and crash recovery state are too likely to
contain unsaved work. Zen may report browser memory and swap pressure, but the
user remains responsible for deciding what to close.

Current stance:

- Browser processes are protected by default.
- `zen clean --execute` does not close browsers.
- Heuristic cleanup must not promote browser matches to executable actions.
- Future browser integrations should be documentation or explicit export tools,
  not implicit cleanup gates.
