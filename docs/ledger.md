# Ledger

Quick learnings, one dated line each; triaged at each feature's Capture phase
(see `shipgate/skills/knowledge-base/SKILL.md`).

- 2026-09-26 — Skill descriptions written around the flow's phases ("first step of any feature", "final pre-push review") never auto-trigger on natural asks; ones written around what the user asks plus the capability a plain read cannot give (per-file fix history, blast radius) fire 3/3. A negative trigger ("not for a trivial one-line edit") kept the negative eval at 0/3. Promoted: shipgate v0.13.1 descriptions + CHANGELOG.
- 2026-09-26 — `claude plugin eval` gotchas on this machine (git shim, credential-store symlinks, which account pays, nested `claude`) are encoded in `.claude/skills/run-evals`; do not re-derive. Promoted: that skill.
- 2026-09-26 — A `claude -p --plugin-dir <plugin> --setting-sources "" --strict-mcp-config` session lists exactly the plugin's skills as `<plugin>:<skill>` + description and nothing else from the plugin (no README, no hooks output) — the description is the whole triggering surface; cap 1,536 chars.
