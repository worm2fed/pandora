---
type: regex
target: last_message
flags: i
---
cancel\.ts[\s\S]{0,400}(switch|exhaustive|match\b)|(switch|exhaustive)[\s\S]{0,400}cancel\.ts
