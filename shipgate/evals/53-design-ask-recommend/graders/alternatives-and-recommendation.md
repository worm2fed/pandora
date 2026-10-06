---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true.
- There is an explicit recommendation with reasons grounded in the PRD's constraints or the codebase (volumes, the 3-second budget, stdlib only, what data exists).
- At least one alternative approach is named and rejected with a reason (e.g. pre-render vs. on demand, background job vs. in-request) — OR the answer explains why only one approach is viable here.
- The answer asks the user to confirm or choose before the worklog is written; it does not say "you decide" without recommending.
