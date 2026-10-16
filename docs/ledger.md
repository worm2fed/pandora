# Ledger

Quick learnings, one dated line each; triaged at each feature's Capture phase
(see `shipgate/skills/knowledge-base/SKILL.md`).
- 2026-10-15 — followup (shipgate): journal.py has no actor authentication. `--actor user` and a `raised_by: user` publish gate-decision are free for the model to write, so a flow can satisfy the `mr-opened` rule itself. shipgate-hud's README states the gate is a net, not a boundary. Candidate: a shipgate hook that refuses a Bash `journal.py append` carrying `raised_by: user` / `--actor user`, or a journal column set only from a real dialog. Needs an issue.
- 2026-10-15 — followup (shipgate review skill): when it records `review-verdict`, also write `criteria: {"SC-001": "met"|"unmet"}` and `dispositions: {"<short file>:<line|?>": "fixed"|"rejected"|"deferred"}` (compact, under the 1 KB payload cap). shipgate-hud 0.4.1+ draws both; until the skill writes them the orchestrator adds the fields by hand. Needs an issue.
- 2026-10-15 — followup (shipgate-hud): a PNG form of the flowchart for users on kitty/Ghostty, with the box-drawing grid as the alt so a multiplexer still gets the picture in text. The measurement behind it is in ADR 0003. Needs an issue.
