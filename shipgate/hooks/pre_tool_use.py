#!/usr/bin/env python3
"""PreToolUse hook — hold a commit or a publish with no go, and refuse a forged go.

ADR 0015, extended by ADR 0023 §14-§18. The hook has two rules: the command gate and the
forgery net.

**The command gate** (ADR 0023 §14). On a journaled project, a model's `git commit` is
held until the stream of its branch holds the user's go for the commit gate, and
`git push`, `git subtree push`, `gh pr create` and `glab mr create` until it holds the go
for the publish gate. `gated_commands` finds them in the lexed line; the branch is read in
the command's directory (git's `-C`, or a literal `cd` before it, else the payload's
`cwd`), and `journal.py authorize` answers for that branch. A `hold` is a `deny` with the
journal's message. A project with no sidecar, `enforce.command_gate: false`, a directory
with no branch, a branch with no stream or a finished one, and any failure of git or the
journal pass the command (§15). A dry run is held like any commit or push: its flags
cannot be read safely from the words (`--dry-run --no-dry-run`, `-m --dry-run`).

**The forgery net** (ADR 0015, §18).

Only the user approves a commit or a publish. The recorder hook writes the user's go from
a gate question answer or a typed gate word, the HUD's publish dialog and the user's own
`!` command write it too, and none of them passes through PreToolUse. So a model's Bash
call that appends one of these to the journal is refused:

* a `gate-decision` that carries `source`, the marker of the user's own approval, at any
  gate, whatever the marker and the actor. 0.28.0 let a read go (`source: read`) through
  here; #52 retired it (ADR 0023, amendment A3), and the journal refuses it too;
* a `gate-decision` at the commit or the publish gate (`gate`, or its alias `kind`;
  trimmed, any case) that names the user: an actor of role `user` (`--actor user`,
  `user@...`, a JSONL `actor`) or `raised_by: user`;
* a `reply-witnessed` event, whatever its actor or payload: a literal `--type` (trimmed,
  any case) or a JSONL line whose `type` names it. Only the recorder hook writes a
  witness.
* `journal.py import`, whatever the file (ADR 0023 §20): it writes rows with no check.
  The user runs an import with `!` when moving a journal between machines.
* a command that runs the recorder hook script `reply.py` (ADR 0023 §21), as the program,
  as a Python's script word, or through a script word the hook cannot read on a line that
  names the script: it writes the user's go and witnesses, and only Claude Code runs it.

The actor is the `--actor` option, or a JSONL line's own `actor`. With neither, journal.py
records the role `orchestrator`, which is not the user. A decision at another gate stays
allowed with every actor, and so does every other event.

The hook lexes the command line itself (no shell runs): quotes, `\\` escapes, `$'...'`,
the operators `;` `&&` `||` `|` `&` and newlines, `(`/`)` groups, comments, redirections,
heredoc bodies (quoted and unquoted delimiters, `<<-`) and here-strings. A simple command
is a journal append when one of its words has the basename `journal.py` (or is not
literal) and the first literal word after it that is not a top-level `--db` is `append`.
The append's options are read as argparse reads them: `--opt value`, `--opt=value` and
unique abbreviations. `--batch` reads stdin from a heredoc, a here-string, or a pipe from
`echo`, `printf` or `cat` fed by one of those. A literal command line given to `sh -c`,
`bash -c`, `zsh -c`, `eval`, a shell fed a literal script on stdin, or a command
substitution is lexed too, to a bounded depth. So is every literal word that names both
`journal.py` and `append`, unless its command only prints or stores text (`git`, `echo`,
`grep`, ...): a wrapper such as `timeout 5 bash -c '...'` hides the shell otherwise.
Wrappers with options and operands of their own (`timeout 60`, `nice -n 5`, `sudo -u
alice`, `env -u X`, `stdbuf -o L`) are skipped to find the command they run, so a shell
that reads its script on stdin behind one is lexed too. A literal stdin of any other
command that is not text-only is lexed as well, and an event found there is refused.

What the hook cannot read, it refuses when the append could be a `gate-decision` or a
witness: a payload from a variable, a command substitution, a file, another command's
output, a `--batch` with no visible stdin, a subcommand from a variable, an unquoted
expansion among the arguments (it may split into a later `--type`), or a shell that reads
a script on a stdin the hook cannot see. A `--type` the hook cannot read is refused
whatever its payload, because a witness is refused whatever its payload. An append whose
literal `--type` names another event type passes whatever its payload.

This is a net, not a boundary. The model has a shell and can still write the approval by
other means, and these are out of scope:

* a direct SQLite write, `python3 -c`, or a copied or renamed script (the recorder
  script included), or a script of the model's own that drives the journal;
* a nested `claude` session that resumes the parent session and fires its real hooks;
* a shell function, an alias, or a sourced file (`. f`, `source f`) that runs the append;
* a shell given a command line from a variable (`bash -c "$X"`, `eval "$X"`) or a script
  file;
* a wrapper the table below does not know, whose stdin script takes its payload from a
  variable (only an event found in such a stdin refuses);
* any other indirection the lexer does not follow.

This hook fires on every Bash call in every project, so the fast path comes first: decode
stdin, and exit 0 with no output and no file read unless the command contains both
`journal.py` and `append` or `import`, or one of the command hints (`commit`, `push`,
`create`, `new`). A command hint reads no file either unless the lexed line holds a gated
command. `_common`
is imported only to print a refusal or to answer for a gated command. A crash of the
forgery net exits 0 silently, except on a command that names `journal.py`, `append` and
`publish`, or `journal.py` and `import`: that one is refused (ADR 0015, ADR 0023 §20). A
crash of the command gate passes the command.
"""

from __future__ import annotations

import json
import sys

GATE_DECISION = "gate-decision"
REPLY_WITNESSED = "reply-witnessed"
COMMIT_GATE = "commit"
PUBLISH_GATE = "publish"
USER_GATES = (COMMIT_GATE, PUBLISH_GATE)
USER_ROLE = "user"
# `_common.SESSION_ENV`, kept here because the fast path does not import `_common`.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"

# How many times a string is lexed again as a command line (`sh -c`, `eval`, backticks, a
# shell's stdin script), and how deep `$( ... )` may nest in one string.
MAX_RELEX_DEPTH = 3
MAX_SUBSTITUTION_DEPTH = 16
# How many producers a pipe is followed back through (`echo x | cat | cat | ...`).
MAX_PIPE_HOPS = 8

# The options journal.py's argparse accepts. Top level: `-h/--help`, `--db PATH`.
TOP_OPTIONS = {"--help": False, "--db": True}
# `append`: option -> takes a value.
APPEND_OPTIONS = {
    "--help": False,
    "--db": True,
    "--stream": True,
    "--type": True,
    "--data": True,
    "--batch": False,
    "--expect": True,
    "--actor": True,
    "--force": False,
    "--force-reason": True,
    "--new-type": False,
    "--json": False,
}

SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
RESERVED = {"!", "{", "then", "do", "else", "elif", "if", "while", "until"}
# Commands that run the command after them: (options that take a value, operands before the
# command). `timeout 60 bash`, `nice -n 5 sh`, `sudo -u alice bash`.
_TIMEOUT = (("-s", "-k", "--signal", "--kill-after"), 1)
WRAPPERS = {
    "command": ((), 0),
    "builtin": ((), 0),
    "exec": (("-a",), 0),
    "nohup": ((), 0),
    "time": (("-f", "-o", "--format", "--output"), 0),
    "env": (("-u", "-C", "-S", "--unset", "--chdir", "--split-string"), 0),
    "sudo": (
        ("-u", "-g", "-C", "-h", "-p", "-U", "-r", "-t", "-D", "-R", "-T", "--user",
         "--group", "--close-from", "--host", "--prompt", "--other-user", "--role",
         "--type", "--chdir", "--chroot", "--command-timeout"),
        0,
    ),
    "doas": (("-u", "-C"), 0),
    "nice": (("-n", "--adjustment"), 0),
    "timeout": _TIMEOUT,
    "gtimeout": _TIMEOUT,
    "stdbuf": (("-i", "-o", "-e", "--input", "--output", "--error"), 0),
    "ionice": (("-c", "-n", "-p", "-P", "-u", "--class", "--classdata"), 0),
    "caffeinate": (("-t", "-w"), 0),
    # macOS: `arch -arm64 python3 …`, `xcrun python3 …` (ADR 0023 §21).
    "arch": (("-arch", "-e", "-d"), 0),
    "xcrun": (("--sdk", "--toolchain", "-sdk", "-toolchain"), 0),
}
# Commands that print, search or store their arguments and never run them: a literal word
# of theirs that names a journal append is text (a commit message), not a command line.
TEXT_ONLY = {
    "git", "gh", "glab", "echo", "printf", "grep", "egrep", "fgrep", "rg", "jq", "cat",
    "head", "tail", "tee",
}

REASON_MARKER = "marker"
REASON_USER = "user"
REASON_WITNESS = "witness"
REASON_IMPORT = "import"
REASON_RECORDER = "recorder"
REASON_SESSION = "session"
REASON_OPAQUE = "opaque"
REASON_SPLIT = "split"
REASON_CRASH = "crash"
REASON_PRIORITY = (
    REASON_MARKER, REASON_USER, REASON_WITNESS, REASON_IMPORT, REASON_RECORDER,
    REASON_SESSION,
    REASON_OPAQUE, REASON_SPLIT,
)
# The reasons that name an event the hook read, not a part it could not read.
EVENT_REASONS = (
    REASON_MARKER, REASON_USER, REASON_WITNESS, REASON_IMPORT, REASON_RECORDER,
)
# The recorder hook script (ADR 0023 §21): it writes the user's go and witnesses.
RECORDER = "reply.py"

# FR-024: the paths of this release (ADR 0023 and its amendment, ADR 0015).
# #55: the net reads no branch and runs no journal, so it prints no go request of its
# own. It points at the two places that print one, and names this plugin's journal
# script (`deny`), so a session never searches the disk for an older copy.
TAIL = (
    "Only the user approves a commit or a publish. When the command gate holds a commit, "
    "a push or a PR/MR creation, its refusal prints the full `go-requested` command: run "
    "it as printed, "
    "then ask the gate question with the header `Commit` or `Publish`, or let the user "
    "type the gate word: the recorder hook records the go. After any other reply, the "
    "recorder's context line prints a new `go-requested` command: run it and ask one "
    "confirming question with that header and the gate word as the first option: the "
    "recorder hook records the click. The user can also choose \"Approve publishing\" "
    "in the shipgate-hud publish dialog, or run the append themselves with `!` and "
    "`\"source\": \"shell\"`. Never record it on their behalf."
)
MESSAGES = {
    REASON_MARKER: (
        "shipgate refused this command: it appends a gate-decision that carries "
        "`source`, the marker of the user's own approval. The model writes no marker, "
        "`read` included."
    ),
    REASON_USER: (
        "shipgate refused this command: it records a commit or publish gate-decision as "
        "the user's (an actor of role `user`, or `raised_by: user`)."
    ),
    REASON_SESSION: (
        "shipgate refused this command: it sets or clears `CLAUDE_CODE_SESSION_ID` for a "
        "journal write. A go request counts for the session that appends it, so a write "
        "runs only in its own session's name."
    ),
    REASON_RECORDER: (
        "shipgate refused this command: it runs the recorder hook script "
        "(`hooks/reply.py`), which writes the user's go and witnesses. Only Claude Code "
        "runs it, on the user's own prompt or question answer. A command that only "
        "writes text naming the script should write the file with the Write tool."
    ),
    REASON_IMPORT: (
        "shipgate refused this command: it runs `journal.py import`, which writes the "
        "rows of a file with no check, so it could write the user's go. Only the user "
        "imports a journal: when you move one between machines, the user runs the "
        "import with `!`."
    ),
    REASON_WITNESS: (
        "shipgate refused this command: it appends a `reply-witnessed` event. Only the "
        "recorder hook writes a witness, when the user replies to a go request."
    ),
    REASON_OPAQUE: (
        "shipgate refused this command: it appends to the journal with an event type, a "
        "payload or an actor the hook cannot read (a variable, a command substitution, "
        "a file, another command's output, or no visible stdin for --batch). Write them "
        "literally: `--type <event> --data '{...}'` or a quoted heredoc (<<'EOF')."
    ),
    REASON_SPLIT: (
        "shipgate refused this command: a journal append takes its subcommand or "
        "options from a variable or substitution the hook cannot read, and an unquoted "
        "one may split into more options. Quote the expansion (\"$S\") and write the "
        "subcommand and options literally."
    ),
    REASON_CRASH: (
        "shipgate refused this command: the hook could not read this journal append, "
        "and it names publish."
    ),
}


class Opaque(Exception):
    """A part of the command the hook must not guess at."""


# -- the lexer ---------------------------------------------------------------------------


class Word:
    """One shell word after quote removal.

    `literal` is False when the shell would expand it (a parameter, a command or process
    substitution, arithmetic, a backtick, an unquoted glob). `split` is True when such an
    expansion stands outside double quotes: the shell may split it into several words, so
    it can hide an option, not just a value. `quoted` is True when any part was quoted or
    escaped — it makes a heredoc delimiter's body literal.
    """

    __slots__ = ("text", "literal", "quoted", "split")

    def __init__(self, text, literal, quoted, split=False):
        self.text = text
        self.literal = literal
        self.quoted = quoted
        self.split = split


class Heredoc:
    __slots__ = ("delimiter", "quoted", "strip_tabs", "body", "literal")

    def __init__(self, delimiter, quoted, strip_tabs):
        self.delimiter = delimiter
        self.quoted = quoted
        self.strip_tabs = strip_tabs
        self.body = None
        self.literal = True


class Command:
    """A simple command: its words, its stdin redirect, and the command piped into it."""

    __slots__ = ("words", "stdin", "pipe_from")

    def __init__(self, pipe_from=None):
        self.words = []
        # None, ("heredoc", Heredoc), ("text", str) or ("opaque",)
        self.stdin = None
        # None, a Command, or OPAQUE_SOURCE (a group, a subshell)
        self.pipe_from = pipe_from


OPAQUE_SOURCE = object()

_WORD_BREAK = " \t\n;&|()<>"
_COMMAND_BREAKS = " \t\n;&|"
_NAME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
_SPECIAL_PARAMS = "@*#?$!-0123456789"
_OPERATORS = ("&&", "||", "|&", ";;", ";&", "|", ";", "&", "(", ")")
_REDIRECTS = ("<<<", "<<-", "<<", "<&", "<>", "<", "&>>", "&>", ">>", ">&", ">|", ">")
_STDIN_REDIRECTS = {"<<<", "<<-", "<<", "<&", "<>", "<"}


def lex(source, depth=0):
    """Every simple command in `source`, nested ones included, in order."""
    if depth > MAX_RELEX_DEPTH:
        if "journal.py" in source and "append" in source:
            raise Opaque("nested too deep")
        return []
    out = []
    lexer = _Lexer(source, depth, out)
    lexer.parse(closer=False, nesting=0)
    lexer.close_heredocs()
    return out


