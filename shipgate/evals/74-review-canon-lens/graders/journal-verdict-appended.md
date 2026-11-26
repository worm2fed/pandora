---
type: regex
target: {source: file, path: .claude/shipgate.db}
weight: 0.5
arm: with-only
---
review-verdict\{[^\x00]{0,1000}"verdict": "(not-ready|ready)"
