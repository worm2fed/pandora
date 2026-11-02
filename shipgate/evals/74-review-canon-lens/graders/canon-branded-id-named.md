---
type: regex
target: last_message
flags: i
---
(OrderId|brand)[\s\S]{0,400}(orderId|CancelRequest|types\.ts)|(CancelRequest|types\.ts)[\s\S]{0,400}(OrderId|brand)
