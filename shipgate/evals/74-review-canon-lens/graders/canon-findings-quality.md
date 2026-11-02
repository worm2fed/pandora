---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true. Facts about HEAD: the config's Style section names the `typed-canon` skill, whose rules are mandatory in `src/`. The change breaks two of them: `cancel` in src/orders/cancel.ts branches on the closed `OrderStatus` union with a `switch` (rule 2: use the exhaustive `match` from src/shared/match.ts), and `CancelRequest.orderId` in src/orders/types.ts is a bare `string` in the domain layer (rule 3: use the branded `OrderId`).
- It reports the `switch` over `OrderStatus` as a finding that the change must fix, citing the canon rule or the `match` helper; it does not wave it off as taste or a nit.
- It reports `CancelRequest.orderId: string` as a finding that the change must fix (an unbranded id; `OrderId` required); it does not wave it off as taste or a nit.
- Both findings appear before or together with the verdict, and the verdict is not-ready / fix before the PR.
