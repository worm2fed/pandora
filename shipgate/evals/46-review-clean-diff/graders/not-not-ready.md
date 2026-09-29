---
type: regex
target: last_message
match: not_contains
flags: i
---
not ready|not-ready|\bnot yet\b|do not (push|open)|don'?t open|must[- ]fix|(?<!no )(?<!zero )(?<!without )blockers?\b
