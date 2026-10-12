---
type: llm
focus: last_message
weight: 0.25
---
Judge the readability of the review report. Grade each claim true/false; pass only if all three are true. A single long sentence or one long list item does not make a claim false. Headings, bullet lists and tables are fine and count as short sentences. Do not grade order, tone, or the length of the whole report.
1. Sentences are mostly short: about 20 words or fewer, and none over about 40.
2. Each finding gives its location (file and line), what fails, and the input or case that triggers it, as plain statements rather than hedges ("may", "might", "should probably").
3. Code, commands, file names and error text appear as inline code or in fenced blocks, not spelled out inside long sentences.
