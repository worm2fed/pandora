---
type: llm
focus: {source: file, path: app/docs/prd/payment-reminders.md}
---
Grade each claim true/false; pass only if all are true. Context: the repo already computes due dates and days-until-due (`terms.py`: `due_date`, `days_until_due`, weekend roll-forward). The request's "we'll need to compute the due window" is a stale assumption.
- No functional requirement asks to build or re-implement the due-date rule itself (issued + net days, weekend roll-forward). Defining reminder points relative to the existing due date (e.g. "7 days before the due date") is fine and does not count.
- The PRD says, somewhere, that the invoice's due date (or days-until-due) already exists in the service / follows the existing payment-terms rule, and is reused.
