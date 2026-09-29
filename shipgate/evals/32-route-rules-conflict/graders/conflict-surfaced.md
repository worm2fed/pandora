---
type: llm
focus: last_message
---
Context (the repo's rules): root CLAUDE.md — new endpoints go in services/api, scheduled work in services/worker, migrations in services/api/migrations/ and services/worker/schema_snapshot.sql must be regenerated afterwards; services/api/CLAUDE.md — read-only reporting endpoints go under reports/, never in routes.py; services/worker/CLAUDE.md — the worker never writes order tables, it emits events api applies; docs/adr/0002 — all customer notifications are sent by the worker, api only enqueues.

        Grade each claim true/false; pass only if all are true.
        - The answer recognises that two rules collide here: scheduled work belongs in the worker, but the worker never writes to the order tables.
        - It resolves this explicitly — either as an open routing question for the user, or as an explicit split (the worker computes and emits an event; api applies the stored totals) — and says which.
        - It does NOT silently route the writes into the worker, and does not silently put the scheduled job in api.