class _Lexer:
    def __init__(self, source, depth, out):
        self.s = source
        self.n = len(source)
        self.i = 0
        self.depth = depth
        self.out = out
        self.pending = []

    # -- commands --

    def parse(self, closer, nesting):
        """Read commands until the end, or until the `)` that closes a `$(`."""
        if nesting > MAX_SUBSTITUTION_DEPTH:
            raise Opaque("substitutions nested too deep")
        command = Command()
        redirect = None
        groups = 0  # `(` groups opened inside this parse, so their `)` is not the closer
        while True:
            token = self.token(nesting)
            if token is None:
                break
            kind, value = token
            if redirect is not None:
                operator, fd = redirect
                redirect = None
                if kind == "word":
                    self.attach(command, operator, fd, value)
                    continue
            if kind == "word":
                command.words.append(value)
                continue
            if kind == "redirect":
                redirect = value
                continue
            # an operator
            self.finish(command)
            if value == "(":
                groups += 1
            elif value == ")":
                if groups == 0 and closer:
                    return
                groups = max(0, groups - 1)
            if value in ("|", "|&"):
                command = Command(pipe_from=command if command.words else OPAQUE_SOURCE)
            else:
                command = Command()
        self.finish(command)

    def finish(self, command):
        if command.words or command.stdin is not None:
            self.out.append(command)

    def attach(self, command, operator, fd, word):
        reads_stdin = fd in (None, 0)
        if operator in ("<<", "<<-"):
            heredoc = Heredoc(word.text, word.quoted, operator == "<<-")
            self.pending.append(heredoc)
            if reads_stdin:
                command.stdin = ("heredoc", heredoc)
        elif operator == "<<<":
            if reads_stdin:
                command.stdin = ("text", word.text + "\n") if word.literal else ("opaque",)
        elif operator in _STDIN_REDIRECTS:
            if reads_stdin:
                command.stdin = ("opaque",)

    # -- tokens --

    def token(self, nesting):
        s, n = self.s, self.n
        while self.i < n:
            c = s[self.i]
            if c in " \t":
                self.i += 1
            elif c == "\\" and s.startswith("\\\n", self.i):
                self.i += 2
            elif c == "#":
                end = s.find("\n", self.i)
                self.i = n if end < 0 else end
            else:
                break
        if self.i >= n:
            return None
        c = s[self.i]
        if c == "\n":
            self.i += 1
            self.read_heredocs()
            return ("op", "\n")
        # A redirection, with an optional fd number in front of it.
        j = self.i
        while j < n and s[j].isdigit():
            j += 1
        fd = int(s[self.i:j]) if j > self.i else None
        if j < n and s[j] in "<>&":
            if not s.startswith(("<(", ">("), j):
                for operator in _REDIRECTS:
                    if s.startswith(operator, j):
                        if fd is not None and operator.startswith("&"):
                            break
                        self.i = j + len(operator)
                        return ("redirect", (operator, fd))
        if fd is None:
            for operator in _OPERATORS:
                if s.startswith(operator, self.i):
                    self.i += len(operator)
                    return ("op", operator)
        if s.startswith(("<(", ">("), self.i):
            # A process substitution: a word nobody can read, whose commands still run.
            self.i += 2
            self.parse(closer=True, nesting=nesting + 1)
            return ("word", Word("", False, False))  # one path: never split
        return ("word", self.word(nesting))

    def word(self, nesting):
        s, n = self.s, self.n
        parts = []
        literal = True
        quoted = False
        split = False
        while self.i < n:
            c = s[self.i]
            if c in _WORD_BREAK:
                break
            if c == "\\":
                if s.startswith("\\\n", self.i):
                    self.i += 2
                elif self.i + 1 < n:
                    parts.append(s[self.i + 1])
                    self.i += 2
                    quoted = True
                else:
                    parts.append("\\")
                    self.i += 1
            elif c == "'":
                end = s.find("'", self.i + 1)
                end = n if end < 0 else end
                parts.append(s[self.i + 1:end])
                self.i = end + 1
                quoted = True
            elif c == '"':
                self.i += 1
                if not self.double_quoted(parts, nesting):
                    literal = False
                quoted = True
            elif c == "$" and s.startswith("$'", self.i):
                self.i += 2
                parts.append(self.ansi_c())
                quoted = True
            elif c == "$" and s.startswith('$"', self.i):
                self.i += 2
                if not self.double_quoted(parts, nesting):
                    literal = False
                quoted = True
            elif c == "$":
                if not self.dollar(parts, nesting):
                    literal = False
                    split = True
            elif c == "`":
                self.backtick(parts)
                literal = False
                split = True
            else:
                if c in "*?[":
                    literal = False
                    split = True
                parts.append(c)
                self.i += 1
        return Word("".join(parts), literal, quoted, split)

    def double_quoted(self, parts, nesting):
        """Read up to the closing `"`. Returns whether the text was literal."""
        s, n = self.s, self.n
        literal = True
        while self.i < n:
            c = s[self.i]
            if c == '"':
                self.i += 1
                return literal
            if c == "\\" and self.i + 1 < n:
                following = s[self.i + 1]
                if following == "\n":
                    pass
                elif following in '$`"\\':
                    parts.append(following)
                else:
                    parts.append("\\" + following)
                self.i += 2
            elif c == "$":
                if not self.dollar(parts, nesting):
                    literal = False
            elif c == "`":
                self.backtick(parts)
                literal = False
            else:
                parts.append(c)
                self.i += 1
        return literal

    def dollar(self, parts, nesting):
        """Read an expansion at `$`. Returns whether it was a plain `$` (literal)."""
        s, n = self.s, self.n
        start = self.i
        following = s[self.i + 1] if self.i + 1 < n else ""
        if s.startswith("$((", self.i):
            self.i = self.balanced(self.i + 1, "(", ")")
        elif following == "(":
            self.i += 2
            self.parse(closer=True, nesting=nesting + 1)
        elif following == "{":
            self.i = self.balanced(self.i + 1, "{", "}")
        elif following and following in _SPECIAL_PARAMS:
            self.i += 2
        elif following and following in _NAME_CHARS:
            self.i += 1
            while self.i < n and s[self.i] in _NAME_CHARS:
                self.i += 1
        else:
            parts.append("$")
            self.i += 1
            return True
        parts.append(s[start:self.i])
        return False

    def balanced(self, start, opening, closing):
        """The index after the `closing` that matches the `opening` at `start`."""
        s, n = self.s, self.n
        level = 0
        i = start
        while i < n:
            c = s[i]
            if c == "\\":
                i += 2
                continue
            if c == "'":
                end = s.find("'", i + 1)
                i = n if end < 0 else end + 1
                continue
            if c == opening:
                level += 1
            elif c == closing:
                level -= 1
                if level == 0:
                    return i + 1
            i += 1
        return n

    def backtick(self, parts):
        """Read a backtick substitution and lex its command line again."""
        s, n = self.s, self.n
        start = self.i
        self.i += 1
        inner = []
        while self.i < n:
            c = s[self.i]
            if c == "`":
                self.i += 1
                break
            if c == "\\" and self.i + 1 < n and s[self.i + 1] in "`\\$":
                inner.append(s[self.i + 1])
                self.i += 2
                continue
            inner.append(c)
            self.i += 1
        parts.append(s[start:self.i])
        self.out.extend(lex("".join(inner), self.depth + 1))

    def ansi_c(self):
        """Read a `$'...'` string (the `$'` already consumed) and decode its escapes."""
        s, n = self.s, self.n
        raw = []
        while self.i < n:
            c = s[self.i]
            if c == "'":
                self.i += 1
                break
            if c == "\\" and self.i + 1 < n:
                raw.append(s[self.i:self.i + 2])
                self.i += 2
                continue
            raw.append(c)
            self.i += 1
        return interpret_escapes("".join(raw))

    # -- heredocs --

    def read_heredocs(self):
        """Read the bodies of the heredocs the line just ended opened, in order."""
        s, n = self.s, self.n
        pending, self.pending = self.pending, []
        for heredoc in pending:
            lines = []
            while self.i < n:
                end = s.find("\n", self.i)
                line = s[self.i:] if end < 0 else s[self.i:end]
                self.i = n if end < 0 else end + 1
                if heredoc.strip_tabs:
                    line = line.lstrip("\t")
                if line == heredoc.delimiter:
                    break
                lines.append(line)
            settle_heredoc(heredoc, "".join(line + "\n" for line in lines))

    def close_heredocs(self):
        for heredoc in self.pending:
            settle_heredoc(heredoc, "")
        self.pending = []


