---
type: regex
target: last_message
flags: i
---
lint[^.\n]{0,80}(clean|0 findings|no (problems|findings|issues)|exit(s|ed)? (code )?0|pass)
