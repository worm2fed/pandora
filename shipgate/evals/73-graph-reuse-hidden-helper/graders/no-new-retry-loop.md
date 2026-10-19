---
type: regex
target: {source: file, path: app/packages/billing/src/gateway/invoiceClient.ts}
match: not_contains
---
setTimeout|function\s+retry|\bwhile\s*\(|for\s*\(\s*let\s+attempt