def settle_heredoc(heredoc, body):
    """Store a body as the command reads it, or mark it non-literal."""
    if heredoc.quoted:
        heredoc.body = body
        return
    if "$" in body or "`" in body:
        heredoc.literal = False
        heredoc.body = body
        return
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body) and body[i + 1] in "\\\n":
            if body[i + 1] == "\\":
                out.append("\\")
            i += 2
            continue
        out.append(c)
        i += 1
    heredoc.body = "".join(out)


_SIMPLE_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
    "e": "\x1b", "E": "\x1b", "\\": "\\", '"': '"', "'": "'", "?": "?",
}


def decode_escape(text, i):
    """Decode the backslash escape at `text[i]`: (decoded text, index after it)."""
    n = len(text)
    if i + 1 >= n:
        return "\\", i + 1
    following = text[i + 1]
    if following in _SIMPLE_ESCAPES:
        return _SIMPLE_ESCAPES[following], i + 2
    if following in "01234567":
        j = i + 2 if following == "0" else i + 1
        k = j
        while k < n and k < j + 3 and text[k] in "01234567":
            k += 1
        return chr(int(text[j:k] or "0", 8) & 0xFF), k
    if following == "x":
        k = i + 2
        while k < n and k < i + 4 and text[k] in "0123456789abcdefABCDEF":
            k += 1
        if k == i + 2:
            return "\\x", k
        return chr(int(text[i + 2:k], 16)), k
    return "\\" + following, i + 2


def interpret_escapes(text):
    """Decode backslash escapes the way `printf`, `echo -e` and `$'...'` do."""
    out = []
    i = 0
    while i < len(text):
        if text[i] == "\\":
            decoded, i = decode_escape(text, i)
            out.append(decoded)
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


# -- reading commands --------------------------------------------------------------------


def basename(path):
    return path.rstrip("/").rsplit("/", 1)[-1]


def command_name(command):
    """The index of the command a simple command runs, or None.

    Assignments, reserved words and wrappers are skipped, with each wrapper's options,
    their values and its operands (`sudo -u alice`, `timeout -k 5 60`), so a wrapped
    `bash` or `git` is seen as itself.
    """
    words = command.words
    i = 0
    while i < len(words):
        word = words[i]
        if not word.literal:
            return i
        text = word.text
        head, equals, _ = text.partition("=")
        assignment = equals and head and not head[0].isdigit()
        if assignment and all(c in _NAME_CHARS for c in head):
            i += 1
            continue
        if text in RESERVED:
            i += 1
            continue
        wrapper = WRAPPERS.get(basename(text))
        if wrapper is None:
            return i
        takes_value, operands = wrapper
        i += 1
        while i < len(words) and words[i].literal and len(words[i].text) > 1 \
                and words[i].text.startswith("-"):
            option = words[i].text
            i += 1
            if option == "--":
                break
            if option in takes_value:
                i += 1
        i += operands
    return None


def stdin_texts(command, hops=0):
    """The texts a command may read on stdin, or None when the hook cannot see them."""
    if hops > MAX_PIPE_HOPS:
        return None
    source = command.stdin
    if source is not None:
        if source[0] == "heredoc":
            heredoc = source[1]
            if not heredoc.literal or heredoc.body is None:
                return None
            return [heredoc.body]
        if source[0] == "text":
            return [source[1]]
        return None
    producer = command.pipe_from
    if producer is None or producer is OPAQUE_SOURCE:
        return None
    return producer_texts(producer, hops + 1)


def producer_texts(command, hops):
    """What `echo`, `printf` or `cat` writes to the pipe, or None for anything else."""
    at = command_name(command)
    if at is None:
        return None
    name = command.words[at]
    args = command.words[at + 1:]
    if not name.literal or any(not arg.literal for arg in args):
        return None
    program = basename(name.text)
    texts = [arg.text for arg in args]
    if program == "echo":
        while texts and len(texts[0]) > 1 and texts[0][0] == "-" \
                and set(texts[0][1:]) <= set("neE"):
            texts = texts[1:]
        joined = " ".join(texts) + "\n"
        return [joined, interpret_escapes(joined)]
    if program == "printf":
        if texts and texts[0] == "--":
            texts = texts[1:]
        if not texts or texts[0].startswith("-"):
            return None
        printed = emulate_printf(texts[0], texts[1:])
        if printed is None:
            return None
        return [printed] + texts + [interpret_escapes(text) for text in texts]
    if program == "cat":
        if all(text == "-" for text in texts):
            return stdin_texts(command, hops)
        return None
    return None


def emulate_printf(fmt, args):
    """printf's output for `%s`, `%b` and `%%` formats; None for any other conversion."""
    out = []
    index = 0
    while True:
        converts = False
        i = 0
        while i < len(fmt):
            c = fmt[i]
            if c == "\\":
                decoded, i = decode_escape(fmt, i)
                out.append(decoded)
                continue
            if c == "%":
                following = fmt[i + 1] if i + 1 < len(fmt) else ""
                if following == "%":
                    out.append("%")
                elif following in ("s", "b"):
                    converts = True
                    value = args[index] if index < len(args) else ""
                    index += 1
                    out.append(value if following == "s" else interpret_escapes(value))
                else:
                    return None
                i += 2
                continue
            out.append(c)
            i += 1
        if not converts or index >= len(args):
            return "".join(out)


def resolve_option(text, options):
    """argparse's reading of `--opt` / `--opt=value`: (option, inline value) or None."""
    name, equals, value = text.partition("=")
    inline = value if equals else None
    if name in options:
        return name, inline
    matches = [option for option in options if option.startswith(name)]
    if len(matches) == 1 and name.startswith("--") and len(name) > 2:
        return matches[0], inline
    return None


