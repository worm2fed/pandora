# Ledger

Quick learnings, one dated line each; triaged at each feature's Capture phase
(see `shipgate/skills/knowledge-base/SKILL.md`).
- 2026-10-08 — gotcha: an orchestrator committed a fix before the review verdict "to give reviewers a stable ref"; the review skill could say to brief reviewers with the working-tree diff (`git diff <base>`) and commit only after `review-verdict: ready`.
- 2026-10-12 — gotcha: a shared helper script in the session scratchpad was overwritten by a worker mid-run (parity.py); give workers a copy, or keep orchestrator tools in a directory the brief never names as writable.
