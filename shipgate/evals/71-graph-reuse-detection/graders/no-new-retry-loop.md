---
type: regex
target: {source: file, path: app/src/billing/client.ts}
match: not_contains
---
setTimeout|function\s+retry|\bwhile\s*\(|for\s*\(\s*let\s+attempt
