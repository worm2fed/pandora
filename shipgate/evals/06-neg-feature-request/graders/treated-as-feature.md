---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true.
- It treats the request as feature work: it implements a CSV export for the invoices (or presents a concrete implementation plan for one).
- It does not frame the work as debugging: no reproduction step, no hypothesis list, no root-cause analysis, no hunt for an introducing commit.
- If it implemented the export, it handles the comma in "Globex, Inc." correctly (quoted field, e.g. via the csv module) or states how it handles it.