def relexed(command, depth):
    """Commands hidden in a literal string a shell or `eval` runs."""
    at = command_name(command)
    if at is None:
        return []
    name = command.words[at]
    if not name.literal:
        return []
    program = basename(name.text)
    args = command.words[at + 1:]
    if program == "eval":
        if args and all(arg.literal for arg in args):
            return lex(" ".join(arg.text for arg in args), depth + 1)
        return []
    if program not in SHELLS:
        return []
    c_mode = False
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg.literal:
            return []
        text = arg.text
        if text == "--":
            i += 1
            break
        if text.startswith("--"):
            if text in ("--rcfile", "--init-file"):
                i += 1
            i += 1
            continue
        if len(text) > 1 and text[0] in "-+":
            flags = text[1:]
            if "c" in flags:
                c_mode = True
            if "o" in flags or "O" in flags:
                i += 1
            i += 1
            continue
        break
    rest = args[i:]
    if c_mode:
        if rest and rest[0].literal:
            return lex(rest[0].text, depth + 1)
        return []
    if rest and not (rest[0].literal and rest[0].text == "-"):
        return []  # a script file
    texts = stdin_texts(command)
    if texts is None:
        if command.stdin is not None or command.pipe_from is not None:
            # `{ echo '...'; } | sh`: a script the hook cannot see, in a command line that
            # names a journal append (the fast path saw to that).
            raise Opaque("a shell reads an unreadable script")
        return []
    found = []
    for text in texts:
        found.extend(lex(text, depth + 1))
    return found


# -- the rule ----------------------------------------------------------------------------


def _folded(value):
    return value.strip().casefold() if isinstance(value, str) else None


def _is_user(actor):
    """True for an actor label of role `user` (`user`, `user@alice`, ` User `)."""
    if not isinstance(actor, str):
        return False
    return actor.partition("@")[0].strip().casefold() == USER_ROLE


def judge_event(data, actor):
    """The reason to refuse a gate-decision with this data and actor, or None.

    `actor` is a string, None (no actor: journal.py's default), or a non-literal Word.
    Any `source` is refused, whatever its value and the actor: the model writes no
    marker (ADR 0023 amendment A3).
    """
    if not isinstance(data, dict):
        return None
    if "source" in data:
        return REASON_MARKER
    gates = [_folded(data.get(key)) for key in ("gate", "kind") if key in data]
    if not any(gate in USER_GATES for gate in gates):
        return None
    if _folded(data.get("raised_by")) == USER_ROLE:
        return REASON_USER
    if isinstance(actor, Word):
        return REASON_OPAQUE
    if _is_user(actor):
        return REASON_USER
    return None


def judge_jsonl(texts, args_actor):
    reasons = []
    for text in texts:
        for line in text.splitlines():
            line = line.lstrip("﻿")
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(record, dict):
                continue
            event_type = _folded(record.get("type"))
            if event_type == REPLY_WITNESSED:
                reasons.append(REASON_WITNESS)
                continue
            if event_type != GATE_DECISION:
                continue
            actor = record.get("actor")
            if not (isinstance(actor, str) and actor):
                actor = args_actor
            reasons.append(judge_event(record.get("data"), actor))
    return reasons


APPEND_ONLY_OPTIONS = tuple(
    option for option in APPEND_OPTIONS if option not in TOP_OPTIONS and option != "--json"
)


def names_append_options(words):
    """True when a literal word reads as an option only `append` takes."""
    for word in words:
        if word.literal and word.text.startswith("--"):
            option = resolve_option(word.text, APPEND_OPTIONS)
            if option and option[0] in APPEND_ONLY_OPTIONS:
                return True
    return False


def top_option_with_value(word):
    """True for an unsplit `--db=<expansion>`: a top-level option and its unread value."""
    if word.split or not word.text.startswith("--"):
        return False
    name, equals, _ = word.text.partition("=")
    if not equals or "$" in name or "`" in name:
        return False
    option = resolve_option(name, TOP_OPTIONS)
    return bool(option and TOP_OPTIONS[option[0]])


def append_args(command):
    """(the words after `append`, whether an unread word comes first) for each append.

    A word the hook cannot read where the subcommand, or a top-level option that may split
    into it, would stand makes the rest a possible append, read as opaque. Behind a
    `journal.py` the hook can name, that always counts; behind a non-literal word that only
    might be the script, it counts when the rest carries an option only `append` takes, so
    `cp $SRC $DST` stays a copy.
    """
    words = command.words
    found = []
    for at, word in enumerate(words):
        named = word.literal and basename(word.text) == "journal.py"
        if word.literal and not named:
            continue
        i = at + 1
        while i < len(words):
            candidate = words[i]
            if not candidate.literal:
                if top_option_with_value(candidate):
                    i += 1  # `--db="$DB"`: one word, a value of a known option
                    continue
                rest = words[i + 1:]
                if named or names_append_options(rest):
                    found.append((rest, True))
                break
            text = candidate.text
            if text.startswith("-"):
                option = resolve_option(text, TOP_OPTIONS)
                i += 1
                if option and TOP_OPTIONS[option[0]] and option[1] is None:
                    value = words[i] if i < len(words) else None
                    if value is not None and value.split:
                        rest = words[i + 1:]
                        if named or names_append_options(rest):
                            found.append((rest, True))
                        break
                    i += 1
                continue
            if text == "append":
                found.append((words[i + 1:], False))
            break
    return found


def inline_option(word):
    """`--opt="$X"`: (option, its unread value) when only the value is non-literal."""
    if word.split or not word.text.startswith("--"):
        return None
    name, equals, _ = word.text.partition("=")
    if not equals or "$" in name or "`" in name:
        return None
    option = resolve_option(name, APPEND_OPTIONS)
    if option is None or not APPEND_OPTIONS[option[0]]:
        return None
    return option[0], ""


def judge_append(command, args, from_xargs, leading_opaque=False):
    """The reasons to refuse one `append` with these argument words.

    An unread word in an option's place, or an unquoted expansion anywhere (it may split
    into `--type gate-decision`, and argparse keeps the last `--type`), is opaque at its
    position. Only a literal `--type` naming another event after the last of them lets the
    append through unread. A literal `--type reply-witnessed` there is refused whatever
    its payload, so a `--type` the hook cannot read is refused too: it may be a witness.
    """
    values = {}
    batch = False
    opaque_at = 0 if leading_opaque else -1
    other_type_at = -1
    witness_at = -1
    opaque_type_at = -1
    i = 0
    while i < len(args):
        word = args[i]
        i += 1
        if not word.literal:
            option = inline_option(word)
            if option is None:
                opaque_at = i
                continue
            name, _ = option
            value = Word("", False, False)
            values[name] = value
            if name == "--type":
                other_type_at = witness_at = -1
                opaque_type_at = i
            continue
        if not word.text.startswith("--"):
            continue
        option = resolve_option(word.text, APPEND_OPTIONS)
        if option is None:
            continue
        name, inline = option
        if not APPEND_OPTIONS[name]:
            if name == "--batch":
                batch = True
            continue
        if inline is not None:
            value = Word(inline, word.literal, False)
        elif i < len(args):
            value = args[i]
            i += 1
            if value.split:
                opaque_at = i
        else:
            value = Word("", False, False)  # no value here: xargs may supply it
        values[name] = value
        if name == "--type":
            folded = _folded(value.text) if value.literal else None
            other_type_at = (
                i if folded not in (None, GATE_DECISION, REPLY_WITNESSED) else -1
            )
            witness_at = i if folded == REPLY_WITNESSED else -1
            opaque_type_at = i if folded is None else -1

    if other_type_at > opaque_at and not batch and not from_xargs:
        return []  # a literal --type names another event, after anything opaque
    if witness_at > opaque_at and not batch and not from_xargs:
        return [REASON_WITNESS]  # only the recorder hook writes a witness
    if from_xargs:
        return [REASON_OPAQUE]
    if opaque_at >= 0:
        return [REASON_SPLIT]
    if opaque_type_at >= 0 and not batch:
        return [REASON_OPAQUE]  # an unread --type: a gate-decision or a witness

    actor_word = values.get("--actor")
    if actor_word is None:
        actor = None
    elif actor_word.literal:
        actor = actor_word.text
    else:
        actor = actor_word

    if batch:
        texts = stdin_texts(command)
        if texts is None:
            return [REASON_OPAQUE]
        return judge_jsonl(texts, actor)

    data_word = values.get("--data")
    if data_word is None:
        return []
    if not data_word.literal:
        return [REASON_OPAQUE]
    try:
        data = json.loads(data_word.text)
    except (ValueError, RecursionError):
        return []
    return [judge_event(data, actor)]


