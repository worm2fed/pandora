---
type: regex
target: {source: file, path: app/dates.py}
match: contains
---
return local\.astimezone\(timezone\.utc\)\.date\(\)
