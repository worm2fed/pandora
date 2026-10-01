---
type: regex
target: {source: file, path: app/docs/prd/overdue-digest.worklog.md}
match: not_contains
flags: i
weight: 0.5
---
api (sends|delivers|emails) (the )?(digest|email)|send(s|ing)? (the )?(digest|email)s? (from|in) (services/)?api
