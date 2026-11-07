---
type: adr
title: "0015. The user approves a publish outside the model's tools, and a marker says so"
created: 2026-11-06
updated: 2026-11-06
tags:
  - adr
  - shipgate
status: accepted
date: 2026-11-06
issue: "#1"
related:
  - "0009-the-journal-computes-the-hud-position.md"
  - "../../../shipgate-hud/docs/adr/0005-the-publish-gate-checks-the-published-branch.md"
  - "../../../shipgate-hud/docs/adr/0010-the-publish-dialog-records-the-approval.md"
---

# 0015. The user approves a publish outside the model's tools, and a marker says so

> A user publish decision authorizes only with the marker `source: dialog` or
> `source: shell`. A PreToolUse hook refuses a model's Bash call that writes the marker, or
> that records a publish decision as the user's. The HUD's publish dialog and the user's own
> `!` command write the marker; neither passes through PreToolUse.

## Context

`journal.py append --actor user` takes the actor from the flag, and `raised_by: user` is
free text. So the model can append a publish `gate-decision` "by the user", which satisfies
`mr-opened` and the HUD's publish gate (#1). No local check is a hard boundary: the model has
a shell and can write the SQLite file. The goal is narrower: no normal tool path forges the
approval, and the READMEs say exactly that.

## Decision

1. **The marker.** `gate-decision` takes an optional `source`, one of `dialog` (the HUD's
   publish dialog) or `shell` (the user's own `!` command). `vocab --shape gate-decision`
   prints the enum.
2. **The rule.** A `gate-decision` authorizes a publish only with `gate: publish`,
   `raised_by: user`, `decision: publish` (trimmed, any case), a `source` marker and an
   actor of role `user`. `publish_authorization` is the one helper; `mr-opened`,
   `status --json` and `position --json` read it, and the HUD reads `publish` from them. So
   there is no second copy of the rule to change.
3. **Old rows.** An unmarked user publish decision recorded before 0.23.0 no longer
   authorizes. The gate asks again. Both changelogs say so.
4. **The hook.** `hooks/pre_tool_use.py`, PreToolUse, matcher `Bash`. It refuses a command
   that appends a `gate-decision` that carries `source` (any gate), or a `gate-decision` at
   the publish gate (`gate` or its alias `kind`, trimmed, any case) that names the user:
   `--actor user`, `user@…`, a JSONL `actor` of that role, or `raised_by: user`. A
   decision at another gate stays allowed with every actor.
5. **What the hook reads.** It lexes the shell line itself: quotes, `\` escapes, `;`, `&&`,
   `||`, `|`, `&`, newlines, heredoc bodies (quoted and unquoted delimiters, `<<-`),
   here-strings. A simple command is a journal append when one of its words (the first
   included, as the script has a shebang) has the basename `journal.py` or is not literal,
   and the subcommand after it is `append`. It reads `--type`, `--data`, `--actor` and
   `--batch` in the `--opt value` and `--opt=value` forms and as unique abbreviations, as
   argparse does. Stdin comes from a heredoc, a here-string or a pipe from `echo`, `printf`
   or `cat`. These are lexed again:
   - a literal command line given to `sh -c`, `bash -c`, `zsh -c` or `eval`, and a `$(…)`
     body;
   - the literal script a shell reads on stdin. A table of wrappers (`timeout`, `nice`,
     `sudo`, `env`, `stdbuf`, `nohup`, `time` and others) and the options that take a value
     finds the shell behind `timeout 60` or `sudo -u bob`;
   - a literal word that holds `journal.py`, `append` and a word break, whatever program
     takes it (`ssh host '…'`);
   - the literal stdin of a program the hook does not know, when it holds `journal.py` and
     `append`. There only a marker or a user claim refuses, since such a stdin is often a
     program or a document.

   The arguments and stdin of a journal append itself and of a program that only prints or
   stores text (`git`, `gh`, `glab`, `echo`, `printf`, `grep`, `egrep`, `fgrep`, `rg`, `jq`,
   `cat`, `head`, `tail`, `tee`) are not lexed again, behind a wrapper too.
6. **Fail closed on what it cannot read.** When the append could be a `gate-decision`, the
   hook refuses a payload it cannot see in full: a `--data` or a stdin that comes from a
   variable, a command substitution, a redirected file, or another command's output. That
   message asks for a literal payload. It also refuses an unquoted expansion anywhere in the
   append's words, as it can split into more options (`--stream $S`), and a subcommand that
   comes from a variable (`journal.py $SUB`). That message asks to quote the expansion and to
   write the subcommand literally. A double-quoted `"$B"` is one word, and so is
   `--db="$DB"`. An append whose literal `--type` names another type, after any such word,
   passes. A shell whose script comes from a stdin the hook cannot read (a group, a
   subshell, a file) is refused when the line names `journal.py` and `append`.
7. **The no-op path.** A tool other than Bash, or a command without the words `journal.py`
   and `append`, prints nothing and exits 0. The hook reads no file on that path. A crash
   exits 0, except on a command that names `journal.py`, `append` and `publish`: that one
   is refused.
8. **The refusal** names what it refused and sends the model to the user: approve in the
   HUD's publish dialog, or run the append with `!` and `"source": "shell"`.

## Alternatives considered

- **A journal column only a dialog can set.** The model can write the SQLite file, and a
  column set by a CLI flag is as forgeable as a payload key. It costs a migration for the
  same strength.
- **Refuse `--actor user` on every event.** User decisions the model records from chat
  (scope, clarify, design) are normal; only the publish gate authorizes anything.
- **A journal-existence probe in the hook.** Without a journal the forged append fails
  anyway, and the probe adds file reads to every Bash call in every project.
- **Fail open on an opaque payload.** A variable or `$(cat file)` would then be the
  one-line way around the hook.

## Consequences

- The `feature` and `review` skills, journal.py's `mr-opened` message and the HUD's deny
  text tell the model to ask the user, never to record the approval.
- The boundary is a net against a flow forging approval through its tools. It is no
  defence against deliberate circumvention: a direct SQLite write, `python3 -c`, a copied
  or renamed script, or a payload built by an indirection the lexer does not follow. Both
  READMEs say so.
- The hook runs on every Bash call in every project with shipgate installed. Its fast path
  is one substring test after the JSON decode.
- Known limits, accepted:
  - A program outside the text-only list that takes a text naming an append and a `$`
    (`sed -i`, `claude -p`) is refused. Write the text without the `$`, or run it in two
    steps.
  - The text-only list trusts `git` whole. A git feature that runs a command (an alias that
    starts with `!`, `rebase -x`) is not lexed; using it to write the journal is deliberate.
  - An unquoted glob character among an append's words is refused as unreadable, since a
    glob can expand to more words. Quote it.
  - A program outside the text-only list whose literal stdin holds a forged append is
    refused, even when it only reads the text (`python3 - <<'EOF'`, `wc -l <<'EOF'`).
  - A wrapper missing from the table, before a shell whose stdin script takes its payload
    from a variable, passes. So does a combined short-flag cluster that ends in a
    value-taking option (`sudo -Hu bob`): the hook then names the wrong program, and can
    refuse a text-only command behind it.
  - A shell that reads its script through process substitution (`bash <(…)`,
    `tee >(bash)`) is not lexed. Nor is a `-c` or `eval` text built by
    `"$(cat <<'EOF' … EOF)"`, or a group piped into `bash -s` with positional arguments.
  - A subcommand from a variable is refused only when the line names `append` somewhere;
    the fast path passes a line with no literal `append`.
