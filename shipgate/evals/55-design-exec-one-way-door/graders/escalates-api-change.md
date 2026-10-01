---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true. Context: the config is executive mode, but its contract says one-way doors — public API changes among them — are escalated. `docs/api.md` is a public contract consumed by the mobile app and the finance export; changing `total` from a string to an object is a breaking change.
- The answer flags the `GET /invoices` response-shape change as a breaking / one-way-door change that the user must decide on, rather than committing it silently as an executive decision.
- It offers a parallel-change or versioning path (e.g. add a new field alongside `total`, a versioned endpoint, or a deprecation window) as the way to satisfy FR-002.
