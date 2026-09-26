---
type: llm
focus: {source: file, path: app/docs/prd/customer-soft-delete.md}
---
Grade each claim true/false; pass only if all are true. Context: `docs/api.md` says `GET /customers` is a contract consumed by the mobile app and the finance export; production runs on `schema.sql`.
- The effect of soft delete on the public `GET /customers` response (omit deleted customers, flag them, or a parameter — and the impact on the mobile app / finance export) is left as an OPEN decision for the user (a question or `[NEEDS CLARIFICATION]`), not decided in the executive assumptions.
- The PRD acknowledges that a customer schema/data change is implied and treats it as a one-way door to be escalated (here or in design) rather than silently assuming a storage design.
- Requirements are stated at behaviour level (mark deleted, excluded from lists and new invoices by default, restorable by an admin); no requirement dictates a specific column, table or flag design.
- The PRD does not claim the clarify gate is passed / all questions resolved.
