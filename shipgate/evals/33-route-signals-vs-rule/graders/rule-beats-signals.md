---
type: llm
focus: last_message
---
Context (the repo's rules): root CLAUDE.md — new endpoints go in services/api, scheduled work in services/worker, migrations in services/api/migrations/ and services/worker/schema_snapshot.sql must be regenerated afterwards; services/api/CLAUDE.md — read-only reporting endpoints go under reports/, never in routes.py; services/worker/CLAUDE.md — the worker never writes order tables, it emits events api applies; docs/adr/0002 — all customer notifications are sent by the worker, api only enqueues.

        Grade each claim true/false; pass only if all are true. Context: `services/api/routes.py` has by far the most fix commits in the repo's history.
        - The answer keeps `services/api/routes.py` (endpoint registration) plus `orders.py` (the state change) as the home, per the rules.
        - It reports routes.py as high-risk / hot / frequently fixed (from git history or risk signals).
        - It does not reroute the endpoint elsewhere to avoid the hot file; the risk is reported as a reason for care (tests, review), not for changing the home.
