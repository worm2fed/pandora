---
type: regex
target: {source: file, path: .claude/shipgate.db}
---
review-verdict\{[^\x00]{0,1000}"ranking": \{"files": \[[^\x00]{0,700}\], "source": "graph"\}
