---
type: regex
target: {source: file, path: docs/prd/payment-reminders.md}
match: not_contains
flags: im
---
^- \*\*FR-0\d\d\*\*[^\n]*(compute|calculate|implement)[^\n]*due[- ]date (rule|calculation|logic)
