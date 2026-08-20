# shipgate configuration — pandora

Project configuration for the `shipgate` plugin. Skills read this at the start of a flow;
it overrides their built-in defaults. Written by `/shipgate:setup` on 2026-08-20 —
re-run it to change the journal or artifact homes rather than hand-editing those.

pandora is a **plugin marketplace**: one git repo holding several independent plugins
(`shipgate/`, `astrolabe/`, `bpmn/`), each its own deliverable with its own version.

## Knowledge base

- PRD home: `<plugin>/docs/prd/` — artifacts live with the plugin they describe, not in a
  shared top-level folder, because each plugin ships and versions separately.
- ADR home: `<plugin>/docs/adr/` — sequential `NNNN-<title>.md`. Single-writer repo, so
  sequential numbering is safe here.
- Worklog home: beside the PRD as `<name>.worklog.md`.
- Page conventions: the plugin's own templates —
  `shipgate/skills/clarify/references/prd-template.md`,
  `shipgate/skills/design/references/adr-template.md`,
  `shipgate/skills/design/references/worklog-template.md`. Frontmatter as those define.
- Ledger: `docs/ledger.md` (repo root, shared across plugins). Promotion targets at triage:
  plugin behaviour and conventions → the relevant `<plugin>/README.md` or its skill files;
  decisions → that plugin's ADR home; personal workflow preferences → Claude's built-in
  memory; everything else → drop.

## Journal

- Database: `.claude/shipgate.db`

## Forge & tracker

- Forge: GitHub — CLI: `gh`, pull requests.
- Issue tracker: GitHub issues on this same repo (`worm2fed/pandora`). Much of the work
  here is ad-hoc with no issue; that is fine — the branch and PR carry the context.
- Integration branch: `main`.
- Title/body rules: state which plugin a change targets, since one repo ships several.
  A version bump belongs in the same PR as the change that earns it — both
  `<plugin>/.claude-plugin/plugin.json` and the matching entry in
  `.claude-plugin/marketplace.json`, kept in lockstep.

## Branching

- Pattern: `<type>/<slug>`, type ∈ feat | fix | chore. The issue id is optional here and
  usually absent — include it as `<type>/<issue-id>-<slug>` when an issue does exist.
- Examples: `feat/sqlite-journal`, `fix/hook-fast-path`, `chore/bump-astrolabe`.

## Security-sensitive areas

- **Anything under a plugin's `hooks/`.** Plugin hooks execute on the user's machine in
  every project they open, so a defect here has a blast radius far beyond this repo.
  Changes to hook scripts or `hooks/*.json` get the full `/security-review`, and the
  no-op-when-not-applicable path is treated as a correctness requirement, not an
  optimization.
- Anything that reads or writes outside the plugin's own directory.

## Autonomy

- Mode: executive
- Executive contract: the orchestrator makes and RECORDS routine decisions itself —
  clarify answers land in the PRD's "Assumptions (executive)" list, design choices in the
  ADR, small calls in the ledger — and reports them in each phase summary so they can be
  vetoed. It still escalates: one-way doors, user-visible scope changes, anything in
  Security-sensitive areas above, and genuine 50/50s where it cannot form a recommendation.
- Extra escalations: publishing — a version bump released to the marketplace, or anything
  that changes what an already-installed plugin does on someone else's machine. Also any
  change to the hook contract itself (which events fire, what can block a session).
