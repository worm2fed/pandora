#!/usr/bin/env python3
"""SessionStart hook — hand the session its position before it thinks to ask.

Injects the journal's resume brief as context, and opens the session's event window by
recording `session-started`. That window is what `journal.py check` measures against at
Stop time: everything appended after this event belongs to this session.

The session id is also handed to `journal.py session --set`, because a skill's shell
cannot see it and `append` needs it to attribute skill-written events (ADR 0003).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    append_event,
    emit,
    likely_journaled,
    read_hook_input,
    resolve_project,
    run_journal,
    safe_main,
    watch_paths,
)

META_STREAM = "shipgate"
GIT_TIMEOUT_SECONDS = 2
# Where an umbrella keeps its nested repos — the same three places `setup` looks.
NESTED_REPO_PARENTS = ("", "source", "packages")
# Where `workspace` puts a git worktree: `.worktrees/<slug>` beside the repos or inside one.
WORKTREES_DIR = ".worktrees"
NESTED_REPO_LIMIT = 64
NESTED_ENTRY_LIMIT = 512  # directory entries examined per parent
HEAD_REF_PREFIX = "ref: refs/heads/"
MAX_BRANCH_LENGTH = 255


def current_branch(cwd):
    """The branch checked out in `cwd`, or None when there is no name worth passing.

    A detached HEAD answers with the literal `HEAD`, which is not a branch and matches
    no stream. No git, no repository and a hung git all land here as None as well: the
    branch is an ordering hint for the brief, never a reason to degrade it.
    """
    import subprocess

    if not isinstance(cwd, str):
        return None
    # `GIT_DIR`/`GIT_WORK_TREE` inherited from the session point git at whatever
    # repository set them, not at `cwd`; drop the whole family rather than guess.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return _branch_name((result.stdout or "").strip())


def _read_first_line(path):
    """The first line of a regular file, or None.

    A checkout is untrusted content: `path` may be a FIFO, a device or a symlink to one,
    and a plain `open()` would block the hook on it. Open non-blocking, refuse anything
    that is not a regular file, read a bounded number of bytes.
    """
    import stat

    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        raw = os.read(fd, MAX_BRANCH_LENGTH + len(HEAD_REF_PREFIX) + 8)
    except (OSError, ValueError):
        return None
    finally:
        if fd is not None:
            os.close(fd)
    return raw.split(b"\n", 1)[0].decode("utf-8", "replace").strip()


def _branch_name(text):
    """`text` as a branch name worth passing on, else None.

    The name travels as one argv token: a NUL would make `subprocess` refuse the whole
    call, a control character has no business in a branch. Over-long names are noise.
    """
    if not text or len(text) > MAX_BRANCH_LENGTH or text == "HEAD":
        return None
    if "\0" in text or not text.isprintable():
        return None
    return text


def _within(path, root):
    """True when `path` resolves to somewhere under `root` (symlinks followed)."""
    real_root = os.path.realpath(root)
    return os.path.realpath(path).startswith(real_root.rstrip(os.sep) + os.sep)


def head_branch(git_entry, root):
    """The branch a nested repo's `.git` names, read from its HEAD file — no subprocess.

    `.git` is a directory, or (a worktree, a submodule) a file `gitdir: <path>`, followed
    once and only when it stays under `root`, the session's directory — a checkout must
    not point the hook at files elsewhere on disk. A detached HEAD holds a hash, not a
    `ref:` line, and names no branch; so does anything unreadable, over-long or not a
    regular file. Only ever a hint for ordering the brief.
    """
    git_dir = git_entry
    if os.path.isfile(git_entry):
        line = _read_first_line(git_entry)
        if not line or not line.startswith("gitdir:"):
            return None
        target = line[len("gitdir:"):].strip()
        if not target:
            return None
        git_dir = os.path.join(os.path.dirname(git_entry), target)
        if not _within(git_dir, root):
            return None
    line = _read_first_line(os.path.join(git_dir, "HEAD"))
    if not line or not line.startswith(HEAD_REF_PREFIX):
        return None
    return _branch_name(line[len(HEAD_REF_PREFIX):])


def _is_repo(directory):
    """A `.git` entry of its own (directory or `gitdir:` file), never through a symlink."""
    git_entry = os.path.join(directory, ".git")
    return os.path.lexists(git_entry) and not os.path.islink(git_entry)


def _child_dirs(base):
    """Real (unlinked) child directories of `base`, sorted, dot-names and node_modules
    left out, at most NESTED_ENTRY_LIMIT entries examined; [] when unreadable or when
    `base` is itself a symlink (a checkout must not point the scan elsewhere)."""
    if os.path.islink(base):
        return []
    try:
        with os.scandir(base) as entries:
            return sorted(
                os.path.join(base, entry.name)
                for entry in _bounded(entries, NESTED_ENTRY_LIMIT)
                if entry.is_dir(follow_symlinks=False)
                and not entry.name.startswith(".")
                and entry.name != "node_modules"
            )
    except OSError:
        return []


def nested_branches(cwd, own=None):
    """Branches checked out in the nested repos of an umbrella checkout, deduplicated.

    An umbrella holds the real repos one level down (`*/`, `source/*`, `packages/*`);
    its own directory is a plain folder or a repo on a branch that carries no stream.
    A git worktree made by `workspace` sits in `.worktrees/<slug>` beside the repos or
    inside one, so each parent's and each repo's `.worktrees/` is looked into as well.
    Other dot-directories, `node_modules` and symlinked entries are not; the first
    NESTED_ENTRY_LIMIT entries of a directory are examined (sorted among themselves) and
    NESTED_REPO_LIMIT repos read in all, top level first, a repo's worktrees right after
    it, and the scan stops where the reads do. A single repo with no nested `.git` costs
    a few directory scans. Nothing here may raise: the branches are an ordering hint for
    the brief, and losing the brief over a hint would invert the hook's priorities.
    """
    if not isinstance(cwd, str):
        return []
    seen = {own} if own else set()
    found = []
    try:
        for directory in _bounded(_nested_repo_dirs(cwd), NESTED_REPO_LIMIT):
            branch = head_branch(os.path.join(directory, ".git"), cwd)
            if branch and branch not in seen:
                seen.add(branch)
                found.append(branch)
    except Exception:  # noqa: BLE001 — a hint, never the brief
        return found
    return found


def _nested_repo_dirs(cwd):
    """Yield each nested repo and worktree directory once, in brief order, lazily — so a
    cap on the consumer bounds the scanning too."""
    visited = set()

    def fresh(directory):
        if directory in visited or not _is_repo(directory):
            return False
        visited.add(directory)
        return True

    for parent in NESTED_REPO_PARENTS:
        base = os.path.join(cwd, parent) if parent else cwd
        for repo in _child_dirs(base):
            if not fresh(repo):
                continue
            yield repo
            for worktree in _child_dirs(os.path.join(repo, WORKTREES_DIR)):
                if fresh(worktree):
                    yield worktree
        for worktree in _child_dirs(os.path.join(base, WORKTREES_DIR)):
            if fresh(worktree):
                yield worktree


def _bounded(iterable, limit):
    for index, item in enumerate(iterable):
        if index >= limit:
            return
        yield item


def main() -> None:
    if likely_journaled() is None:
        sys.exit(0)

    payload = read_hook_input()
    project = resolve_project(payload)
    if project is None:
        sys.exit(0)

    session_id = payload.get("session_id") or "unknown"
    append_event(
        project,
        META_STREAM,
        "session-started",
        {"session": session_id, "source": payload.get("source") or "startup"},
    )
    attributed = run_journal(project, ["session", f"--set={session_id}"])
    notice = (
        ""
        if attributed is not None and attributed.returncode == 0
        else (
            "shipgate: session attribution unavailable (journal.py session --set "
            "failed) — skill appends this session will carry no session label.\n\n"
        )
    )

    watched = watch_paths(project)

    branch = current_branch(payload.get("cwd"))
    # `--branch=<name>`, never two tokens: a branch may be literally named `--all`,
    # and argparse would read the second token as a flag. In an umbrella checkout the
    # nested repos' branches go along as `--nested-branch=<name>`; which of them (if
    # any) orders the brief is the journal's call, not the hook's.
    status_args = ["status"] + ([f"--branch={branch}"] if branch else [])
    status_args += [
        f"--nested-branch={nested}"
        for nested in nested_branches(payload.get("cwd"), own=branch)
    ]
    result = run_journal(project, status_args)
    if result is None or result.returncode != 0:
        # The journal is configured but unreachable. Say so rather than starting the
        # session silently blind — the orchestrator treats this as an infrastructure
        # problem needing acknowledgement, not as an un-journaled project.
        detail = (result.stderr or "").strip() if result else "journal CLI unavailable"
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "watchPaths": watched,
                    "additionalContext": (
                        "shipgate: this project declares a flow journal, but reading it "
                        f"failed ({detail or 'unknown error'}). Do NOT silently fall back "
                        "to inferring phase from artifacts — surface this, suggest "
                        "`journal.py doctor`, and continue only with the user's "
                        "acknowledgement."
                    ),
                }
            }
        )
        sys.exit(0)

    brief = (result.stdout or "").strip()
    if not brief:
        specific = {"hookEventName": "SessionStart", "watchPaths": watched}
        if notice:
            specific["additionalContext"] = notice.strip()
        emit({"hookSpecificOutput": specific})
        sys.exit(0)

    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "watchPaths": watched,
                "additionalContext": notice
                + (
                    "shipgate flow journal — this is the authoritative position for "
                    "work in this project. Route from it; do not re-derive phase by "
                    "scanning worklog checkboxes.\n\n" + brief
                ),
            }
        }
    )


safe_main(main)
