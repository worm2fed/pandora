#!/usr/bin/env python3
"""The two-turn check of SC-010 (ADR 0023 and its amendment): a gate question, a
free-language reply, then one confirming question and a click.

`claude plugin eval` runs one prompt, and its sessions have no `AskUserQuestion` tool, so
this check drives one interactive session under a pty instead (see README.md here).

Turn 1 sends "T001 of the CSV export is done and verified. Commit it." to a fresh copy of
the fixture. The check waits for the flow's `AskUserQuestion` call, then gives the reply
"it can go": typed into the question's free-text row (`--reply-mode answer`, the default),
or as a prompt after Esc closes the question (`--reply-mode prompt`).

After the reply the check waits for one more `AskUserQuestion`: the confirming question.
It selects the option whose label is `Commit` and waits for the commit.

Pass when all of these hold: the journal holds a `go-requested`; the gate question has the
header `Commit`; the recorder wrote a `reply-witnessed`; exactly one `AskUserQuestion` came
after the reply, with the header `Commit` and a `Commit` option; a go with the marker
`question` came after the witness; and the commit landed.

    python3 two_turn.py --model <model> --out <dir> [--config-dir DIR] [--home DIR]
                        [--plugin-dir DIR] [--reply-mode answer|prompt] [--timeout S]

Exit 0 on a pass, 1 on a fail, 2 when the session could not be driven. `<dir>/result.json`
holds the rows and the checks; `<dir>/screen.txt` the screen text; `<dir>/hooks.jsonl`
the PreToolUse and UserPromptSubmit payloads a logging hook saw.
"""

from __future__ import annotations

import argparse
import json
import os
import pty
import re
import select
import shutil
import signal
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixture.sh")
PROMPT = "T001 of the CSV export is done and verified. Commit it."
REPLY = "it can go"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[()][A-Za-z0-9]")
DOWN, ESC, ENTER = "\x1b[B", "\x1b", "\r"
GO_LABEL = "Commit"


