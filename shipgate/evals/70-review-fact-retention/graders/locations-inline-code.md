---
type: regex
target: last_message
flags: m
weight: 0.25
---
^(?=[\s\S]*?^(?:[^`\n]*`[^`\n]*`)*[^`\n]*`[^`\n]*\bdb\.py\b[^`\n]*`)(?=[\s\S]*?^(?:[^`\n]*`[^`\n]*`)*[^`\n]*`[^`\n]*\bexport\.py\b[^`\n]*`)(?=[\s\S]*?^(?:[^`\n]*`[^`\n]*`)*[^`\n]*`[^`\n]*\breport\.py\b[^`\n]*`)
