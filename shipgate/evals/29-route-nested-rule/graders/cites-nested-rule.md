---
type: llm
focus: last_message
---
Context (the repo's rules): root CLAUDE.md — new endpoints go in services/api, scheduled work in services/worker, migrations in services/api/migrations/ and services/worker/schema_snapshot.sql must be regenerated afterwards; services/api/CLAUDE.md — read-only reporting endpoints go under reports/, never in routes.py; services/worker/CLAUDE.md — the worker never writes order tables, it emits events api applies; docs/adr/0002 — all customer notifications are sent by the worker, api only enqueues.

        Grade each claim true/false; pass only if all are true.
        - The answer names `services/api/reports/` as the home for this endpoint and gives the api CLAUDE.md rule (reporting endpoints go under reports/, not routes.py) as the reason.
        - It does not propose putting the endpoint in `routes.py`.
        - It says no schema migration is needed (the data is already in the orders table), or otherwise does not invent one.
