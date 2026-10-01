---
type: regex
target: last_message
match: not_contains
flags: i
weight: 0.5
---
INFO[^.\n]{0,60}(should|must|change to|use DEBUG|violat)
