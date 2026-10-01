---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true. Context: root CLAUDE.md puts scheduled work in services/worker; services/worker/CLAUDE.md says the worker never writes order tables and emits events api applies.
- The answer recognises that the two rules collide for this request.
- It resolves this explicitly — an open routing question for the user, or an explicit split (worker computes and emits; api applies the stored totals) — and says which.
- It does NOT silently route the writes into the worker, and does not silently put the scheduled job in api.
