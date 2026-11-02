---
type: regex
target: {source: file, path: .claude/shipgate.db}
weight: 0.5
arm: with-only
---
"phase": "review",[^\x00]{0,200}"style": \["typed-canon"\]|review-verdict\{[^\x00]{0,1000}"style": \["typed-canon"\]
