---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true. Context: docs/adr/0003 already decided fixed 15-minute retries (max 3, then notify.dead) and rejected exponential backoff because aligned retries burst against provider rate limits.
- The answer cites ADR 0003 as an existing decision that conflicts with the request.
- It either designs within the decision (e.g. explains why the fixed interval stays, offers jitter or a supersession path) or explicitly proposes SUPERSEDING the ADR, naming what changes and why the earlier reason (burst alignment) is addressed.
- It does not present exponential backoff as if nothing had been decided before.
