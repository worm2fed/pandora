# shipgate configuration — a production project

Project configuration for the `shipgate` plugin. Skills read this at the start of a flow;
it overrides their built-in defaults. Written by `/shipgate:setup` on 2026-09-01 —
re-run it to change the journal or artifact homes rather than hand-editing those. This
checkout is an umbrella over several service repos. The real repos live under `services/`.

## Code signals

<!-- Read by `shipgate/scripts/signals.py` itself (v0.14+): backticked values only, flags
     win. Defaults when absent: 12-month window, built-in fix pattern, built-in excludes. -->

- Window: `12`

## Autonomy

- Mode: ask