def judge_commands(commands, depth, recorder_named=False):
    """The reasons to refuse these commands. `recorder_named` says the line names the
    recorder script, so a Python whose script word the hook cannot read may run it."""
    reasons = []
    for command in commands:
        at = command_name(command)
        from_xargs = (
            at is not None
            and command.words[at].literal
            and basename(command.words[at].text) == "xargs"
        )
        appends = append_args(command)
        for args, leading_opaque in appends:
            reasons.extend(judge_append(command, args, from_xargs, leading_opaque))
        if runs_import(command):
            reasons.append(REASON_IMPORT)
        if runs_recorder(command, recorder_named):
            reasons.append(REASON_RECORDER)
        reasons.extend(
            judge_commands(relexed(command, depth), depth + 1, recorder_named)
        )
        if not appends and not text_only(command, at):
            # A Python's arguments are Python, not a shell line (`python3 -c '...'` is out
            # of scope, ADR 0015), so they are not lexed again as commands.
            program = basename(command.words[at].text) if at is not None else ""
            if not _is_python(program):
                reasons.extend(
                    judge_commands(wrapped(command, depth), depth + 1, recorder_named)
                )
            reasons.extend(stdin_events(command, depth))
    return reasons


def stdin_events(command, depth):
    """Forged events in a literal stdin that names a journal append, lexed as a script.

    This catches a shell behind a wrapper the table does not know. Stdin is often not a
    script at all (a Python program, a document), so only an event found there refuses;
    an unread payload in it is left alone.
    """
    reasons = []
    for text in stdin_texts(command) or []:
        if not names_a_net_target(text):
            continue
        try:
            found = judge_commands(lex(text, depth + 1), depth + 1, RECORDER in text)
        except Opaque:
            continue
        reasons.extend(r for r in found if r in EVENT_REASONS)
    return reasons


def names_a_write(text):
    """True when the text names one of the journal's two writing subcommands."""
    return "append" in text or "import" in text


def names_a_net_target(text):
    """True when the text may run a journal write or the recorder script: the forgery
    net's fast path."""
    return ("journal.py" in text and names_a_write(text)) or RECORDER in text


def _is_python(program):
    """`python`, `python3`, `python3.12`."""
    rest = program[len("python"):] if program.startswith("python") else None
    return rest is not None and all(c.isdigit() or c == "." for c in rest)


# Modules that run the path after them as `__main__`.
SCRIPT_RUNNERS = ("cProfile", "profile", "trace", "pdb")
# Python options that take the next word as their value.
PYTHON_VALUE_OPTIONS = ("-W", "-X", "--check-hash-based-pycs")


def runs_recorder(command, recorder_named):
    """True when a simple command runs the recorder script (ADR 0023 §21).

    The script runs as the program (`./hooks/reply.py`) or as a Python's script word
    (`python3 -u hooks/reply.py`). A script word the hook cannot read (`"$R"`,
    `"${CLAUDE_PLUGIN_ROOT}/hooks/reply.py"`) counts when the line names the script.
    `python3 -c` runs no script word, and neither does `python3 -m` with most modules,
    so `python3 -m py_compile hooks/reply.py` passes. A runner module (`cProfile`,
    `profile`, `trace`, `pdb`) runs the path after it as `__main__`, so any later word
    that names the script counts.
    """
    at = command_name(command)
    if at is None:
        return False
    word = command.words[at]
    if not word.literal:
        return False
    program = basename(word.text)
    if program == RECORDER:
        return True
    if not _is_python(program):
        return False
    words = command.words
    i = at + 1
    while i < len(words):
        candidate = words[i]
        if not candidate.literal:
            return recorder_named or RECORDER in candidate.text
        text = candidate.text
        if text.startswith("-") and not text.startswith("--") and len(text) > 1:
            # A short-option cluster: `-c`/`-m` end it and take the rest of the word, or
            # the next word (`-mcProfile`, `-um cProfile`, `-Im pdb`).
            flags = text[1:]
            cut = next((k for k, c in enumerate(flags) if c in "cmWX"), None)
            if cut is not None and flags[cut] == "c":
                return False
            if cut is not None and flags[cut] == "m":
                rest = flags[cut + 1:]
                after = i + 1 if rest else i + 2
                module = rest if rest else (
                    words[i + 1].text if i + 1 < len(words) and words[i + 1].literal
                    else None
                )
                if module not in SCRIPT_RUNNERS:
                    return False
                return any(
                    (w.literal and basename(w.text) == RECORDER)
                    or (not w.literal and (recorder_named or RECORDER in w.text))
                    for w in words[after:]
                )
            if cut is not None:  # `-W arg`, `-X opt`: the value follows
                i += 1 if flags[cut + 1:] else 2
                continue
        if text in PYTHON_VALUE_OPTIONS:
            i += 2
            continue
        if text.startswith("-") and text != "-":
            i += 1
            continue
        return basename(text) == RECORDER
    return False


def runs_import(command):
    """True when a simple command runs `journal.py import` (ADR 0023 §20).

    The words are walked as `append_args` walks them. The script is a literal word whose
    basename is `journal.py`, or a word the hook cannot read (`"$J"`,
    `"${CLAUDE_PLUGIN_ROOT}/scripts/journal.py"`). Top-level options and their values
    are skipped, `--db="$DB"` included, and the first other literal word is the
    subcommand.
    """
    words = command.words
    for at, word in enumerate(words):
        if word.literal and basename(word.text) != "journal.py":
            continue
        i = at + 1
        while i < len(words):
            candidate = words[i]
            if not candidate.literal:
                if top_option_with_value(candidate):
                    i += 1
                    continue
                break
            text = candidate.text
            if not text.startswith("-"):
                if text == "import":
                    return True
                break
            option = resolve_option(text, TOP_OPTIONS)
            i += 1
            if option and TOP_OPTIONS[option[0]] and option[1] is None:
                i += 1
    return False


def text_only(command, at):
    """True for a command that only prints or stores its arguments (a commit message)."""
    if at is None or not command.words[at].literal:
        return False
    return basename(command.words[at].text) in TEXT_ONLY


def wrapped(command, depth):
    """Commands in a literal word that names a journal append (`ssh host '...'`).

    A wrapper with arguments of its own (`timeout`, `nice -n`, `sudo -u`, `ssh host`,
    `xargs sh -c`) hides the shell from `relexed`, so every literal word that holds both
    `journal.py` and `append` is lexed again as a command line.
    """
    found = []
    for word in command.words:
        if not (word.literal and names_a_net_target(word.text)):
            continue
        # A word with no break in it lexes back to itself: a path, a test id, no command.
        if any(c in word.text for c in _COMMAND_BREAKS):
            found.extend(lex(word.text, depth + 1))
    return found


# `env` options that take the next word as their value.
ENV_VALUE_OPTIONS = ("-u", "--unset", "-C", "--chdir", "-S", "--split-string")


