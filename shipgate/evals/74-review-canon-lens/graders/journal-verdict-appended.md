---
type: regex
target: {source: file, path: .claude/shipgate.db}
weight: 0.5
---
review-verdict\{[^\x00]{0,1000}"verdict": "(not-ready|ready)"
