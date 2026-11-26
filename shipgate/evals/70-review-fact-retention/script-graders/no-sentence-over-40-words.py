#!/usr/bin/env python3
"""Script grader of case 70: no sentence of the final answer is over 40 words.

    python3 no-sentence-over-40-words.py <trace.jsonl>

It takes over claim 1 of the LLM judge `readable` (ADR 0036). The final answer is the
`result` text of the trace's last `result` record. A trace with no such record falls back
to the text of the last assistant message of the main thread (no `parent_tool_use_id`).

How the answer is cut into sentences:

- A fenced code block (from a line that starts with ``` or ~~~ to its closing fence, or
  to the end) is not prose and is dropped.
- An inline code span counts as one word, whatever it holds.
- A heading line, and each cell of a table row, is a block of its own. A blank line and
  a list item start a new block. The other lines join the block before them. Heading
  marks, list markers (`-`, `*`, `+`, `1.`, `1)`) and `>` quote marks are dropped.
- In a block, a sentence ends at `.`, `!` or `?` followed by a space or the end of the
  block. Closing marks (`*`, `_`, `)`, `]`, quotes, a backtick) may stand between the
  two, so `**Not ready.**` ends its sentence. An abbreviation such as "e.g." can end a
  sentence early, which only shortens it.
- A word is a run of non-space characters that holds a letter or a digit, so a dash or an
  arrow on its own is no word.

A sentence of 40 words passes; one of 41 fails. An answer with no text fails.

Exit codes:

    0  pass (one line on stdout)
    1  fail (one line on stdout: the reason)
    2  usage error, or the trace cannot be read (stderr)
"""
import json
import re
import sys

LIMIT = 40
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`+[^`\n]*?`+")
HEADING = re.compile(r"^\s*#{1,6}\s")
BLOCK_START = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s)")
MARKERS = re.compile(r"^\s*(?:>\s*)*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)?")
SENTENCE_END = re.compile(r"(?<=[.!?])[*_)\]\"'\u2019\u201d`]*\s+")
WORD = re.compile(r"[^\W_]")


def final_answer(path):
    """The final answer of the trace, or None."""
    result = assistant = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "result" and isinstance(event.get("result"), str):
                result = event["result"]
            elif event.get("type") == "assistant" and not event.get("parent_tool_use_id"):
                message = event.get("message")
                blocks = message.get("content") if isinstance(message, dict) else None
                if isinstance(blocks, list):
                    texts = [b.get("text") or "" for b in blocks
                             if isinstance(b, dict) and b.get("type") == "text"]
                    if any(t.strip() for t in texts):
                        assistant = "\n".join(texts)
    return result if result is not None else assistant


def prose_blocks(text):
    """The blocks of prose of a markdown text, as strings, code blocks dropped."""
    blocks, current, fence = [], [], None
    for line in text.splitlines():
        opening = FENCE.match(line)
        if fence is not None:
            if opening and opening.group(1) == fence:
                fence = None
            continue
        if opening:
            fence = opening.group(1)
            blocks.append(current)
            current = []
            continue
        if not line.strip():
            blocks.append(current)
            current = []
            continue
        if line.lstrip().startswith("|"):
            blocks.append(current)
            blocks.extend([cell] for cell in line.strip().strip("|").split("|"))
            current = []
            continue
        if HEADING.match(line):
            blocks.append(current)
            blocks.append([MARKERS.sub("", line, count=1)])
            current = []
            continue
        if BLOCK_START.match(line):
            blocks.append(current)
            current = []
        current.append(MARKERS.sub("", line, count=1))
    blocks.append(current)
    return [" ".join(b) for b in blocks if b]


def words(sentence):
    return [w for w in sentence.split() if WORD.search(w)]


def longest_sentence(text):
    """(word count, sentence) of the longest sentence of the text's prose."""
    best = (0, "")
    for block in prose_blocks(text):
        block = INLINE_CODE.sub("code", block)
        for sentence in SENTENCE_END.split(block.strip()):
            n = len(words(sentence))
            if n > best[0]:
                best = (n, sentence)
    return best


def main(argv):
    if len(argv) != 1:
        print("usage: no-sentence-over-40-words.py <trace.jsonl>", file=sys.stderr)
        return 2
    try:
        answer = final_answer(argv[0])
    except OSError as e:
        print(f"cannot read trace {argv[0]}: {e.strerror or e}", file=sys.stderr)
        return 2
    if answer is None or not answer.strip():
        print("no final answer in the trace")
        return 1
    n, sentence = longest_sentence(answer)
    if n > LIMIT:
        start = " ".join(sentence.split()[:8])
        print(f"a sentence of {n} words (limit {LIMIT}): {start} ...")
        return 1
    print(f"the longest sentence has {n} words (limit {LIMIT})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
