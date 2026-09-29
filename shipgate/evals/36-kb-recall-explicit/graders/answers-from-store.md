---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true.
- The answer states the recorded decision: the worker sends every customer notification; api never sends, it enqueues a `notify.*` event; delivery status comes back as `notify.delivered` / `notify.failed` events.
- It attributes this to the ADR (docs/adr/0002) as a documented decision, not merely to what the code happens to do.
- It mentions the retry policy from ADR 0003 (fixed 15-minute retries, max 3) or at least points to it, since it is part of "how notifications are sent".
