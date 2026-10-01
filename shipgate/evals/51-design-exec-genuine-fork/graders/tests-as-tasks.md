---
type: regex
target: {source: file, path: app/docs/prd/monthly-statement-pdf.worklog.md}
flags: im
---
(^- \[ \]|^\s*\d+\.\s|^- T\d+)[^\n]*test
