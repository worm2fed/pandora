---
type: regex
target: {source: file, path: app/docs/prd/invoice-csv-export.md}
match: not_contains
flags: i
---
csv\W{0,3}module|import csv|pandas|StringIO|csv\.writer|\bJOIN\b|dict built
