# shipgate — a production project

This repo is a monorepo of three services. The flow runs inside each service, never at the
root, because each service ships on its own schedule.

## Knowledge base

- PRD home: `docs/prd/`
- ADR home: `docs/adr/` — numbered `NNNN-<title>.md`.
  <!-- numbering is sequential because one person writes ADRs here. -->
- Worklog home: beside the PRD as `<name>.worklog.md`.

## Forge & tracker

- Forge: GitLab — CLI: `glab`, merge requests.
- Issue-link form: `group/project#1234`.

## Branching

- Pattern: <type>/<slug>
- Examples: `feat/x`, `fix/1290-date-off-by-one`.

## Code signals

- Window: `6`
- Exclude: `generated/`

The values above are tuned for a young repo; widen the window once it has a year of history.

## Release train

- Cadence: every second Tuesday.
- Owner: user@alice

```markdown
- Window: `3`
- Mode: <ask | executive>
<!-- Default when absent: this fence is an example, not config. -->
```

## Autonomy

- Mode: ask
- Extra escalations: any change to the billing export.
