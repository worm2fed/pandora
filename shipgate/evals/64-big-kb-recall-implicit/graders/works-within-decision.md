---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true. Context: docs/adr/0007 (one of twelve ADRs) decided fixed 15-minute retries, max 3, then notify.dead, and rejected exponential backoff because aligned retries burst against provider rate limits.
- The answer cites ADR 0007 as an existing decision that conflicts with the request.
- It either designs within it (e.g. jitter, a supersession path) or explicitly proposes SUPERSEDING the ADR, naming what changes and how the burst problem is addressed.
- It does not present exponential backoff as if nothing had been decided before.
