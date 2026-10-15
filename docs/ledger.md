# Ledger

Quick learnings, one dated line each; triaged at each feature's Capture phase
(see `shipgate/skills/knowledge-base/SKILL.md`).
- 2026-10-15 — shipgate: journal.py has no actor authentication. `--actor user` fills the actor column only, and `raised_by: user` in a gate-decision payload is free for the model to write, so a publish gate-decision "by the user" can be appended by the orchestrator itself and satisfies the `mr-opened` rule. shipgate-hud's publish gate treats the journal as a net for a forgetful model, not a boundary (found by its security review). Candidate: a shipgate hook that refuses a Bash `journal.py append` carrying `raised_by: user` / `--actor user`, or a journal column the hook sets only from a real dialog.
- 2026-10-15 — shipgate review skill: when it records `review-verdict`, also write `criteria: {"SC-001": "met"|"unmet"}` and `dispositions: {"<short file>:<line|?>": "fixed"|"rejected"|"deferred"}` (compact, under the 1 KB payload cap). shipgate-hud 0.4.1 draws both (pre-ticked criteria, per-card disposition) and counts a finding open only without one; until the skill writes them the orchestrator adds the fields by hand.
