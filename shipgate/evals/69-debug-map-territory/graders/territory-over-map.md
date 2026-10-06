---
type: llm
focus: last_message
---
The README, the `pricing.py` docstring and `test_pricing.py` all describe discount-before-tax, and they are correct about `pricing.quote()`. The live checkout path (`checkout.charge_total`) no longer calls `quote()`: since the "perf(checkout): compute the cart total in one pass" commit it re-implements the arithmetic inline: it taxes the gross (120.00), computes the coupon on that gross (12.00) and then "scales the discount back out" of the tax (`discount / (1 + rate)` → 10.00), so only the pre-tax 10.00 comes off the taxed 120.00 — 110.00 instead of 108.00. (Order alone would not matter: percentage tax and percentage discount commute; the scale-back line is the defect.) Grade each claim true/false; pass only if all are true.
- It locates the defect in `checkout.py` / `charge_total` and says that this is the code that actually runs at checkout, and that it does not go through `pricing.quote()`.
- It explains why the docs and the green tests did not catch it: they describe and test `quote()`, which checkout no longer uses — the test covers the wrong path (the description is a map; the running code is what ships). Saying only "the test is wrong" without saying what it does cover fails this claim.
- It shows evidence from the running code or a reproduction (quoting the lines, or running `charge_total` on the 100.00 / 10% / EU case and getting 110.00), not just reasoning from the README's rule.
- It names the introducing commit (the perf one-pass change), not the later CH-rate or shipping commits that merely touched nearby code.
- It ends with a fix **proposal** (restore the call to `quote()` per line, or drop the scale-back line — take the coupon off the net, or off the gross directly — and add a checkout-level test on the 108.00 case) and asks for the go-ahead; it does not apply the fix.
