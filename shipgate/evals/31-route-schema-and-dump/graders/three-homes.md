---
type: llm
focus: last_message
---
Context (the repo's rules): root CLAUDE.md — new endpoints go in services/api, scheduled work in services/worker, migrations in services/api/migrations/ and services/worker/schema_snapshot.sql must be regenerated afterwards; services/api/CLAUDE.md — read-only reporting endpoints go under reports/, never in routes.py; services/worker/CLAUDE.md — the worker never writes order tables, it emits events api applies; docs/adr/0002 — all customer notifications are sent by the worker, api only enqueues.

        Grade each claim true/false; pass only if all are true.
        - The answer says a schema migration is needed and that it goes in `services/api/migrations/`.
        - It names the obligation to regenerate `services/worker/schema_snapshot.sql` (make snapshot) after the migration.
        - It names `web/` (the order list component) for showing the timestamp.
        - It identifies where `shipped_at` gets written (api's order state change when order.shipped is applied), not the worker.
