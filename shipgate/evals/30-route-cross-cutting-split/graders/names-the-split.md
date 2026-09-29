---
type: llm
focus: last_message
---
Context (the repo's rules): root CLAUDE.md — new endpoints go in services/api, scheduled work in services/worker, migrations in services/api/migrations/ and services/worker/schema_snapshot.sql must be regenerated afterwards; services/api/CLAUDE.md — read-only reporting endpoints go under reports/, never in routes.py; services/worker/CLAUDE.md — the worker never writes order tables, it emits events api applies; docs/adr/0002 — all customer notifications are sent by the worker, api only enqueues.

        Grade each claim true/false; pass only if all are true.
        - The answer states an explicit split across two services: `services/api` (the order state change / emitting the notify event) and `services/worker` (delivering the SMS, e.g. a handler in notifications.py).
        - It does not have the worker write to the order tables.
        - It does not have api send the SMS itself.
        - It cites the ADR (0002) or the worker rule as the reason for the split, not just convention.
