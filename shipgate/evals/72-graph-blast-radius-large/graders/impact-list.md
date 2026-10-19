---
type: llm
focus: last_message
weight: 1
---
Grade each claim true/false; pass only if all are true.

The change at HEAD edits `packages/money/src/rounding/halfEven.ts` (the hub) and `packages/tools/src/scripts/alignQuotaSet.ts` (a script that nothing imports). The ground truth below is the exact set of files that import the hub directly or transitively: static imports, `@app/*` workspace package imports, barrel `index.ts` re-exports and `require(...)` calls all count. It has 44 source files and 15 test files (59 in total).

Source files:
  - `packages/auth/src/session/deriveStockSet.ts`
  - `packages/auth/src/session/loadBadge.ts`
  - `packages/auth/src/session/rankParcelSet.ts`
  - `packages/billing/src/invoice/checkReportSet.ts`
  - `packages/billing/src/invoice/deriveMarginSet.ts`
  - `packages/billing/src/ledger/splitSessionSet.ts`
  - `packages/core/src/config/computeShard.ts`
  - `packages/core/src/config/scanRangeMap.ts`
  - `packages/core/src/config/scanRebateSet.ts`
  - `packages/core/src/errors/priceSessionView.ts`
  - `packages/inventory/src/stock/sumShardSet.ts`
  - `packages/inventory/src/warehouse/loadCredit.ts`
  - `packages/inventory/src/warehouse/scoreStampMap.ts`
  - `packages/money/src/format/rankDigestMap.ts`
  - `packages/money/src/index.ts`
  - `packages/money/src/rounding/checkCursorPlan.ts`
  - `packages/money/src/rounding/computeTier.ts`
  - `packages/money/src/rounding/mapLedgerPlan.ts`
  - `packages/money/src/rounding/scanSkuView.ts`
  - `packages/notify/src/email/mergeShardMap.ts`
  - `packages/notify/src/email/planStockView.ts`
  - `packages/notify/src/hooks/deriveLabelSet.ts`
  - `packages/notify/src/hooks/groupCreditSet.ts`
  - `packages/notify/src/index.ts`
  - `packages/orders/src/checkout/parseVoucherPlan.ts`
  - `packages/orders/src/fulfilment/alignBatchMap.ts`
  - `packages/orders/src/fulfilment/alignShardMap.ts`
  - `packages/orders/src/fulfilment/mapStockPlan.ts`
  - `packages/pricing/src/quotes/checkWindowPlan.ts`
  - `packages/pricing/src/quotes/collectCarriers.ts`
  - `packages/pricing/src/quotes/deriveSlotSet.ts`
  - `packages/pricing/src/rules/loadBasketPlan.ts`
  - `packages/pricing/src/rules/sortBadge.ts`
  - `packages/pricing/src/rules/sumSku.ts`
  - `packages/reports/src/exports/sortTicket.ts`
  - `packages/reports/src/monthly/resolveQuotaPlan.ts`
  - `packages/search/src/indexer/computeRebateMap.ts`
  - `packages/search/src/query/collectTicketMap.ts`
  - `packages/search/src/query/trackCredits.ts`
  - `packages/shipping/src/rates/planTokenMap.ts`
  - `packages/tools/src/dev/splitTierView.ts`
  - `packages/tools/src/scripts/applyVoucher.ts`
  - `packages/tools/src/scripts/groupWindowPlan.ts`
  - `packages/tools/src/scripts/groupWindowSet.ts`

Test files:
  - `__tests__/auth/splitLanes.test.ts`
  - `__tests__/auth/sumColumns.test.ts`
  - `__tests__/catalog/splitCarriers.test.ts`
  - `__tests__/core/alignLabelMap.test.ts`
  - `__tests__/core/planLabelSet.test.ts`
  - `__tests__/money/checkReportPlan.test.ts`
  - `__tests__/money/renderParcel.test.ts`
  - `__tests__/orders/checkStampMap.test.ts`
  - `__tests__/orders/computeCreditPlan.test.ts`
  - `__tests__/pricing/parseBatchSet.test.ts`
  - `__tests__/reports/checkLanes.test.ts`
  - `__tests__/reports/resolvePeriodMap.test.ts`
  - `__tests__/reports/scanRebateView.test.ts`
  - `__tests__/search/trackMargin.test.ts`
  - `__tests__/shipping/trackRebatePlan.test.ts`

- Recall: the answer lists at least 54 of the 59 files above as affected. Count file paths; a directory name alone does not count for the files in it.
- Precision: the answer lists no other file as affected. The two changed files themselves are allowed. In particular, `packages/pricing/src/rules/roundingPolicy.ts` and `packages/reports/src/monthly/halfEvenSummary.ts` are not affected, and nothing is affected because of the edit to `packages/tools/src/scripts/alignQuotaSet.ts`.
- Tests: the answer names at least 13 of the 15 test files above as tests the change reaches.
