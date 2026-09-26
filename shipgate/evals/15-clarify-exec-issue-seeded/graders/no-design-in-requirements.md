---
type: regex
target: {source: file, path: app/docs/prd/invoice-csv-export.md}
match: not_contains
flags: im
---
^- \*\*N?FR-\d+[^\n]*((exposes|adds?|new|introduces?)[^\n]{0,60}(GET|POST|PUT|DELETE) /|(GET|POST|PUT|DELETE) /[^\n]{0,80}(returns|responds|Content-Type)|\bmodule\b|\blibrary\b|http\.server|stdlib|standard[- ]library|`Decimal`|Decimal arithmetic|uses Decimal|reportlab|fpdf)
