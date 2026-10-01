---
type: regex
target: {source: file, path: .claude/shipgate.db}
match: not_contains
weight: 0.5
---
verify-passed|implement-done|workspace-ready
