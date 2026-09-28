---
type: regex
target: {source: file, path: app/orders.py}
flags: i
---
quantity[\s\S]{0,120}raise|raise[\s\S]{0,120}quantity
