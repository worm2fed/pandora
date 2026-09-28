---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true.
- It says pages are 1-based and each page holds `size` items.
- It says a page past the end returns an empty list.
- It says `size <= 0` (and `page < 1`) raise ValueError.
