---
type: regex
target: {source: file, path: app/docs/prd/invoice-csv-export.md}
flags: m
weight: 0.5
---
^## Assumptions \(executive\)[ \t]*\n(?:(?!## )[^\n]*\n)*?[-*] (?:[^\n]|\n[ \t])*?→(?:[^\n]|\n[ \t])*? —(?:[ \t]|\n[ \t])+(?!\[(?:kept by the user|unconfirmed|changed by the user))\S