def overrides_session(commands, depth=0):
    """True when a command of the line sets or clears the session id (ADR 0023 §8).

    A word that is the variable's name or `NAME=value`: an assignment, `env NAME=value`,
    `env -u NAME`, `export`, `unset`, `declare`, `read NAME`, `printf -v NAME`; and
    `env -i`. Nested scripts (`sh -c`, `eval`, a shell's stdin, a quoted command line)
    count too. A word that only mentions the name inside other text (a note, a commit
    message) does not.
    """
    for command in commands:
        at = command_name(command)
        program = basename(command.words[at].text) if at is not None else ""
        if text_only(command, at) and program != "printf":
            words = []  # a search or a print sets nothing (`grep NAME f`)
        elif program == "printf":
            words = [w for i, w in enumerate(command.words)
                     if i and command.words[i - 1].text == "-v"]
        else:
            words = command.words
        in_env = False
        value_next = False
        for word in words:
            text = word.text
            if text in (SESSION_ENV, "-u" + SESSION_ENV, "--unset=" + SESSION_ENV) \
                    or text.startswith(SESSION_ENV + "="):
                return True
            if value_next:
                value_next = False  # the value of `env -u NAME`, `-C DIR`, `-S STR`
                continue
            if word.literal and basename(text) == "env":
                in_env = True
                continue
            if not in_env:
                continue
            if word.literal and text.startswith("-"):
                if text in ("-", "--ignore-environment") or (
                    not text.startswith("--") and "i" in text[1:]
                ):
                    return True  # `env -i`, `env -iv`, `env -v -i`: a cleared environment
                value_next = text in ENV_VALUE_OPTIONS
                continue
            if not (word.literal and "=" in text):
                in_env = False  # the command env runs
        try:
            nested = relexed(command, depth) + wrapped(command, depth)
        except Opaque:
            continue
        if overrides_session(nested, depth + 1):
            return True
    return False


def inspect(command_line):
    """The reason to refuse this command line, or None to let it run."""
    try:
        commands = lex(command_line)
        reasons = judge_commands(commands, 0, RECORDER in command_line)
        if overrides_session(commands):
            reasons.append(REASON_SESSION)
    except Opaque:
        return REASON_OPAQUE
    for reason in REASON_PRIORITY:
        if reason in reasons:
            return reason
    return None


# -- the command gate --------------------------------------------------------------------

# git's global options that take the next word as their value (`--opt=value` is one word).
GIT_VALUE_OPTIONS = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env",
    "--super-prefix", "--shallow-file", "--attr-source",
}
# git's global options that print or open help and exit: no subcommand runs after them.
GIT_EXIT_OPTIONS = {
    "-h", "--help", "-v", "--version", "--exec-path", "--html-path", "--man-path",
    "--info-path",
}
# `git subtree` options that take the next word as their value.
SUBTREE_VALUE_OPTIONS = {
    "-P", "--prefix", "-m", "--message", "--onto", "-b", "--branch", "--annotate",
}
# `gh` and `glab` options before the noun or the verb that take a value.
FORGE_VALUE_OPTIONS = {"-R", "--repo"}
FORGE_NOUNS = {"gh": "pr", "glab": "mr"}
FORGE_VERBS = ("create", "new")


def _option_with_unread_value(word):
    """True for an unsplit `--opt="$X"`: a literal option name with a value unread."""
    if word.split or not word.text.startswith("-"):
        return False
    name, equals, _ = word.text.partition("=")
    return bool(equals) and "$" not in name and "`" not in name


def _skip_options(args, i, value_options):
    """The index of the first word from `i` that is no option, or None when a word the
    hook cannot read stands there (it may be the option or the operand)."""
    while i < len(args):
        word = args[i]
        if not word.literal:
            if _option_with_unread_value(word):
                i += 1
                continue
            return None
        if not word.text.startswith("-"):
            return i
        i += 2 if word.text in value_options else 1
    return i


def _path_of(word):
    """The path a literal word names, with an unquoted leading `~` expanded as the shell
    expands it."""
    import os

    if not word.quoted and word.text.startswith("~"):
        return os.path.expanduser(word.text)
    return word.text


def _git_gate(args):
    """(gate, directory) for `git <global options> commit|push|subtree push`, or None.

    git's global options are walked as git reads them: a value option takes the next
    word, `--opt=value` is one word, a help or version option ends git before any
    subcommand. Each `-C` enters its path relative to the one before, and an absolute
    path starts again. A `-C` the hook cannot read leaves the directory unknown (None)
    until an absolute `-C` after it.
    """
    import os

    directory = None
    known = True
    i = 0
    while i < len(args):
        word = args[i]
        if not word.literal:
            if _option_with_unread_value(word):
                i += 1
                continue
            return None  # the subcommand, or options that may split, unread
        text = word.text
        if not text.startswith("-"):
            break
        i += 1
        if text in GIT_EXIT_OPTIONS or text.startswith("--list-cmds"):
            return None
        if text.startswith(("--git-dir", "--work-tree")):
            known = False  # git leaves the `-C` directory: read the cwd
            directory = None
        if text not in GIT_VALUE_OPTIONS:
            continue
        value = args[i] if i < len(args) else None
        i += 1
        if text != "-C" or value is None:
            continue
        if not value.literal:
            directory, known = None, False
        elif value.text:  # git ignores an empty `-C ""`
            path = _path_of(value)
            if os.path.isabs(path):
                directory, known = path, True
            elif known:
                directory = os.path.join(directory, path) if directory else path
    if i >= len(args) or not args[i].literal:
        return None
    subcommand = args[i].text
    if subcommand == "subtree":
        at = _skip_options(args, i + 1, SUBTREE_VALUE_OPTIONS)
        if at is None or at >= len(args) or args[at].text != "push":
            return None
        subcommand = "push"
    gate = {"commit": COMMIT_GATE, "push": PUBLISH_GATE}.get(subcommand)
    if gate is None:
        return None
    return gate, (directory if known else UNKNOWN_DIR)


def _forge_gate(program, args):
    """("publish", None) for `gh pr create|new` and `glab mr create|new`, or None."""
    noun = _skip_options(args, 0, FORGE_VALUE_OPTIONS)
    if noun is None or noun >= len(args) or args[noun].text != FORGE_NOUNS[program]:
        return None
    verb = _skip_options(args, noun + 1, FORGE_VALUE_OPTIONS)
    if verb is None or verb >= len(args) or args[verb].text not in FORGE_VERBS:
        return None
    return PUBLISH_GATE, None


# Variables that move git away from the directory its `-C` or cwd names.
GIT_DIR_VARIABLES = ("GIT_DIR=", "GIT_WORK_TREE=")


def _assigns(text):
    """True for `NAME=...`, the head of an assignment word."""
    head, equals, _ = text.partition("=")
    return bool(equals) and bool(head) and not head[0].isdigit() \
        and all(c in _NAME_CHARS for c in head)


def _gated_command(command):
    """(gate, directory) for one simple command, wrappers skipped, or None.

    An assignment before the command is skipped whether or not the hook can read its
    value (`X="$Y" git commit`): bash does not split an assignment. `GIT_DIR=` or
    `GIT_WORK_TREE=` there leaves the directory unknown, read as the cwd.
    """
    words = command.words
    start = 0
    while True:
        rest = Command()
        rest.words = words[start:]
        at = command_name(rest)
        if at is None:
            return None
        word = rest.words[at]
        if not word.literal and _assigns(word.text):
            start += at + 1
            continue
        break
    if not word.literal:
        return None
    program = basename(word.text)
    args = rest.words[at + 1:]
    if program == "git":
        gated = _git_gate(args)
    elif program in FORGE_NOUNS:
        gated = _forge_gate(program, args)
    else:
        return None
    if gated is not None and any(
        w.text.startswith(GIT_DIR_VARIABLES) for w in words[:start + at]
    ):
        gated = (gated[0], UNKNOWN_DIR)
    return gated


