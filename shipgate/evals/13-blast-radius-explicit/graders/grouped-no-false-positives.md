---
type: llm
focus: last_message
weight: 1
---
Grade each claim true/false; pass only if all are true.
- The affected set it presents is exactly these six files (the changed `src/util/round.ts` itself may also be mentioned as the change): `src/util/currency.ts`, `src/util/percent.ts` (direct importers), and `src/billing/lineItem.ts`, `src/billing/tax.ts`, `src/billing/invoice.ts`, `src/billing/pdfSummary.ts` (transitive importers).
- It includes no false positives in the affected list: `src/util/slugify.ts`, `src/billing/refundPolicy.ts`, `src/catalog/product.ts` and `src/catalog/search.ts` are not listed as affected (they do not import `round.ts` directly or transitively, even though some of them do their own `Math.round`).
- The list is grouped by directory (e.g. `src/util/` and `src/billing/` as separate groups).
