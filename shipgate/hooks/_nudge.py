"""The context nudge (ADR 0022) — imported by `post_tool_use.py` only after a Bash call
whose stdout names a boundary event, so every other call skips this module's import.

After an append of `design-committed` or `review-verdict`, measure the session's context
from the tail of `transcript_path` and ask `journal.py nudge` whether it is past the
handoff threshold. The hook measures; journal.py decides (hooks hold no policy).
"""

from __future__ import annotations

import os

from _common import find_project, run_journal

# The appends after which a fresh session pays off. journal.py decides whether a verdict
# counts (only `not-ready` does) and whether the context is past the threshold. The hook's
# NUDGE_WORDS and journal.py's NUDGE_EVENTS name the same two (a test holds them equal).
BOUNDARY_EVENTS = ("design-committed", "review-verdict")
# `append`'s text summary: `appended <type> to <stream>: seq <n>, version <n>`.
APPEND_SUMMARY = (
    r"appended (" + "|".join(BOUNDARY_EVENTS) + r") to (\S+): seq (\d+), version \d+"
)
MAX_JSON_STDOUT = 64 * 1024  # a larger stdout is no append's `--json` output
# The transcript tail read for the last usage record: a small window first, a larger one
# only when a big record (a long tool result) sits after it.
TRANSCRIPT_WINDOWS = (256 * 1024, 4 * 1024 * 1024)
MAX_STREAM_LENGTH = 255
MAX_NUDGE_CHARS = 400


def _seq(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def boundary_append(tool_response):
    """`(event, stream, seq)` of the last boundary event a Bash call's stdout shows
    appended, or None.

    The caller has already found one of the words in the stdout (`maybe_boundary`). Read
    `append --json` output (an object, or a batch's array) or the text summary. Only a
    written row counts: it carries a `seq`. A refused `--json` append prints an `error`
    object with `type` and `stream` but no `seq`, and a duplicate is not an append.
    `journal.py nudge` then checks that the seq is the stream's newest event of its type,
    so a quoted old append line prints nothing. When one call appended several, the
    newest `design-committed` wins over a verdict: a design commit alone earns the advice,
    and a later `ready` verdict must not hide it.
    """
    if not isinstance(tool_response, dict):
        return None
    stdout = tool_response.get("stdout")
    if not isinstance(stdout, str):
        return None
    import json
    import re

    found = []
    text = stdout.strip()
    if text[:1] in ("[", "{") and len(text) <= MAX_JSON_STDOUT:
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        for entry in parsed if isinstance(parsed, list) else [parsed]:
            if (
                isinstance(entry, dict)
                and "error" not in entry
                and entry.get("type") in BOUNDARY_EVENTS
                and isinstance(entry.get("stream"), str)
                and _seq(entry.get("seq")) is not None
                and entry.get("duplicate") is not True
            ):
                found.append((entry["type"], entry["stream"], entry["seq"]))
    if not found:
        found = [
            (match.group(1), match.group(2), int(match.group(3)))
            for match in re.finditer(APPEND_SUMMARY, stdout)
        ]
    if not found:
        return None
    designs = [entry for entry in found if entry[0] == "design-committed"]
    found = (designs or found)[-1]
    stream = found[1]
    if not stream or len(stream) > MAX_STREAM_LENGTH or not stream.isprintable():
        return None
    return found


def _read_tail(path, size):
    """The last `size` bytes of the regular file at `path`, and whether the read began
    mid-file; None when it is not a regular file or cannot be read.

    The path comes from the harness, but open it as untrusted all the same: non-blocking,
    so a FIFO cannot hang the hook, and refused unless it is a regular file.
    """
    import stat

    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None
        start = max(0, info.st_size - size)
        os.lseek(fd, start, os.SEEK_SET)
        chunks = []
        remaining = info.st_size - start
        while remaining > 0:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks), start > 0
    except (OSError, ValueError, OverflowError):
        return None
    finally:
        if fd is not None:
            os.close(fd)


def _usage_tokens(record):
    """Context tokens of one main-thread assistant record, or None."""
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return None
    if record.get("isSidechain") is True:
        return None
    message = record.get("message")
    if not isinstance(message, dict) or message.get("model") == "<synthetic>":
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    total = 0
    for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        value = usage.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        total += value
    return total or None


def context_tokens(transcript_path):
    """The session's context size: input, cache-creation and cache-read tokens of the
    last main-thread assistant record in the transcript; None when none is found."""
    import json

    if not isinstance(transcript_path, str) or not os.path.isabs(transcript_path):
        return None
    for size in TRANSCRIPT_WINDOWS:
        tail = _read_tail(transcript_path, size)
        if tail is None:
            return None
        raw, cut = tail
        lines = raw.split(b"\n")
        if cut:
            lines = lines[1:]  # the first line is a fragment
        for line in reversed(lines):
            if b'"usage"' not in line or b'"assistant"' not in line:
                continue
            try:
                tokens = _usage_tokens(json.loads(line.decode("utf-8", "replace")))
            except ValueError:
                continue
            if tokens is not None:
                return tokens
        if not cut:
            return None  # the whole file was read
    return None


def context_nudge(payload):
    """The nudge line after a boundary append past the threshold, or None.

    The hook measures; `journal.py nudge` decides (hooks hold no policy). It runs only
    after `boundary_append` matched, so a call that is not a phase boundary never reads
    the transcript or starts a process.
    """
    boundary = boundary_append(payload.get("tool_response"))
    if boundary is None:
        return None
    project = find_project(payload.get("cwd"))
    if project is None:
        return None
    tokens = context_tokens(payload.get("transcript_path"))
    if tokens is None:
        return None
    event, stream, seq = boundary
    args = ["nudge", f"--stream={stream}", f"--event={event}", f"--tokens={tokens}",
            f"--seq={seq}"]
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and os.path.isabs(cwd) and cwd.isprintable():
        # The session's directory: the config layers start there (ADR 0018), not at the
        # project root where run_journal runs. journal.py ignores one outside the root.
        args.append(f"--start={cwd}")
    result = run_journal(project, args)
    if result is None or result.returncode != 0:
        return None
    line = " ".join((result.stdout or "").split())[:MAX_NUDGE_CHARS]
    return line or None
