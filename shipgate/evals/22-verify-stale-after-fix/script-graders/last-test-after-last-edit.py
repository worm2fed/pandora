#!/usr/bin/env python3
"""Script grader of case 22: the last test run comes after the last edit of pricing.py.

    python3 last-test-after-last-edit.py <trace.jsonl>

It replaces the LLM judge that read the trace (ADR 0036). It reads every tool call of the
run's kept trace in order, the calls of subagents included, and compares call indexes.

- A test run is a Bash call that runs the fixture's one test command, `python3 -m unittest`
  (also `python` or `python3.N`, with any args after it). Its result does not matter: a
  failing run is still a run.
- An edit of pricing.py is an Edit, Write, MultiEdit or NotebookEdit call whose
  `file_path` (`notebook_path` for NotebookEdit) has the base name `pricing.py` (so
  `test_pricing.py` is no edit) and whose result is not an error. An edit made through a
  shell command is out of scope, because the trace records tool edits exactly and shell
  text cannot be read that way.

Verdicts: no test run is a fail, because there is no fresh evidence. Test runs and no edit
of pricing.py is a pass: no edit came after the last run.

Exit codes:

    0  pass (one line on stdout)
    1  fail (one line on stdout: the reason)
    2  usage error, or the trace cannot be read (stderr)
"""
import json
import os
import re
import sys

TARGET = "pricing.py"
EDIT_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path"}
TEST_RUN = re.compile(r"""(?<![\w.-])python(?:3(?:\.\d+)?)?\s+-m\s+unittest\b""")


def tool_calls(path):
    """[(name, input, is_error)] for each tool call of the trace, in order."""
    calls, by_id = [], {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get("type") not in ("assistant", "user"):
                continue
            message = event.get("message")
            blocks = message.get("content") if isinstance(message, dict) else None
            if not isinstance(blocks, list):
                continue
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    args = b.get("input")
                    call = [b.get("name"), args if isinstance(args, dict) else {}, False]
                    calls.append(call)
                    by_id[b.get("id")] = call
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in by_id:
                    by_id[b["tool_use_id"]][2] = bool(b.get("is_error"))
    return calls


def grade(calls):
    """(passed, reason)."""
    last_test = last_edit = None
    for index, (name, args, is_error) in enumerate(calls, 1):
        if name in EDIT_TOOLS:
            path = args.get(EDIT_TOOLS[name]) or ""
            if os.path.basename(path) == TARGET and not is_error:
                last_edit = (index, f"{name} call {index}")
        elif name == "Bash" and TEST_RUN.search(args.get("command") or ""):
            last_test = (index, f"Bash call {index}")
    if last_test is None:
        return False, "no test run (a Bash call with python3 -m unittest) in the trace"
    if last_edit is None:
        return True, f"the last test run is {last_test[1]}; pricing.py was not edited"
    if last_test[0] > last_edit[0]:
        return True, f"the last test run ({last_test[1]}) comes after the last edit of pricing.py ({last_edit[1]})"
    return False, f"pricing.py was edited ({last_edit[1]}) after the last test run ({last_test[1]})"


def main(argv):
    if len(argv) != 1:
        print("usage: last-test-after-last-edit.py <trace.jsonl>", file=sys.stderr)
        return 2
    try:
        calls = tool_calls(argv[0])
    except OSError as e:
        print(f"cannot read trace {argv[0]}: {e.strerror or e}", file=sys.stderr)
        return 2
    passed, reason = grade(calls)
    print(reason)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
