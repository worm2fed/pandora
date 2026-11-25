"""`assumptions`: parse a PRD's "Assumptions (executive)" lines (#24, option P).

The section starts at the line `## Assumptions (executive)` and ends at the next line that
starts with `## `, or at the end of the file. The heading line appears once in the file; a
second one is an error at its line.

The section holds only assumption lines (the user's decision after review round 5). Each
line in it is one of three kinds, and any other line is an error, `only assumption lines
belong in this section`: prose, a heading, a wrong or missing bullet, a numbered item.

- A blank line. It closes the open item.
- An item line: `- ` or `* ` at column 0. Its form errors are its own (`no class tag`).
- A continuation line: indented two spaces or more, or a tab, right after an item line or
  another continuation line. It is joined to the item with one space.

Two indented forms keep their own reason: a line whose stripped text starts with ``` or
~~~ is a `code block in the assumptions section` (at column 0 too), and one that starts with
`- [` or `* [` is an `indented list item`. The parser reads no fence anywhere, so a fence
elsewhere in the PRD needs no handling; examples of the line form live in clarify's
SKILL.md, never in a PRD. An item's line is the 1-based file line it starts on.

An item reads, tags separated by spaces:

    - [<class>] [blindspot|reference]? <source tag> <question> → <answer> — <rationale> <end tag>?

- `<class>`: `domain`, `data`, `behaviour` or `technical`.
- The kind tag `[blindspot]` or `[reference]` is optional.
- Exactly one source tag: `[source: <ref>]` or `[no source found in <what was searched>]`.
  A leading tag ends at the `]` that closes its `[`, counting nested brackets, so
  `[source: app/[id]/page.tsx]` keeps the whole ref. An unclosed `[` in the class, kind or
  source position is an error; after the source tag it starts the question and stays in
  it (`[WIP Q?`).
- ` → ` is required; ` — <rationale>` is optional (the first ` — ` after the arrow).
- The end tag is optional: `[kept by the user]`, `[changed by the user, was: <old>]` or
  `[unconfirmed]`, exactly, and last on the item. One of these forms (in any case) with
  any text after it is `text after the end tag`. A trailing bracket whose text starts
  with `kept by`, `changed by` or `unconfirmed` in any case but is none of the exact forms
  is a broken end tag; followed only by `.`, `,`, `;`, `:`, `!` or spaces it is `text
  after the end tag`. Other trailing brackets (`[Kept items list]`) are plain text.

A bad item raises `AssumptionError` with its line. `risky_batch` keeps the items with no
end tag that are either unsourced `domain`, `data` or `behaviour` items or candidates (kind
`blindspot` or `reference`, whatever their class and source: a candidate exists to be put
to the user), in file order, capped at `cap` (default `BATCH_CAP`). #25 reuses
`parse_assumptions`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

ASSUMPTION_CLASSES = ("domain", "data", "behaviour", "technical")
ASSUMPTION_KINDS = ("blindspot", "reference")
RISKY_CLASSES = ("domain", "data", "behaviour")
BATCH_CAP = 4

_SECTION_HEADING = re.compile(r"^## Assumptions \(executive\)\s*$")
_ITEM_START = re.compile(r"^[-*] ")
_INDENTED_ITEM = re.compile(r"^[-*] \[")
_TRAILING_PUNCTUATION = ".,;:! "
_SOURCE_TAG = re.compile(r"^source:(.*)$", re.S)
_NO_SOURCE_TAG = re.compile(r"^no source found in(?:\s(.*))?$", re.S)
_CHANGED_TAG = re.compile(r"^changed by the user, was: (.*)$", re.S)
_END_WORDS = ("kept by", "changed by", "unconfirmed")
_EXACT_CHANGED = re.compile(r"^changed by the user, was: (.*\S.*)$", re.S | re.I)


class AssumptionError(ValueError):
    """A malformed assumption item; `line` is the file line it starts on."""

    def __init__(self, line: int, reason: str):
        super().__init__(f"{line}: {reason}")
        self.line = line
        self.reason = reason


def _scan(text: str) -> Tuple[bool, List[Tuple[int, str]]]:
    """(whether the section is there, (line, joined text after the bullet) per item)."""
    lines = text.splitlines()
    headings = [n for n, line in enumerate(lines, start=1) if _SECTION_HEADING.match(line)]
    if len(headings) > 1:
        raise AssumptionError(headings[1], 'a second "## Assumptions (executive)" heading')
    if not headings:
        return False, []
    items: List[List[Any]] = []
    current: Optional[List[Any]] = None
    for number in range(headings[0] + 1, len(lines) + 1):
        line = lines[number - 1]
        stripped = line.strip()
        if line.startswith("## "):
            break
        if not stripped:
            current = None
            continue
        if stripped.startswith(("```", "~~~")):
            raise AssumptionError(number, "code block in the assumptions section")
        if _ITEM_START.match(line):
            current = [number, line[2:].strip()]
            items.append(current)
            continue
        if line[:1] in (" ", "\t") and _INDENTED_ITEM.match(stripped):
            raise AssumptionError(number, "indented list item")
        if current is None or not line.startswith(("  ", "\t")):
            raise AssumptionError(number, "only assumption lines belong in this section")
        current[1] = f"{current[1]} {stripped}".strip()
    return True, [(number, body) for number, body in items]


def _leading_tag(body: str, line: int,
                 strict: bool = True) -> Tuple[Optional[str], str]:
    """The content of the `[...]` that opens `body` and the text after it.

    The tag ends at the `]` that closes the opening `[`, counting nested brackets. An
    unclosed `[` raises, or with `strict` false is no tag.
    """
    if not body.startswith("["):
        return None, body
    depth = 0
    for index, char in enumerate(body):
        depth += {"[": 1, "]": -1}.get(char, 0)
        if depth == 0:
            return body[1:index], body[index + 1:].lstrip()
    if not strict:
        return None, body
    raise AssumptionError(line, "unclosed [ in a tag")


def _is_source(tag: str) -> bool:
    return bool(_SOURCE_TAG.match(tag) or _NO_SOURCE_TAG.match(tag))


def _trailing_bracket(body: str) -> Optional[int]:
    """The index of the `[` that opens the bracket `body` ends with, if any."""
    if not body.endswith("]"):
        return None
    depth = 0
    for index in range(len(body) - 1, -1, -1):
        depth += {"]": 1, "[": -1}.get(body[index], 0)
        if depth == 0:
            return index
    return None


def _is_end_words(tag: str) -> bool:
    return tag.casefold().startswith(_END_WORDS)


def _is_exact_end_tag(tag: str) -> bool:
    """One of the three end-tag forms, in any case."""
    folded = tag.casefold()
    return (folded in ("kept by the user", "unconfirmed")
            or bool(_EXACT_CHANGED.match(tag)))


def _check_nothing_after_an_end_tag(body: str, line: int) -> None:
    """Raise when an end-tag form (any case) has any text after it."""
    for start, char in enumerate(body):
        if char != "[":
            continue
        depth = 0
        for index in range(start, len(body)):
            depth += {"[": 1, "]": -1}.get(body[index], 0)
            if depth == 0:
                if (_is_exact_end_tag(body[start + 1:index])
                        and body[index + 1:].strip()):
                    raise AssumptionError(line, "text after the end tag")
                break


def _end_tag(body: str, line: int) -> Tuple[Optional[str], Optional[str], str]:
    """(end, was, text before it) — the trailing end tag of `body`, if it has one."""
    body = body.rstrip()
    if not body.endswith("]"):
        bare = body.rstrip(_TRAILING_PUNCTUATION)
        if bare != body:
            start = _trailing_bracket(bare)
            if start is not None and start > 0 and _is_end_words(bare[start + 1:-1]):
                raise AssumptionError(line, "text after the end tag")
        return None, None, body
    depth = 0
    start = -1
    for index in range(len(body) - 1, -1, -1):
        depth += {"]": 1, "[": -1}.get(body[index], 0)
        if depth == 0:
            start = index
            break
    if start <= 0:
        return None, None, body
    tag = body[start + 1:-1]
    if not _is_end_words(tag):
        return None, None, body
    rest = body[:start].rstrip()
    if tag == "kept by the user":
        return "kept", None, rest
    if tag == "unconfirmed":
        return "unconfirmed", None, rest
    changed = _CHANGED_TAG.match(tag)
    if changed and changed.group(1).strip():
        return "changed", changed.group(1).strip(), rest
    raise AssumptionError(line, f"broken end tag [{tag}]")


def _parse_item(line: int, body: str) -> Dict[str, Any]:
    tag, rest = _leading_tag(body, line)
    if tag is None or tag in ASSUMPTION_KINDS or _is_source(tag):
        raise AssumptionError(line, "no class tag")
    if tag not in ASSUMPTION_CLASSES:
        raise AssumptionError(line, f"unknown class [{tag}]")
    item: Dict[str, Any] = {"line": line, "class": tag, "kind": None, "source": None,
                            "searched": None}
    sources = 0
    while True:
        tag, after = _leading_tag(rest, line, strict=not sources)
        if tag is None:
            break
        if tag in ASSUMPTION_CLASSES:
            raise AssumptionError(line, "two class tags")
        if tag in ASSUMPTION_KINDS:
            if sources or item["kind"]:
                raise AssumptionError(line, f"kind tag [{tag}] out of place")
            item["kind"] = tag
        elif _is_source(tag):
            sources += 1
            if sources > 1:
                raise AssumptionError(line, "two source tags")
            source = _SOURCE_TAG.match(tag)
            if source:
                item["source"] = source.group(1).strip()
                if not item["source"]:
                    raise AssumptionError(line, "empty source ref")
            else:
                item["searched"] = (_NO_SOURCE_TAG.match(tag).group(1) or "").strip()
                if not item["searched"]:
                    raise AssumptionError(line, "empty 'no source found in'")
        else:
            break
        rest = after
    if not sources:
        raise AssumptionError(line, "no source tag")
    _check_nothing_after_an_end_tag(rest, line)
    end, was, rest = _end_tag(rest, line)
    arrow = rest.find("→")
    if arrow < 0:
        raise AssumptionError(line, "no arrow (→) between question and answer")
    question, after = rest[:arrow].strip(), rest[arrow + 1:]
    dash = after.find(" — ")
    if dash < 0 and after.rstrip().endswith(" —"):
        dash = len(after.rstrip()) - 2
    answer = (after if dash < 0 else after[:dash]).strip()
    rationale = None if dash < 0 else (after[dash + 3:].strip() or None)
    if not question:
        raise AssumptionError(line, "empty question")
    if not answer:
        raise AssumptionError(line, "empty answer")
    item.update(question=question, answer=answer, rationale=rationale, end=end, was=was)
    return item


def parse_assumptions(text: str) -> List[Dict[str, Any]]:
    """Every item of the "Assumptions (executive)" section, in file order.

    Raises `AssumptionError` (a `ValueError`) for the first malformed item, a line that is
    no assumption line, or a second section heading. No section gives an empty list (`assumptions_report` tells it from an empty
    section).
    """
    return [_parse_item(line, body) for line, body in _scan(text)[1]]


def risky_batch(items: List[Dict[str, Any]],
                cap: int = BATCH_CAP) -> Tuple[List[Dict[str, Any]], int]:
    """(the first `cap` batch items in file order, how many more were dropped).

    In the batch: no end tag, and either class `domain`, `data` or `behaviour` with no
    source, or kind `blindspot` or `reference` whatever the class and source.
    """
    risky = [i for i in items if i["end"] is None
             and ((i["class"] in RISKY_CLASSES and i["source"] is None)
                  or i["kind"] in ASSUMPTION_KINDS)]
    return risky[:cap], max(len(risky) - cap, 0)


def assumptions_report(prd: str, text: str, risky: bool,
                       cap: int = BATCH_CAP) -> Dict[str, Any]:
    """The `assumptions --json` object for `text`, read from `prd`."""
    found, entries = _scan(text)
    items = [_parse_item(line, body) for line, body in entries]
    if not risky:
        return {"prd": prd, "section": found, "count": len(items),
                "cap": None, "overflow": 0, "items": items}
    batch, overflow = risky_batch(items, cap)
    return {"prd": prd, "section": found, "count": len(batch) + overflow, "cap": cap, "overflow": overflow,
            "items": batch}


def render_assumptions(report: Dict[str, Any]) -> str:
    """One line per item, then the count (and, for a batch, the overflow).

    With no section, a first line says so.
    """
    lines = [] if report["section"] else ['no "## Assumptions (executive)" section']
    lines += [f"{i['line']} [{i['class']}] {i['question']} → {i['answer']}"
              for i in report["items"]]
    if report["cap"] is None:
        count = report["count"]
        lines.append(f"{count} assumption{'' if count == 1 else 's'}")
    else:
        lines.append(f"{report['count']} to confirm, {report['overflow']} over the cap "
                     f"of {report['cap']}")
    return "\n".join(lines)
