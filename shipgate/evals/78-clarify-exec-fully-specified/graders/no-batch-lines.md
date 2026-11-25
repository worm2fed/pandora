---
type: regex
target: {source: file, path: app/docs/prd/monthly-statement-pdf.md}
match: not_contains
flags: m
---
^[-*] \[(?:domain|data|behaviour)\] (?:\[(?:blindspot|reference)\] )?\[no source found|^[-*] \[(?:domain|data|behaviour|technical)\] \[(?:blindspot|reference)\]
