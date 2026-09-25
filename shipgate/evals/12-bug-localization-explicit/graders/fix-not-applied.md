---
type: regex
target: {source: file, path: app/src/dates/monthRange.ts}
match: contains
---
d\.getTime\(\) <= r\.end\.getTime\(\)
