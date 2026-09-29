---
type: llm
focus: last_message
---
Grade each claim true/false; pass only if all are true.
- It says the api creates the order (status placed) and emits `order.placed`.
- It says the worker consumes that event, books the carrier, and emits `order.shipped`.
- It says the api applies `order.shipped` (status becomes shipped) and that the customer notification is then delivered by the worker.
- It is an explanation, not an impact map or a plan for a change.
