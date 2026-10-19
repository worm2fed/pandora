---
type: llm
focus: last_message
weight: 1
---
Grade each claim true/false; pass only if all are true.
- The change makes `fetchInvoice` (or its HTTP call) run through the existing `withPolicy` helper (exported from `@app/platform`, defined in `packages/platform/src/net/resilience/policy.ts`), directly or through a thin wrapper that calls `withPolicy`.
- The answer does not add a new retry or backoff loop of its own (no new `for`/`while` loop with a sleep, `pause` or `setTimeout`, no new retry function that re-implements the doubling pause).
- A 404 ("not found") is not retried: the answer shows a `keepGoing` check, or keeps the 404 check outside the retried call, or says how a 404 is excluded.
