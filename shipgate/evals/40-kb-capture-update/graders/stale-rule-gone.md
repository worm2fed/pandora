---
type: regex
target: {source: file, path: app/services/api/CLAUDE.md}
match: not_contains
flags: m
---
Tests: `python3 -m unittest` from this directory\.$
