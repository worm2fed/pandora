---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true.
- It says retries happen only on HTTP 5xx errors and on timeouts / connection-level URLError, and that other errors (e.g. 4xx) are raised immediately.
- It says there are at most 3 retries (4 attempts total) before the last exception is re-raised.
- It describes the wait as exponential backoff with full jitter: a random delay between 0 and 0.5 × 2^attempt seconds (ceilings 0.5 s, 1 s, 2 s).
- It does not frame the answer as a bug investigation (no hypotheses, no reproduction, no root cause) — it is an explanation.
