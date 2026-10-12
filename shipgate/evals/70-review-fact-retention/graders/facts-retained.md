---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true. Grade presence, never sentence order. Facts planted in the commit at HEAD:
- `db.py` line 18: the new `DB.invoices_for(customer)` builds its SQL with an f-string, `WHERE customer = '{customer}'`. CLAUDE.md says SQL is always parameterised, and the PRD says the name comes from a search box in the admin UI, so it is an injection risk: `invoices_for("x' OR '1'='1")` returns all 3 invoices instead of none, and a name with an apostrophe raises a SQL error.
- `export.py` line 16: rows are now built as `f"{number},{name},{fmt(total)},{status}"` with no CSV quoting (the old code used `csv.writer`). `export(customer="Globex, Inc.")` writes `INV-002,Globex, Inc.,119.00,paid`, which a CSV reader parses as 5 columns, not 4 (FR-003 / SC-002 broken).
- `report.py` line 19: the late fee is formatted with `f"{fee / 100:.2f}"` instead of `money.fmt()` (CLAUDE.md rule). For Initech (2500 cents due) the fee is 12.5 cents; `:.2f` rounds half to even and prints `Late fee: 0.12`, while `money.fmt` rounds half up to `0.13` as SC-001 requires.
Claims:
1. The SQL interpolation in db.py is reported as a rule violation or injection risk, with its location.
2. The CSV quoting bug in export.py is reported with a concrete failing input or scenario (a comma in a customer name such as "Globex, Inc." gives extra columns).
3. The money-formatting rule violation in report.py is reported with its location and its rounding or formatting consequence (the half-cent fee prints 0.12 instead of 0.13, or equivalent).
4. Each of the three findings carries a severity or an equivalent ranking word (blocker, high, medium, must-fix, should-fix, or a ranked position).
5. The verdict is not ready / do not open the PR yet.
