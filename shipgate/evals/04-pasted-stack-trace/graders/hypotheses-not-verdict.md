---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true.
- It restates the problem as observed vs expected (settlement for some events fails with a missing `currency` key; they should settle).
- It offers at least two distinct competing hypotheses (e.g. provider B's payload shape changed / omits currency on some events; v2.3.0 changed how the payload is parsed or which key is read; a race where the event is processed before it is fully populated, given the retry succeeds).
- For each hypothesis it names the concrete evidence or check that would confirm or kill it (e.g. dump a failing raw payload, diff v2.3.0's changes to settle.py/payload parsing, check whether provider A events ever lack currency).
- It does NOT present a single cause as confirmed fact; the answer is explicit that it is not yet reproduced/confirmed.
- It asks for, or proposes how to get, a reproduction or the missing evidence (e.g. a failing payload sample, the v2.3.0 diff).
- It does not propose applying a code fix (like `payload.get("currency", "USD")`) as the answer before the cause is known.