# A directory the hook cannot read: a `-C` or a `cd` from a variable. The caller reads it
# as the command's cwd, as it reads no directory at all.
UNKNOWN_DIR = object()
CD_COMMANDS = ("cd", "pushd")


def _cd_target(command):
    """The directory a `cd` or `pushd` enters, UNKNOWN_DIR, or None for any other command.

    `cd` with no operand, `cd -` and a path from a variable are unknown.
    """
    at = command_name(command)
    if at is None or not command.words[at].literal:
        return None
    if basename(command.words[at].text) not in CD_COMMANDS:
        return None
    operands = command.words[at + 1:]
    while operands and operands[0].literal and len(operands[0].text) > 1 \
            and operands[0].text.startswith("-"):
        operands = operands[1:]
    if not operands or not operands[0].literal or operands[0].text == "-":
        return UNKNOWN_DIR
    return _path_of(operands[0])


def _enter(base, path):
    """`path` entered from `base`: None is the cwd, UNKNOWN_DIR stays unknown."""
    import os

    if path is UNKNOWN_DIR:
        return UNKNOWN_DIR
    if os.path.isabs(path):
        return path
    if base is UNKNOWN_DIR:
        return UNKNOWN_DIR
    return os.path.join(base, path) if base else path


def _gated_in(commands, depth, found, cwd=None, follow_cd=True, cds=None):
    """Walk the commands in the lexer's order. A literal `cd` moves the directory the
    later commands act on (ADR 0023 §14: the branch of the command's directory); a
    nested script starts from the directory its shell starts in, and its own `cd` does
    not move the outer line."""
    for command in commands:
        target = _cd_target(command)
        if target is not None:
            if cds is not None:
                cds.append(target)
            if follow_cd:
                cwd = _enter(cwd, target)
            continue
        gated = _gated_command(command)
        if gated is not None:
            gate, directory = gated
            directory = cwd if directory is None else _enter(cwd, directory)
            pair = (gate, None if directory is UNKNOWN_DIR else directory)
            if pair not in found:
                found.append(pair)
        try:
            hidden = relexed(command, depth)
        except Opaque:
            continue  # a script the hook cannot see: that script only, not the line
        _gated_in(hidden, depth + 1, found, cwd, follow_cd, cds)


def gated_commands(command_line):
    """Every command of the line the command gate holds, as (gate, directory) pairs.

    Each distinct pair comes once, in the order the lexer finds it: the gate asks the
    journal once per pair. The gate is `commit` for `git commit`, and `publish` for
    `git push`, `git subtree push`, `gh pr create|new` and `glab mr create|new`. The
    directory is git's literal `-C` path, or None for the command's own cwd. Wrappers
    and assignments are skipped (`timeout 5 git commit`), and a literal line given to
    `sh -c`, `eval` or a shell's stdin is read too. Only a command is matched, never a
    word: `echo git commit`, a commit message and `git log --grep commit` hold nothing.
    A literal `cd` or `pushd` earlier in the line moves the directory, and git's `-C`
    enters from there. The lexer cannot tell a `cd` inside `( )` or `$( )` from one that
    moves the line, so a line with a `cd` also gives the pairs read from the cwd, and
    the gate holds when either holds. A `cd` or `-C` the hook cannot read, `--git-dir`,
    `--work-tree`, `GIT_DIR=` and a wrapper's own `-C` read as the command's cwd.

    Pure: it reads no file and runs nothing. A line the lexer refuses, or any error,
    gives [], and the caller's failure policy passes the command (ADR 0023 §15).
    """
    try:
        commands = lex(command_line)
        found = []
        cds = []
        _gated_in(commands, 0, found, cds=cds)
        if cds:
            # The lexer cannot tell a `cd` inside `( )` or `$( )` from one that moves
            # the line (security review, T021), so the cwd's reading is asked too.
            _gated_in(commands, 0, found, follow_cd=False)
        return found
    except Exception:  # noqa: BLE001 — the command gate passes what it cannot read
        return []


# -- the hook ----------------------------------------------------------------------------


def deny(reason):
    deny_with(MESSAGES[reason] + " " + TAIL + script_line())


def script_line():
    """The sentence that names this plugin's journal script, absolute and quoted (#55).

    A path computation only: no file is read and no process runs. Empty when the path
    does not print on one line.
    """
    import os
    from shlex import quote

    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "journal.py",
    )
    line = f" This plugin's journal script is `{quote(script)}`."
    return line if line.isprintable() else ""


# The command gate's second fast path: without one of these words no command of the line
# can be gated, and the hook reads no file.
GATED_COMMAND_HINTS = ("commit", "push", "create", "new")
# `git` gets 2 seconds per branch read (`_common.GIT_TIMEOUT_SECONDS`), `authorize` 5.
AUTHORIZE_SECONDS = 5


def command_gate(payload, command):
    """The refusal for a gated command the journal holds, or None to let it run.

    ADR 0023 §14-§15. The project comes from the payload's `cwd`; no sidecar, or
    `enforce.command_gate` false, passes. Each directory the line acts on is asked once,
    for its strongest gate: a publish go covers a commit, so a line that commits and
    pushes in one directory asks for the publish gate. A directory with no branch, a
    journal that fails or times out, and any answer but `hold` pass.
    """
    import os

    gated = gated_commands(command)
    if not gated:
        return None
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import current_branch, resolve_project, run_journal

    project = resolve_project(payload)
    if project is None or not project.enforces("command_gate"):
        return None
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    strongest = {}
    for gate, directory in gated:
        if directory and "\x00" in directory:
            directory = None  # no path at all: bash drops it, so git acts on the cwd
        path = os.path.normpath(os.path.join(cwd, directory) if directory else cwd)
        if strongest.get(path) != PUBLISH_GATE:
            strongest[path] = gate
    subagent = ["--subagent"] if "agent_id" in payload else []
    for path, gate in strongest.items():
        branch = current_branch(path)
        if not branch:
            continue
        result = run_journal(
            project,
            ["authorize", "--gate", gate, "--branch", branch, "--json", *subagent],
            timeout=AUTHORIZE_SECONDS,
        )
        if result is None or result.returncode != 0:
            continue
        try:
            answer = json.loads(result.stdout)
        except ValueError:
            continue
        if isinstance(answer, dict) and answer.get("verdict") == "hold":
            message = answer.get("message")
            if isinstance(message, str) and message:
                return message
            request = answer.get("request_command")
            request = (f" with `{request}`" if isinstance(request, str) and request
                       and request.isprintable() else "")
            return (f"shipgate held this {gate}: the stream of branch {branch} holds "
                    f"no go from the user. Record a go-requested{request} and ask the "
                    "gate question, or let the user type the gate word.")
    return None


def deny_with(message):
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import emit

    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    })


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except (OSError, ValueError):
        return
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return
    if names_a_net_target(command):
        try:
            reason = inspect(command)
        except Exception:  # noqa: BLE001 — the failure policy below decides
            folded = command.casefold()
            named = all(word in folded for word in ("journal.py", "append", "publish")) \
                or all(word in folded for word in ("journal.py", "import")) \
                or RECORDER in folded
            reason = REASON_CRASH if named else None
        if reason is not None:
            deny(reason)
            return
    if not any(word in command for word in GATED_COMMAND_HINTS):
        return
    try:
        message = command_gate(payload, command)
    except Exception:  # noqa: BLE001 — a command gate that fails passes (ADR 0023 §15)
        message = None
    if message:
        deny_with(message)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 — a hook never surfaces a traceback
        sys.exit(0)