def parse_args():
    parser = argparse.ArgumentParser(
        description="The two-turn check of SC-010: a gate question, then a reply.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True, help="a new or empty directory")
    parser.add_argument("--config-dir", help="CLAUDE_CONFIG_DIR of the account that pays")
    parser.add_argument("--home", help="HOME for the session (a scratch HOME)")
    parser.add_argument("--plugin-dir", help="load this plugin copy too (--plugin-dir)")
    parser.add_argument("--reply-mode", choices=("answer", "prompt"), default="answer")
    parser.add_argument("--timeout", type=int, default=420, help="seconds per turn")
    return parser.parse_args()


class Screen:
    def __init__(self, fd, path):
        self.fd = fd
        self.text = ""
        self.log = open(path, "w", encoding="utf-8")

    def pump(self, seconds):
        """Read the pty for `seconds`. False once the session has exited."""
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([self.fd], [], [], 0.5)
            if self.fd not in ready:
                continue
            try:
                chunk = os.read(self.fd, 65536).decode("utf-8", "replace")
            except OSError:
                return False
            if not chunk:
                return False
            clean = ANSI.sub("", chunk)
            self.text += clean
            self.log.write(clean)
            self.log.flush()
        return True

    def wait_for(self, pattern, seconds, since=0):
        """Wait for `pattern` in the screen text after offset `since`."""
        end = time.time() + seconds
        while time.time() < end:
            if re.search(pattern, self.text[since:]):
                return True
            if not self.pump(1):
                return False
        return False

    def send(self, keys, pause=0.3):
        os.write(self.fd, keys.encode())
        time.sleep(pause)


def logged(path):
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    return rows


def questions(path):
    return [row for row in logged(path) if row.get("hook_event_name") == "PreToolUse"
            and row.get("tool_name") == "AskUserQuestion"]


def first_question(row):
    """The header and the option labels of a logged `AskUserQuestion` call."""
    question = ((row.get("tool_input") or {}).get("questions") or [{}])[0]
    return {"header": question.get("header"),
            "options": [o.get("label") for o in question.get("options", [])]}


def go_index(question):
    """The position of the go option (`Commit`, any case), or None."""
    for index, label in enumerate(question.get("options") or []):
        if isinstance(label, str) and label.strip().casefold() == GO_LABEL.casefold():
            return index
    return None


def commits(repo):
    out = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=repo,
                         capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() else -1


def journal_rows(repo):
    conn = sqlite3.connect(os.path.join(repo, ".claude", "shipgate.db"))
    try:
        rows = conn.execute(
            "SELECT seq, type, data, actor FROM events WHERE type IN "
            "('go-requested', 'reply-witnessed', 'gate-decision') ORDER BY seq"
        ).fetchall()
    finally:
        conn.close()
    return [{"seq": s, "type": t, "data": json.loads(d), "actor": a} for s, t, d, a in rows]


def main():
    args = parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    repo = os.path.join(out, "repo")
    shutil.rmtree(repo, ignore_errors=True)
    os.makedirs(repo)
    subprocess.run(["bash", FIXTURE], cwd=repo, check=True)
    start_commits = commits(repo)

    log = os.path.join(out, "hooks.jsonl")
    logger = os.path.join(out, "logger.py")
    with open(logger, "w", encoding="utf-8") as handle:
        handle.write("import sys\nwith open(%r, 'a') as f:\n"
                     "    f.write(sys.stdin.read().replace('\\n', ' ') + '\\n')\n" % log)
    settings = os.path.join(out, "settings.json")
    hook = {"type": "command", "command": f"{sys.executable} {logger}"}
    with open(settings, "w", encoding="utf-8") as handle:
        json.dump({"hooks": {
            "PreToolUse": [{"matcher": "*", "hooks": [hook]}],
            "UserPromptSubmit": [{"hooks": [hook]}],
        }}, handle)

    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID")}
    env["TERM"] = "xterm-256color"
    if args.config_dir:
        env["CLAUDE_CONFIG_DIR"] = args.config_dir
    if args.home:
        env["HOME"] = args.home
    argv = ["claude", "--model", args.model, "--settings", settings, "--strict-mcp-config",
            "--allowedTools", "Bash", "Read", "Grep", "Glob", "Edit", "Write", "Skill",
            "AskUserQuestion"]
    if args.plugin_dir:
        argv += ["--plugin-dir", args.plugin_dir]
    argv += ["--", PROMPT]

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(repo)
        os.execvpe("claude", argv, env)
    screen = Screen(fd, os.path.join(out, "screen.txt"))
    result = {"model": args.model, "reply_mode": args.reply_mode}

    # A new directory asks for trust first, and the dialog defaults to "No, exit".
    if screen.wait_for(r"trust", 60):
        screen.send(DOWN)
        screen.send(ENTER)
    deadline = time.time() + args.timeout
    while time.time() < deadline and not questions(log):
        if not screen.pump(2):
            break
    asked = questions(log)
    if not asked:
        result["error"] = "turn 1 ended with no AskUserQuestion call"
    else:
        result["question"] = first_question(asked[0])
        screen.wait_for(r"Enter to select|Esc to cancel", 30)
        screen.pump(2)
        if args.reply_mode == "answer":
            for _ in range(len(result["question"]["options"])):
                screen.send(DOWN)  # to the free-text row after the options
            screen.send(REPLY)
            screen.send(ENTER)
        else:
            screen.send(ESC)
            screen.pump(4)
            if re.search(r"Enter to confirm", screen.text[-400:]):
                screen.send(ESC)  # a tip dialog after the turn; dismiss it before typing
            screen.send(REPLY)
            screen.send(ENTER)
        asked_before = len(questions(log))
        deadline = time.time() + args.timeout
        clicked = False
        while time.time() < deadline:
            # The dialog renders after the logging hook fires, inside the same pump.
            mark = len(screen.text)
            if not screen.pump(3):
                break
            if commits(repo) > start_commits:
                screen.pump(10)
                break
            later = questions(log)[asked_before:]
            if later and not clicked:
                # The confirming question: select the go option and wait for the commit.
                result["confirming"] = first_question(later[0])
                index = go_index(result["confirming"])
                if index is None:
                    break  # no go option to click: the check fails here
                screen.wait_for(r"Enter to select|Esc to cancel", 30, since=mark)
                screen.pump(2)
                for _ in range(index):
                    screen.send(DOWN)
                screen.send(ENTER)
                clicked = True
            elif len(later) > 1:
                break  # a second question after the click: the check fails here
        result["questions_after_reply"] = len(questions(log)) - asked_before
    result["committed"] = commits(repo) > start_commits

    for keys in ("\x03", "\x03"):
        try:
            screen.send(keys, pause=0.5)
        except OSError:
            break
    screen.pump(2)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass

    rows = journal_rows(repo)
    witnesses = [r["seq"] for r in rows if r["type"] == "reply-witnessed"]
    question_gos = [r for r in rows if r["type"] == "gate-decision"
                    and r["data"].get("source") == "question"
                    and r["data"].get("gate") in ("commit", "publish")]
    confirming = result.get("confirming") or {}
    checks = {
        "go_requested": any(r["type"] == "go-requested" for r in rows),
        "header_commit": (result.get("question") or {}).get("header") == "Commit",
        "witness": bool(witnesses),
        "one_confirming_question": result.get("questions_after_reply") == 1,
        "confirming_header_commit": confirming.get("header") == "Commit"
        and go_index(confirming) is not None,
        "question_go_after_the_witness": bool(witnesses) and any(
            r["seq"] > witnesses[0] for r in question_gos),
        "committed": result["committed"],
    }
    result.update(rows=rows, checks=checks, passed=all(checks.values()))
    with open(os.path.join(out, "result.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps({"model": args.model, "passed": result["passed"], "checks": checks,
                      "error": result.get("error")}))
    if result.get("error"):
        sys.exit(2)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
