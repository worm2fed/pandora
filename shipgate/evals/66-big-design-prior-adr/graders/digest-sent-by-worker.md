---
type: regex
target: {source: file, path: docs/prd/overdue-digest.worklog.md}
flags: i
---
worker[^\n]{0,160}(digest|notify|send|deliver)|(digest|notify|send|deliver)[^\n]{0,160}worker
