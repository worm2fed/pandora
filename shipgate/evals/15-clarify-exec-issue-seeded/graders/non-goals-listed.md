---
type: regex
target: {source: file, path: app/docs/prd/invoice-csv-export.md}
flags: im
weight: 0.5
---
^(?:#{1,6}[ \t][^\n]*non[- ]?goals|\*\*non[- ]?goals)[^\n]*\n(?:[ \t]*\n)*[ \t]*(?!#|\*\*[^*\n]*\*\*:?[ \t]*(?:\([^\n]*\))?[ \t]*$)\S|^\*\*non[- ]?goals:?\*\*:?[ \t]*[^\s(]
