#!/usr/bin/env python3
"""PostToolUse hook — record the artifact writes a session's own tool calls made.

Each record is a claim that this session wrote the file (ADR 0008):

* Write/Edit/NotebookEdit name the file they wrote: `source: tool`.
* Bash names no file, so its claim rests on the call's own evidence, best first. When
  Claude Code took a diff of the call, each listed artifact is claimed with
  `evidence: diff`. Every other artifact goes to the window: one whose mtime falls
  inside the call's `duration_ms` and that the command text writes, in a write shape
  (a redirect target, `tee`, `sed -i`, `perl -i`, or the destination of `mv`, `cp` or
  `install`), is claimed with `evidence: window`. A read never claims. With no usable
  diff the window covers every artifact; with one, those the diff did not list, because
  the diff never lists a file git ignores or a file in a submodule. A background
  command has no diff and no real duration, so it claims nothing.

A claim is evidence, not a verdict: `journal.py` weighs every claim on a write when it
reads them, so a wrong window claim at worst ties with the true writer and names no
author. `file_changed.py` watches the disk and records each write as an observation,
which catches what no tool call claims (an external editor, a sync).

Nothing here can block — the tool has already run by the time this fires, which is
exactly right. Capture is a recording, never a veto.

This hook fires on every Write, Edit and Bash call in every project, so the ordering
below is deliberate: gate on the sidecar before reading stdin, and return before
importing anything heavy when the project isn't journaled. A Bash call runs
`journal.py` only when it has a claim to record.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    append_event,
    append_events,
    find_project,
    likely_journaled,
    mtime_of,
    read_hook_input,
    safe_main,
    watch_paths,
)

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}
# Claude Code lists at most this many changed files; a longer list is a shape it changed.
MAX_CHANGED_FILES = 200
# The hook starts a little after the call ends, and file systems stamp mtimes coarsely.
WINDOW_SLACK_SECONDS = 1.0


def changed_path(payload):
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    return raw if isinstance(raw, str) and raw else None


def diff_paths(tool_response):
    """The files a Bash call's diff lists, or None when there is no usable diff.

    `bashEditDiff` is best effort, in public beta, and its shape may change. So any
    unexpected shape counts as no diff, never as an error, and the call falls back to
    the window evidence. `unavailable` marks an incomplete diff; `skipped`, a checkout
    or stash that moved the working tree.
    """
    if not isinstance(tool_response, dict):
        return None
    diff = tool_response.get("bashEditDiff")
    if not isinstance(diff, dict):
        return None
    if any(diff.get(flag, False) is not False for flag in ("unavailable", "skipped")):
        return None
    changed = diff.get("changedFiles")
    if not isinstance(changed, list) or len(changed) > MAX_CHANGED_FILES:
        return None
    if not all(isinstance(path, str) and os.path.isabs(path) for path in changed):
        return None
    return changed


# The write shapes a window claim needs (ADR 0008, review R1-F2), as regexes for a token
# scan of the command text. A heredoc's body is data, not commands: from `<<EOF` to the
# line that closes it.
HEREDOC_BODY = (
    r"(<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\2[^\n]*)\n(?:.*?\n)?[ \t]*\3[ \t]*(?=\n|$)"
)
# Where one simple command ends: `&&`, `||`, `;`, `|` (not `>|`), a newline, a
# parenthesis, or a background `&` (not the `&` of `&>` or `2>&1`).
COMMAND_SEPARATORS = r"&&|\|\||(?<!>)\||[;\n()]|(?<![<>])&(?!>)"
# A redirect and its target word: `>`, `>>` or `>|`, with or without a digit or `&`
# before it, then the word, optionally quoted. The arrows `->` and `=>` are not redirects.
REDIRECT_TARGET = r"(?<![-=<])>>?\|?[ \t]*(['\"]?)([^\s'\"<>|&;()]+)\1"
# Clustered short flags that may come before `-i` in `sed -Ei` and `perl -wpi`.
SED_FLAGS = "Enrsuz"
PERL_FLAGS = "0123456789alnpwWXtT"
# Words that run the next word as the program, and their options that take a value.
PREFIX_COMMANDS = ("sudo", "env", "command")
PREFIX_OPTIONS_WITH_VALUE = frozenset(
    {"-u", "-g", "-C", "--unset", "--chdir", "--user", "--group"}
)


def _in_place(arg, flags):
    """True when `arg` is a short-flag cluster whose first flag after `flags` is `i`."""
    if not arg.startswith("-") or arg.startswith("--"):
        return False
    return arg[1:].lstrip(flags).startswith("i")


def _is_assignment(word):
    """`VAR=value`, the environment a simple command may start with."""
    variable, equals, _ = word.partition("=")
    return bool(equals) and variable.isidentifier()


def _names_artifact(word, relative, absolutes):
    """True when the target word `word` is the artifact itself, not a file of its name.

    A relative word, after one leading `./` is stripped, must be the project-relative
    path or a `/`-boundary suffix of it (`feat.md` and `prd/feat.md` from inside the
    homes). An absolute word must be the artifact's absolute path or its realpath. A
    file of the same name elsewhere (`/tmp/feat.md`, `~/backup/feat.md`) is not it.
    """
    if not word or word.startswith("~"):
        return False
    if os.path.isabs(word):
        return os.path.normpath(word) in absolutes
    if word.startswith("./"):
        word = word[2:]
    return bool(word) and (word == relative or relative.endswith("/" + word))


def _program(operands):
    """The program a simple command runs, and its arguments.

    What only runs the program is skipped: `VAR=value` words, and `sudo`, `env` or
    `command` with their options (`env -i -u NAME`). A leading `\\` (`\\cp`, which
    bypasses an alias) is dropped.
    """
    index = 0
    while index < len(operands):
        word = operands[index].lstrip("\\")
        if _is_assignment(word):
            index += 1
        elif word in PREFIX_COMMANDS:
            index += 1
            while index < len(operands) and operands[index].startswith("-"):
                index += 2 if operands[index] in PREFIX_OPTIONS_WITH_VALUE else 1
        else:
            return os.path.basename(word), operands[index + 1:]
    return None, []


def _command_writes(words, is_artifact):
    """True when one simple command, as its words, writes to the artifact.

    Redirects are left to the redirect rule: a word holding `<` or `>` is skipped, and
    so is the next word when the operator stands alone (`> f`).
    """
    operands = []
    skip_next = False
    for word in words:
        if skip_next:
            skip_next = False
            continue
        if "<" in word or ">" in word:
            skip_next = word.endswith(("<", ">", "|"))
            continue
        operands.append(word.strip("'\""))
    program, args = _program(operands)
    files = [arg for arg in args if not arg.startswith("-")]

    if program == "tee":
        return any(is_artifact(word) for word in files)
    if program in ("sed", "gsed") and any(
        arg.startswith("--in-place") or _in_place(arg, SED_FLAGS) for arg in args
    ):
        return any(is_artifact(word) for word in files)
    if program == "perl" and any(_in_place(arg, PERL_FLAGS) for arg in args):
        return any(is_artifact(word) for word in files)
    if program == "git" and files[:1] == ["mv"]:
        program, files = "mv", files[1:]
    if program in ("mv", "cp", "install"):
        return bool(files) and is_artifact(files[-1])
    return False


def writes_file(command, relative, absolute):
    """True when `command` writes to the artifact in a shape the window accepts.

    The artifact is `relative`, its project-relative path, at `absolute`. The shapes:
    - a redirect: `> f`, `>> f`, `>| f`, `&> f`, `2> f`, with or without the space
      (`cat > f <<EOF` is one);
    - `tee [-a] ... f`;
    - `sed -i...` or `sed --in-place...` (also `gsed`), and `perl -i...`, `perl -pi...`
      or `perl -wpi...`, with f as an operand;
    - f as the last operand of `mv`, `git mv`, `cp` or `install`, the destination.
    A program may follow `VAR=value` words, `sudo`, `env` or `command`, or carry a
    leading `\\`. The target f must be the artifact itself (`_names_artifact`), so a
    copy elsewhere that keeps the name (`cp f /tmp/f`) is no write. Anything else is no
    write either: `cat f`, `grep x f`, `wc f`, a script that takes f as an argument, a
    heredoc body that mentions f. A session that only reads an artifact so never claims
    an external editor's concurrent write.

    This is a token scan, not a shell parser. Quotes count only around a whole word,
    and a `>` inside a quoted string reads as a redirect. What it misses (a quoted name
    with spaces, `cp f dir/`, a target through a variable, `../` or `git -C`, a
    heredoc fed to a shell) costs a claim, and the diff evidence may still make it.
    """
    name = relative.rsplit("/", 1)[-1]
    if not name or name not in command:
        return False
    import re

    absolutes = {os.path.normpath(absolute), os.path.realpath(absolute)}

    def is_artifact(word):
        return _names_artifact(word, relative, absolutes)

    text = re.sub(HEREDOC_BODY, r"\1", command.replace("\\\n", " "), flags=re.S)
    if any(is_artifact(m.group(2)) for m in re.finditer(REDIRECT_TARGET, text)):
        return True
    return any(
        _command_writes(segment.split(), is_artifact)
        for segment in re.split(COMMAND_SEPARATORS, text)
    )


def window_paths(project, command, duration_ms, now):
    """Watched artifacts that changed while the call ran and that the command writes.

    The write-shape check (`writes_file`) keeps another session's Bash call, a read or
    an unrelated command, from claiming the write. No usable duration, no window: the
    call's own span is the whole evidence.
    """
    if not isinstance(command, str) or not command:
        return []
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float)):
        return []
    if not 0 <= duration_ms < float("inf"):
        return []
    start = now - duration_ms / 1000.0 - WINDOW_SLACK_SECONDS
    end = now + WINDOW_SLACK_SECONDS
    found = []
    for path in watch_paths(project):
        if os.path.basename(path) not in command:
            continue  # the common case, decided before any path work
        # As the command would spell it: `watch_paths` joins the homes to the root, so
        # this is the home's own path, not one resolved through a symlink.
        relative = os.path.relpath(path, project.root).replace(os.sep, "/")
        if not writes_file(command, relative, path):
            continue
        mtime = mtime_of(path)
        if mtime is not None and start <= mtime <= end:
            found.append(path)
    return found


def record_bash_claims(payload):
    import time

    now = time.time()  # the call ended just before this hook started
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    if tool_input.get("run_in_background") not in (None, False):
        return
    session = payload.get("session_id")
    if not isinstance(session, str) or not session:
        return  # a claim with no session never names an author

    project = find_project(payload.get("cwd"))
    if project is None or not project.enforces("auto_capture"):
        return

    listed = diff_paths(payload.get("tool_response")) or []
    found = [(path, "diff") for path in dict.fromkeys(listed) if project.covers(path)]
    # A usable diff does not end the search: it never lists a file git ignores or a
    # file in a submodule. The window covers every artifact the diff did not list, and
    # a window claim is weaker than any diff or tool claim, so at worst it ties.
    claimed = {os.path.realpath(path) for path in listed}
    found.extend(
        (path, "window")
        for path in window_paths(
            project, tool_input.get("command"), payload.get("duration_ms"), now
        )
        if os.path.realpath(path) not in claimed
    )
    if not found:
        return

    tool_use_id = payload.get("tool_use_id")
    claims = []
    for path, evidence in found:
        claim = {
            "path": project.relative(path).replace(os.sep, "/"),
            "source": "bash",
            "evidence": evidence,
            "mtime": mtime_of(path),
            "session": session,
        }
        if isinstance(tool_use_id, str) and tool_use_id:
            claim["tool_use_id"] = tool_use_id
        claims.append(claim)
    append_events(project, "shipgate", "artifact-written", claims)


def main() -> None:
    if likely_journaled() is None:
        sys.exit(0)

    payload = read_hook_input()
    if payload.get("tool_name") == "Bash":
        record_bash_claims(payload)
        sys.exit(0)
    if payload.get("tool_name") not in WRITE_TOOLS:
        sys.exit(0)

    target = changed_path(payload)
    if target is None:
        sys.exit(0)

    project = find_project(payload.get("cwd"), os.path.dirname(target))
    if project is None or not project.enforces("auto_capture"):
        sys.exit(0)
    if not project.covers(target):
        sys.exit(0)

    append_event(
        project,
        "shipgate",
        "artifact-written",
        {
            "path": project.relative(target).replace(os.sep, "/"),
            "source": "tool",
            "tool": payload.get("tool_name"),
            "mtime": mtime_of(target),
            "session": payload.get("session_id"),
        },
    )


safe_main(main)
