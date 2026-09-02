# CLAUDE.md — pandora

pandora is a **public** plugin marketplace (`shipgate/`, `astrolabe/`, `bpmn/`). Each plugin
is its own deliverable with its own version; its `README.md`, `CHANGELOG.md` and
`.claude-plugin/plugin.json` are authoritative for what it does.

## Public repo — nothing employer- or customer-specific

Everything committed here is world-readable. Plugins are developed against private
projects, and evidence from those projects is what improves them — but the evidence must
not travel into the repo. Never write into any file here (docs, skills, agents, tests,
fixtures, examples, ADRs, PRDs, worklogs, changelogs, commit messages):

- an employer, customer, product or project name, or its domain / hostname;
- a tracker reference from a private project (issue ids, MR/PR numbers,
  epic slugs, board names);
- branch or stream names, file paths, repo names or usernames from a private checkout;
- people's names or handles (including the maintainer's, in fixtures);
- incident details specific enough to identify the project.

Write the generic form instead: "a production project", "the reference export", `#1234`,
`feature/x`, `fix/1290-date-off-by-one`, `user@alice`. Measurements from private journals
are fine as **counts and sizes only**. Raw exports and any file that carries private data
live outside the repo (the session scratchpad, or `.claude/` which is gitignored for the
journal db only — check before assuming).

Before finishing any change, grep the diff for the private project's name, its tracker id
pattern and its paths; treat a hit as a blocker, not a nit.

## Working here

- Plugins are independent: read the plugin's own `README.md` / `CHANGELOG.md` before
  editing it; do not assume one plugin's conventions apply to another.
- shipgate's flow config for this repo is `.claude/shipgate.md`; the journal is
  `.claude/shipgate.db` (local, gitignored).
- A behaviour change to a plugin bumps its version in `<plugin>/.claude-plugin/plugin.json`
  and the matching entry in `.claude-plugin/marketplace.json`, in the same change.
- Hooks under `<plugin>/hooks/` run on every user's machine in every project they open:
  the no-op-when-not-applicable path is a correctness requirement.
