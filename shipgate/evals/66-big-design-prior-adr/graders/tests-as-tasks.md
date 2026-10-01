---
type: regex
target: {source: file, path: docs/prd/overdue-digest.worklog.md}
flags: im
---
(^- \[ \]|^\s*\d+\.\s|^- T\d+)[^\n]*test
