---
max_turns: 8
timeout_seconds: 180
allowed_tools: [Read, Grep, Glob, Skill]
runs: 3
---
We've been getting this in prod since yesterday's deploy (v2.3.0 went out at 14:00 UTC). No repo access from here, just the logs:

```
Traceback (most recent call last):
  File "/srv/payments/worker.py", line 88, in handle
    settle_payment(event)
  File "/srv/payments/settle.py", line 41, in settle_payment
    amount = Money(payload["amount"], payload["currency"])
KeyError: 'currency'
```

```
14:02:11 INFO  settle provider=A event=evt_91 ok
14:02:13 ERROR settle provider=B event=evt_92 KeyError: 'currency'
14:05:40 INFO  settle provider=B event=evt_92 retry=1 ok
```

What's going on?
