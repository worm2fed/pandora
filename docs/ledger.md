# Ledger

Quick learnings, one dated line each; triaged at each feature's Capture phase
(see `shipgate/skills/knowledge-base/SKILL.md`).
- 2026-11-02 — gotcha: eval graders over `.claude/shipgate.db` read the SQLite record as text: the `type` column sits directly before the JSON `data` column, and journal.py writes `json.dumps(sort_keys=True)` with `", "` and `": "` separators, so match `review-verdict\{[^\x00]{0,1000}"ranking": \{"files": …`. Home: `shipgate/evals/README.md` (Writing graders); deferred, evals were frozen during 0.20.0.
