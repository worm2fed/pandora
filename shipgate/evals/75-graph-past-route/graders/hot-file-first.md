---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true. Facts about HEAD: three files changed. src/billing/invoice.ts has 14 commits including HEAD, 10 of them fixes, and 5 modules import it; src/billing/format.ts and src/reports/labels.ts have one commit each, no fixes, and little or no fan-in.
- It names src/billing/invoice.ts as the changed file it looked at hardest (or ranks it first).
- It grounds that choice in the file's history or structure (fix history, churn, fan-in, importers or blast radius), not only in the size of the edit.
- It gives a verdict on the change (ready or not ready).
