#!/usr/bin/env python3
"""PreToolUse hook — refuse a Bash call that records the user's publish approval.

ADR 0015.

Only the user approves a publish. The HUD's publish dialog and the user's own `!` command
record that approval, and neither passes through PreToolUse. So a model's Bash call that
appends either of these to the journal is refused:

* a `gate-decision` that carries `source`, the marker of the user's own approval, at any
  gate;
* a `gate-decision` at the publish gate (`gate`, or its alias `kind`; trimmed, any case)
  that names the user: an actor of role `user` (`--actor user`, `user@...`, a JSONL
  `actor`) or `raised_by: user`.

A decision at another gate stays allowed with every actor, and so does every other event.

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

What the hook cannot read, it refuses when the append could be a `gate-decision`: a
payload from a variable, a command substitution, a file, another command's output, a
`--batch` with no visible stdin, a subcommand from a variable, an unquoted expansion
among the arguments (it may split into a later `--type`), or a shell that reads a script
on a stdin the hook cannot see. An append whose literal `--type` names another event type
passes whatever its payload.

This is a net, not a boundary. The model has a shell and can still write the approval by
other means, and these are out of scope:

* a direct SQLite write, `python3 -c`, or a copied or renamed script;
* a shell function, an alias, or a sourced file (`. f`, `source f`) that runs the append;
* a shell given a command line from a variable (`bash -c "$X"`, `eval "$X"`) or a script
  file;
* a wrapper the table below does not know, whose stdin script takes its payload from a
  variable (only an event found in such a stdin refuses);
* any other indirection the lexer does not follow.

This hook fires on every Bash call in every project, so the fast path comes first: decode
stdin, and exit 0 with no output and no file read unless the command contains both
`journal.py` and `append`. `_common` is imported only to print a refusal. A crash exits 0
silently, except on a command that names `journal.py`, `append` and `publish`: that one
is refused.
"""

from __future__ import annotations

import json
import sys

GATE_DECISION = "gate-decision"
PUBLISH_GATE = "publish"
USER_ROLE = "user"

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
}
# Commands that print, search or store their arguments and never run them: a literal word
# of theirs that names a journal append is text (a commit message), not a command line.
TEXT_ONLY = {
    "git", "gh", "glab", "echo", "printf", "grep", "egrep", "fgrep", "rg", "jq", "cat",
    "head", "tail", "tee",
}

REASON_MARKER = "marker"
REASON_USER = "user"
REASON_OPAQUE = "opaque"
REASON_SPLIT = "split"
REASON_CRASH = "crash"
REASON_PRIORITY = (REASON_MARKER, REASON_USER, REASON_OPAQUE, REASON_SPLIT)

TAIL = (
    "Only the user approves a publish. Ask them to choose \"Approve publishing\" in the "
    "shipgate-hud publish dialog, or to run the append themselves with `!` and "
    "`\"source\": \"shell\"`. Never record it on their behalf."
)
MESSAGES = {
    REASON_MARKER: (
        "shipgate refused this command: it appends a gate-decision that carries "
        "`source`, the marker of the user's own approval."
    ),
    REASON_USER: (
        "shipgate refused this command: it records a publish gate-decision as the "
        "user's (an actor of role `user`, or `raised_by: user`)."
    ),
    REASON_OPAQUE: (
        "shipgate refused this command: it appends to the journal with a payload the "
        "hook cannot read (a variable, a command substitution, a file, another "
        "command's output, or no visible stdin for --batch). Write the payload "
        "literally: `--data '{...}'` or a quoted heredoc (<<'EOF')."
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


def judge_event(data, actor):
    """The reason to refuse a gate-decision with this data and actor, or None.

    `actor` is a string, None (no actor: journal.py's default), or a non-literal Word.
    """
    if not isinstance(data, dict):
        return None
    if "source" in data:
        return REASON_MARKER
    gates = [_folded(data.get(key)) for key in ("gate", "kind") if key in data]
    if PUBLISH_GATE not in gates:
        return None
    if _folded(data.get("raised_by")) == USER_ROLE:
        return REASON_USER
    if isinstance(actor, Word):
        return REASON_OPAQUE
    if isinstance(actor, str) and actor.partition("@")[0].strip().casefold() == USER_ROLE:
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
            if _folded(record.get("type")) != GATE_DECISION:
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
    append through unread.
    """
    values = {}
    batch = False
    opaque_at = 0 if leading_opaque else -1
    other_type_at = -1
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
                other_type_at = -1
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
            literal_other = value.literal and _folded(value.text) != GATE_DECISION
            other_type_at = i if literal_other else -1

    if other_type_at > opaque_at and not batch and not from_xargs:
        return []  # a literal --type names another event, after anything opaque
    if from_xargs:
        return [REASON_OPAQUE]
    if opaque_at >= 0:
        return [REASON_SPLIT]

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


def judge_commands(commands, depth):
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
        reasons.extend(judge_commands(relexed(command, depth), depth + 1))
        if not appends and not text_only(command, at):
            reasons.extend(judge_commands(wrapped(command, depth), depth + 1))
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
        if "journal.py" not in text or "append" not in text:
            continue
        try:
            found = judge_commands(lex(text, depth + 1), depth + 1)
        except Opaque:
            continue
        reasons.extend(r for r in found if r in (REASON_MARKER, REASON_USER))
    return reasons


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
        if not (word.literal and "journal.py" in word.text and "append" in word.text):
            continue
        # A word with no break in it lexes back to itself: a path, a test id, no command.
        if any(c in word.text for c in _COMMAND_BREAKS):
            found.extend(lex(word.text, depth + 1))
    return found


def inspect(command_line):
    """The reason to refuse this command line, or None to let it run."""
    try:
        reasons = judge_commands(lex(command_line), 0)
    except Opaque:
        return REASON_OPAQUE
    for reason in REASON_PRIORITY:
        if reason in reasons:
            return reason
    return None


# -- the hook ----------------------------------------------------------------------------


def deny(reason):
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import emit

    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": MESSAGES[reason] + " " + TAIL,
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
    if "journal.py" not in command or "append" not in command:
        return
    try:
        reason = inspect(command)
    except Exception:  # noqa: BLE001 — the failure policy below decides
        folded = command.casefold()
        named = all(word in folded for word in ("journal.py", "append", "publish"))
        reason = REASON_CRASH if named else None
    if reason is not None:
        deny(reason)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 — a hook never surfaces a traceback
        sys.exit(0)
