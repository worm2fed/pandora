"""Close-out and sweep from observed evidence (ADR 0025, ADR 0026)."""

from __future__ import annotations

import json
import re
import shlex
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any, Callable, Dict, List, Literal, Optional, Sequence, Set, Tuple, TypedDict,
)
from urllib.parse import urlsplit

from .vocab import (
    CLOSEOUT_CHOSEN_PLACEHOLDER, CLOSEOUT_QUESTION_PLACEHOLDER, GateViolation, InfraError,
    VersionConflict,
)
from .plugin import _config, _journal_prefix, NO_COMMAND
from .text import _clip, _one_line, _printable, _short_ts, _string_or_none
from .project import _config_files, _config_label
from .store import _parse_ts, list_streams, read_events
from .fold import _newest_string, fold_stream, is_work_stream
from .append import append_event
from .reply import GATE_WORDS, GENERAL_WORDS, reply_word


# --------------------------------------------------------------------------
# Evidence for the close-out and the sweep (ADR 0025): the flow runs the forge CLI
# and git and writes files into a fresh directory; these pure functions parse them.
# The journal itself runs no subprocess.
# --------------------------------------------------------------------------

OBSERVED_FILES = {"prs": "forge.json", "refs": "refs.txt", "merged": "merged.txt",
                  "worktrees": "worktrees.txt", "base": "base.txt",
                  "first_parent": "first-parent.txt",
                  "worktree_files": "worktree-status.txt"}
# An observed file is the flow's own output, but its size is still bounded.
OBSERVED_MAX_BYTES = 4 * 1024 * 1024
MergeState = Literal["merged", "closed", "open", "gone", "unknown"]
EvidenceSource = Literal["forge", "git", "none"]
# gh writes OPEN, CLOSED, MERGED; glab writes opened, closed, merged, locked. glab's
# locked is an MR in the middle of its merge, so the work is not done yet (F50).
_FORGE_STATES = {
    "gh": {"MERGED": "merged", "CLOSED": "closed", "OPEN": "open"},
    "glab": {"merged": "merged", "closed": "closed", "opened": "open", "locked": "open"},
}
# The keys each CLI's JSON carries: url, head branch, head commit, base branch, merge time.
_FORGE_KEYS = {
    "gh": ("url", "headRefName", "headRefOid", "baseRefName", "mergedAt"),
    "glab": ("web_url", "source_branch", "sha", "target_branch", "merged_at"),
}


def _forge_pr(item: Any) -> Optional[Dict[str, Any]]:
    """One PR/MR object of gh or glab JSON, normalized, or None for another shape."""
    if not isinstance(item, dict):
        return None
    forge = "gh" if "headRefName" in item else "glab" if "source_branch" in item else None
    if forge is None:
        return None
    raw = item.get("state")
    state = _FORGE_STATES[forge].get(raw) if isinstance(raw, str) else None
    url, head, head_oid, base, merged_at = (
        _string_or_none(item.get(key)) for key in _FORGE_KEYS[forge]
    )
    if state is None or head is None:
        return None
    # A fork's branch name says nothing about this repo's branches.
    if forge == "gh":
        fork = item.get("isCrossRepository") is True
    else:
        source, target = item.get("source_project_id"), item.get("target_project_id")
        fork = source is not None and target is not None and source != target
    return {"forge": forge, "state": state, "raw_state": raw, "url": url, "head": head,
            "head_oid": head_oid, "base": base, "merged_at": merged_at, "fork": fork}


def parse_forge_prs(text: str) -> Optional[List[Dict[str, Any]]]:
    """The PRs/MRs of one ``gh pr view|list --json`` or ``glab mr view|list -F json``
    output, one object or a list; None when the text is no JSON object or list, or a
    non-empty list of which no entry has the expected shape."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None
    prs = [pr for pr in map(_forge_pr, data) if pr is not None]
    # Entries that all lost the expected keys are a format drift, not "no PR/MR" (F39).
    return prs if prs or not data else None


def parse_refs(text: str) -> Dict[str, str]:
    """``<oid> <refname>`` lines (``git for-each-ref --format='%(objectname)
    %(refname)'``) as refname to oid; a line of another shape is skipped."""
    refs: Dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{7,64}", parts[0]):
            refs[parts[1]] = parts[0]
    return refs


def parse_merged(text: str) -> Set[str]:
    """The refnames of ``git for-each-ref --merged <base>`` output, in ``parse_refs``'s
    format."""
    return set(parse_refs(text))


def parse_first_parent(text: str) -> Set[str]:
    """The commits of ``git rev-list --first-parent <base>``, one oid per line; a line
    of another shape is skipped."""
    return {line.strip() for line in text.splitlines()
            if re.fullmatch(r"[0-9a-f]{7,64}", line.strip())}


def parse_base(text: str) -> Optional[str]:
    """The integration branch the observe script read from ``origin/HEAD`` (else
    ``main``): the first line, or None when it is empty or cannot be a branch name."""
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not line or line.startswith("-") or not line.isprintable() or " " in line:
        return None
    return line


def parse_worktrees(text: str) -> List[Dict[str, Optional[str]]]:
    """``git worktree list --porcelain`` as ``{path, head, branch}`` per worktree; the
    first entry is the main checkout. ``branch`` is None for a detached or bare one."""
    trees: List[Dict[str, Optional[str]]] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        entry: Dict[str, Optional[str]] = {"path": None, "head": None, "branch": None}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if key == "worktree":
                entry["path"] = value
            elif key == "HEAD":
                entry["head"] = value
            elif key == "branch":
                entry["branch"] = value[len("refs/heads/"):] if value.startswith(
                    "refs/heads/") else value
        if entry["path"]:
            trees.append(entry)
    return trees


def parse_worktree_files(text: str) -> List[str]:
    """The ignored (``!!``) and untracked (``??``) entries of ``git status --porcelain
    --ignored`` in the stream's worktree: what ``worktree remove`` deletes with it, or
    refuses on (F60). A change to a tracked file is not one of them."""
    return [line[3:] for line in text.splitlines() if line[:3] in ("!! ", "?? ")]


def _read_observed_file(path: Path) -> Optional[str]:
    try:
        if not path.is_file() or path.stat().st_size > OBSERVED_MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_observed(directory: Path) -> Dict[str, Any]:
    """The evidence files of an observe directory, parsed; a missing or unreadable
    file is None, so the decision falls back to the next source and says so."""
    parsers: Dict[str, Callable[[str], Any]] = {
        "prs": parse_forge_prs, "refs": parse_refs, "merged": parse_merged,
        "worktrees": parse_worktrees, "base": parse_base,
        "first_parent": parse_first_parent, "worktree_files": parse_worktree_files,
    }
    texts = {key: _read_observed_file(directory / name)
             for key, name in OBSERVED_FILES.items()}
    return {key: parsers[key](text) if text is not None else None
            for key, text in texts.items()}


# An open PR/MR on the branch means the work goes on, whatever merged before it.
_PR_STATE_RANK = {"open": 0, "merged": 1, "closed": 2}


_PR_URL_RE = re.compile(r"^(.*?/(?:pull|merge_requests)/\d+)(?:[/?#]|$)")


def _pr_url_key(url: Optional[str]) -> Optional[str]:
    """A PR/MR URL cut at its number, host lower-cased, so ``.../pull/7/files`` and
    ``.../pull/7`` compare equal (F40). A URL that urlsplit refuses is its own key."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    match = _PR_URL_RE.match(parts.path)
    return f"{parts.scheme}://{(parts.netloc or '').lower()}" + (
        match.group(1) if match else parts.path.rstrip("/"))


def _stream_pr(stream: str, url: Optional[str],
               prs: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The stream's own PR/MR: the ``mr-opened`` URL first, then a PR/MR of this repo
    whose head is the stream exactly; open before merged before closed. A fork's PR/MR
    matches by its URL only."""
    key = _pr_url_key(url)
    if key:
        for pr in prs:
            if _pr_url_key(pr["url"]) == key:
                return pr
    named = [pr for pr in prs if not pr["fork"] and pr["head"] == stream]
    named.sort(key=lambda pr: _PR_STATE_RANK[pr["state"]])
    return named[0] if named else None


# F51: the close-out acts on exact names only; the sweep shows the stream to the user.
_SWEEP_HINT = "once the stream is dormant, journal.py sweep lists it and the user decides"


def merge_evidence(facts: Dict[str, Any], prs: Optional[Sequence[Dict[str, Any]]],
                   refs: Optional[Dict[str, str]],
                   merged: Optional[Set[str]],
                   first_parent: Optional[Set[str]] = None,
                   sweep: bool = False) -> Dict[str, Any]:
    """Did the stream's PR/MR merge, and what showed it (ADR 0025, amended twice).

    ``facts``: ``stream``, ``base`` (the integration branch the observe script read,
    ``base.txt``) and ``url`` (the ``mr-opened`` URL or None). Nothing is guessed: the
    branch is the stream's exact name, and the PR/MR is the recorded one or one whose
    head is the stream. The close-out acts on no recorded PR/MR with another head; the
    ``sweep`` reads it, since it writes only journal events after one confirmation.
    The forge's state wins. When the forge answered and holds no PR/MR for the stream,
    git may say gone or unknown, never merged. With no forge evidence, a branch tip in
    ``merged`` is merged only off the base's first-parent line, where a merge commit
    puts it; a branch cut from the base with no commit of its own sits on that line. A
    stream named as the integration branch is never closed. ``squash`` marks a forge
    merge into the observed base whose local branch tip is not in ``merged``: git calls
    it unmerged, so ``branch -d`` refuses it.
    """
    stream = facts["stream"]
    pr = _stream_pr(stream, facts.get("url"), prs) if prs else None
    observed_base = facts.get("base") or "main"
    base = (pr or {}).get("base") or observed_base
    local_ref, remote_ref = f"refs/heads/{stream}", f"refs/remotes/origin/{stream}"
    local = (refs or {}).get(local_ref)
    result: Dict[str, Any] = {"state": "unknown", "source": "none",
                              "url": facts.get("url"), "base": base, "head_oid": None,
                              "detail": "", "squash": False,
                              "local_branch": local is not None}
    if stream in (base, observed_base):
        result["detail"] = (f"the stream names the integration branch {stream}; the "
                            "close-out never removes or deletes it")
        return result
    if pr is not None:
        stamp = _short_ts(pr["merged_at"]) if pr["merged_at"] else ""
        detail = " · ".join(part for part in (
            f"forge {pr['forge']}: {pr['raw_state']}" + (f" {stamp}" if stamp else ""),
            f"head {pr['head_oid'][:7]}" if pr["head_oid"] else "",
            pr["url"] or "",
        ) if part)
        result.update({"source": "forge", "url": pr["url"] or facts.get("url")})
        if not sweep and pr["head"] != stream:
            result["detail"] = (f"{detail}; its head {pr['head']} is not the stream's "
                                f"name, so the close-out acts on no branch; {_SWEEP_HINT}")
            return result
        result.update({
            "state": pr["state"], "head_oid": pr["head_oid"], "detail": detail,
            # ``merged`` holds the refs merged into the observed base only, so a PR
            # that merged into another base says nothing about a squash.
            "squash": bool(pr["state"] == "merged" and local is not None
                           and merged is not None and local_ref not in merged
                           and pr["base"] == observed_base),
        })
        return result
    url = facts.get("url")
    forge_note = ("forge evidence missing" if prs is None
                  else f"forge: no PR/MR for {stream}" + (f" or {url}" if url else ""))
    if refs is None:
        result["detail"] = f"{forge_note}; git evidence missing"
        return result
    base_tip = refs.get(f"refs/remotes/origin/{base}")
    result["source"] = "git"
    present = [(ref, refs[ref]) for ref in (local_ref, remote_ref) if ref in refs]
    if not present:
        result.update({"state": "gone",
                       "detail": f"{forge_note}; git: no local or remote branch {stream}"
                                 + ("" if sweep else f"; {_SWEEP_HINT}")})
        return result
    # The user's ruling on F24: when the forge answered and holds no PR/MR for the
    # stream, git may say gone or unknown, never merged.
    if prs is not None:
        result["detail"] = f"{forge_note}, and a stream with no PR/MR is never merged"
        return result
    if first_parent is None:
        result["detail"] = (f"{forge_note}; git: first-parent evidence missing, so git "
                            "alone cannot show a merge")
        return result
    on_line: Optional[Tuple[str, str]] = None
    for ref, oid in present:
        if merged is None or ref not in merged:
            continue
        if oid == base_tip or oid in first_parent:
            on_line = on_line or (ref, oid)
            continue
        result.update({"state": "merged", "head_oid": oid,
                       "detail": f"{forge_note}; git: {ref} {oid[:7]} is in "
                                 f"origin/{base}, off its first-parent line"})
        return result
    if on_line is not None:
        result["detail"] = (f"{forge_note}; git: {on_line[0]} {on_line[1][:7]} is on "
                            f"origin/{base}'s first-parent line, so no commit of its own "
                            "shows a merge")
    else:
        result["detail"] = f"{forge_note}; git: {stream} is not in origin/{base}"
    return result


def forge_from_url(url: Optional[str]) -> Optional[str]:
    """``gh`` for a ``github.`` host, ``glab`` for a host that names ``gitlab``; None
    for another host or a URL that urlsplit refuses (F52)."""
    if not isinstance(url, str):
        return None
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return None
    if host == "github.com" or host.startswith("github."):
        return "gh"
    if "gitlab" in host:
        return "glab"
    return None


def forge_from_config(value: Optional[str]) -> Optional[str]:
    """The CLI a **Forge & tracker** ``Forge:`` value names (``GitHub — CLI: gh``), or
    the one its forge implies; None for a placeholder or another forge."""
    if not value or _config.is_placeholder_value(value.strip()):
        return None
    named = re.search(r"CLI:\s*`?([A-Za-z]+)", value)
    if named:
        cli = named.group(1).lower()
        return cli if cli in ("gh", "glab") else None
    lowered = value.lower()
    if "github" in lowered:
        return "gh"
    if "gitlab" in lowered:
        return "glab"
    return None


GH_PR_FIELDS = ("state,url,headRefName,headRefOid,baseRefName,mergedAt,mergeCommit,"
                "isCrossRepository")
# A sweep reads every PR/MR in one query: gh pages itself up to this many; glab reads
# one page of this size. The forge answered, so a stream whose MR is older than that
# page reads unknown (kept), or gone (unknown: the user decides) when no branch is left.
SWEEP_GH_LIMIT = 1000
SWEEP_GLAB_PER_PAGE = 100


def _glab_iid(url: Optional[str]) -> Optional[str]:
    match = re.search(r"/merge_requests/(\d+)(?:[/?#]|$)", url or "")
    return match.group(1) if match else None


def _forge_url(url: Any) -> Optional[str]:
    """A recorded PR/MR URL the observe script may pass to the forge CLI: an
    ``https://`` URL only, so it can never reach the CLI as a flag."""
    return url if isinstance(url, str) and url.startswith("https://") else None


def observe_script(kind: str, facts: Dict[str, Any], forge: Optional[str]) -> str:
    """The shell text that writes the evidence files into a fresh directory (ADR 0025).

    ``kind`` is ``closeout`` (one stream: ``branch``, ``url``) or ``sweep`` (one list
    query for every stream). ``facts`` carries ``project_dir`` too. ``forge`` is ``gh``,
    ``glab`` or None (git evidence only). The integration branch is git's: the script
    reads ``origin/HEAD``, else uses ``main``, and writes it to ``base.txt`` beside the
    base's first-parent line. Every value is shell-quoted. The last line prints the
    directory, which the rerun passes as ``--observed``.
    """
    q = shlex.quote
    url = _forge_url(facts.get("url"))
    lines = [
        'd=$(mktemp -d "${TMPDIR:-/tmp}/shipgate-observe.XXXXXX") || exit 1',
        f"cd {q(str(facts['project_dir']))} || exit 1",
    ]
    out = '> "$d/forge.json"'
    if forge == "gh":
        if kind == "sweep":
            lines.append(f"gh pr list --state all --limit {SWEEP_GH_LIMIT} "
                         f"--json {GH_PR_FIELDS} {out}")
        elif url:
            lines.append(f"gh pr view {q(url)} --json {GH_PR_FIELDS} {out}")
        else:
            lines.append(f"gh pr list {q('--head=' + facts['branch'])} --state all "
                         f"--json {GH_PR_FIELDS} {out}")
    elif forge == "glab":
        iid = _glab_iid(url)
        if kind == "sweep":
            lines.append(f"glab mr list --all --per-page {SWEEP_GLAB_PER_PAGE} -F json {out}")
        elif iid:
            lines.append(f"glab mr view {iid} -F json {out}")
        else:
            lines.append(f"glab mr list {q('--source-branch=' + facts['branch'])} --all "
                         f"-F json {out}")
    else:
        lines.append("# no forge CLI: git evidence only")
    fmt = q("%(objectname) %(refname)")
    lines += [
        "git fetch --prune origin",
        "base=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)",
        'base=${base#origin/}; [ -n "$base" ] || base=main',
        "printf '%s\\n' \"$base\" > \"$d/base.txt\"",
        f'git for-each-ref --format={fmt} refs/heads refs/remotes > "$d/refs.txt"',
        f'git for-each-ref "--merged=refs/remotes/origin/$base" --format={fmt} '
        'refs/heads refs/remotes > "$d/merged.txt"',
        'git rev-list --first-parent "refs/remotes/origin/$base" > "$d/first-parent.txt"',
        'git worktree list --porcelain > "$d/worktrees.txt"',
    ]
    if kind == "closeout":
        # F60: the files `worktree remove` deletes (ignored) or refuses on (untracked),
        # from the linked worktree whose branch is the stream. The file is kept only
        # when git succeeds, so a failure reads as not observed. `--untracked-files`
        # overrides `status.showUntrackedFiles=no`, which hides ignored files too (F61).
        where = q("branch refs/heads/" + facts["branch"])
        lines += [
            f"w=$(awk -v b={where} '$1 == \"worktree\" {{ n++; p = substr($0, 10) }} "
            "n > 1 && $0 == b { print p }' \"$d/worktrees.txt\")",
            'if [ -n "$w" ]; then git -C "$w" status --porcelain --ignored '
            '--untracked-files=normal > "$d/ws.tmp" && mv "$d/ws.tmp" '
            '"$d/worktree-status.txt"; fi',
        ]
    lines.append("printf 'observed: %s\\n' \"$d\"")
    # A value that does not print on one line would split a line of the script.
    if not all(line.isprintable() for line in lines):
        return NO_COMMAND
    return "\n".join(lines)


CLOSEOUT_SECTION = "close-out"


class CloseoutRule(TypedDict):
    label: str
    action: str
    source: str


def closeout_rules(project_dir: Path, start: Optional[Path] = None) -> List[CloseoutRule]:
    """The project's post-merge steps (FR-015): the `- <Label>: <action>` bullets of
    the nearest config file's **Close-out** section, through the layers of
    ``config_candidates`` and the user file (ADR 0018). A project's steps are arbitrary
    commands, so each one is an ``ask`` step in the one close-out question: no mark and
    no word list decide it (the user's ruling on F25 and F26, ADR 0026 amendment). A
    wrapped bullet is one rule; fenced code and HTML comments are inert
    (``section_bullets``). The label shows as written."""
    owner = _config.section_owner(_config_files(project_dir, start), CLOSEOUT_SECTION)
    if owner is None:
        return []
    rules: List[CloseoutRule] = []
    for label, value in _config.section_bullets(owner.text, CLOSEOUT_SECTION,
                                                keep_case=True):
        action = _one_line(value)
        if _config.is_placeholder(action) or _config.is_placeholder(label):
            continue
        rules.append({"label": _one_line(label), "action": action,
                      "source": _config_label(owner, project_dir)})
    return rules


FORGE_SECTION = "forge & tracker"
CLOSEOUT_HEADER = "Close-out"


CLOSEOUT_RULE_LINE = (
    "No step takes --force, -f or -D. A step git refuses stops: quote git and ask."
)
# The words the recorder hook reads as a go (ADR 0023); an option label is never one.
_RECORDER_WORDS = frozenset(GATE_WORDS) | GENERAL_WORDS


def configured_forge(project_dir: Path, start: Optional[Path] = None) -> Optional[str]:
    """The forge CLI the nearest **Forge & tracker** section's ``Forge:`` bullet names.
    The integration branch is never read from the config: the observe script reads it
    from git (``base.txt``)."""
    owner = _config.section_owner(_config_files(project_dir, start), FORGE_SECTION)
    if owner is None:
        return None
    for key, value in _config.section_bullets(owner.text, FORGE_SECTION):
        if key == "forge":
            return forge_from_config(value)
    return None


class CloseoutStep(TypedDict):
    n: int
    kind: str  # run | ask | skip
    title: str
    command: Optional[str]
    label: Optional[str]
    # The command alone stands for the step (no title printed before it).
    bare: bool
    # The last step's command when the user chose the squash-merged branch's deletion.
    alt: Optional[str]
    # An ask step's command, shown beside its option label in the question (F53).
    approves: Optional[str]


def _git(tree: str, *args: str) -> str:
    return " ".join(["git", "-C", shlex.quote(tree), *(shlex.quote(a) for a in args)])


def _clean(tree: str) -> str:
    return f'test -z "$({_git(tree, "status", "--porcelain")})"'


def _held_files(files: Optional[List[str]]) -> str:
    """The removal step's note on the worktree's ignored and untracked paths (F60). Git
    prints a wholly ignored or untracked directory as one path (F62)."""
    if files is None:
        return ("its files were not observed, and an ignored file is deleted with the "
                "worktree")
    shown = ", ".join(_one_line(name) for name in files[:5]) + (
        ", …" if len(files) > 5 else "")
    return (f"it holds {len(files)} ignored or untracked "
            f"{'path' if len(files) == 1 else 'paths'} ({shown}), deleted with the worktree")


def _option_label(label: str, n: int) -> str:
    """The option label of an ``ask`` step: never a word the recorder reads as a go."""
    text = _one_line(label)[:60] or f"Step {n}"
    return f"Step {n}: {text}" if reply_word(text) in _RECORDER_WORDS else text


def _journal_append(db_path: Path, stream: str, event_type: str, data: Dict[str, Any],
                    actor: Optional[str] = None) -> Optional[str]:
    words = [*_journal_prefix(db_path), "append", "--stream=" + shlex.quote(stream),
             "--type=" + shlex.quote(event_type)]
    if actor:
        words.append("--actor=" + shlex.quote(actor))
    words.append("--data=" + shlex.quote(json.dumps(data, sort_keys=True)))
    return _printable(" ".join(words))


def _journal_batch(db_path: Path, stream: str, event_type: str, data: Dict[str, Any],
                   actor: str) -> Optional[str]:
    """One ``append --batch`` whose JSONL line sits in a quoted heredoc, so the words a
    model puts into it need no shell quoting. Three lines; the last is the delimiter
    alone, at column 0."""
    head = " ".join([*_journal_prefix(db_path), "append", "--stream=" + shlex.quote(stream),
                     "--actor=" + shlex.quote(actor), "--batch", "<<'EOF'"])
    body = json.dumps({"type": event_type, "data": data}, sort_keys=True,
                      ensure_ascii=False)
    lines = [head, body, "EOF"]
    return "\n".join(lines) if all(line.isprintable() for line in lines) else None


def build_closeout(
    conn: sqlite3.Connection, stream: str, project_dir: Path, db_path: Path,
    ledger: Dict[str, Any], observed: Optional[Path] = None,
    start: Optional[Path] = None,
) -> Dict[str, Any]:
    """The close-out plan of a stream (ADR 0025, ADR 0026 as amended). Writes nothing.

    Without ``observed`` the plan is ``needs-evidence`` and carries the observe script.
    With it, ``merge_evidence`` decides: anything but ``merged`` is ``not-merged`` and
    has no step. ``ready`` lists the steps in ADR 0026's order; a step already done is
    ``skip`` with its reason, so a rerun after a partial failure resumes. The guarded
    deletion of a squash-merged branch is an ``ask`` step whose command runs in the last
    step, after the worktree removal: git refuses to remove a worktree whose branch ref
    is gone (probed, exit 128).
    """
    events = read_events(conn, stream=stream)
    if not events:
        raise InfraError(f"no events for stream {stream!r}")
    folded = fold_stream(events)
    pr = folded["pull_request"] or {}
    forge = forge_from_url(pr.get("url")) or configured_forge(project_dir, start)
    facts = {"stream": stream, "branch": stream, "url": pr.get("url"),
             "project_dir": str(project_dir)}
    report_to = _newest_string(events, "report_to")
    plan: Dict[str, Any] = {
        "stream": stream, "version": folded["version"], "state": "needs-evidence",
        "merge": None, "steps": [], "question": None, "report_to": report_to,
        "observe": None,
        "rerun": _printable(" ".join([
            *_journal_prefix(db_path), "closeout", "--stream=" + shlex.quote(stream),
            "--observed=<the directory it printed>"])),
    }
    if observed is None:
        plan["observe"] = observe_script("closeout", facts, forge)
        return plan
    evidence = read_observed(observed)
    facts["base"] = evidence["base"] or "main"
    merge = merge_evidence(facts, evidence["prs"], evidence["refs"], evidence["merged"],
                           evidence["first_parent"])
    plan["merge"] = merge
    if merge["state"] != "merged":
        plan["state"] = "not-merged"
        return plan
    plan["state"] = "ready"
    refs = evidence["refs"] or {}
    trees = evidence["worktrees"] or []
    main = trees[0]["path"] if trees else str(project_dir)
    base = merge["base"]
    steps: List[CloseoutStep] = []

    def add(kind: str, title: str, command: Optional[str] = None,
            label: Optional[str] = None, bare: bool = False,
            alt: Optional[str] = None, approves: Optional[str] = None) -> None:
        steps.append({"n": len(steps) + 1, "kind": kind, "title": title,
                      "command": command, "label": label, "bare": bare, "alt": alt,
                      "approves": approves})

    # 1. Capture.
    captured = any(e.type == "capture-done" for e in events)
    entries = ledger.get("entries") or 0
    if not captured:
        add("run", "full Capture: the stream has no capture-done — run knowledge-base, "
                   "then append capture-done")
    elif entries:
        add("run", f"residual capture: {entries} untriaged "
                   f"{'entry' if entries == 1 else 'entries'} in {ledger.get('path')} — "
                   "run knowledge-base, then append capture-done")
    else:
        add("skip", "capture: capture-done is recorded and the ledger is empty")
    # 2. flow-completed.
    if folded["terminal"]:
        add("skip", "flow-completed: the stream is already finished")
    else:
        data = {"reason": "merged", "evidence": _clip(merge["detail"])}
        if merge["url"]:
            data["url"] = merge["url"]
        add("run", "flow-completed",
            _journal_append(db_path, stream, "flow-completed", data) or NO_COMMAND,
            bare=True)
    # 3. The integration branch.
    base_tree = next((t["path"] for t in trees if t["branch"] == base), None)
    local_base, origin_base = (refs.get(f"refs/heads/{base}"),
                               refs.get(f"refs/remotes/origin/{base}"))
    if local_base is None:
        add("skip", f"update {base}: no local {base} branch")
    elif local_base == origin_base:
        add("skip", f"update {base}: it is at origin/{base}")
    elif base_tree is not None:
        add("run", f"update {base} where it is checked out, on a clean tree only",
            _printable(f"{_clean(base_tree)} && "
                       + _git(base_tree, "merge", "--ff-only", f"origin/{base}")),
            bare=True)
    else:
        add("run", f"update {base}, which no worktree has checked out",
            _printable(_git(main, "fetch", "origin", f"{base}:{base}")), bare=True)
    # 4. The project's own steps.
    for rule in closeout_rules(project_dir, start):
        add("ask", f"{rule['label']}: {rule['action']}  (Close-out, {rule['source']})",
            label=rule["label"], approves=rule["action"])
    # 5. The worktree removal. Git deletes the worktree's ignored files with it, so
    # with any ignored or untracked path, or files not observed, the removal waits for
    # the question (F60, the user's ruling, ADR 0026 amendment). The option shows the
    # whole last command, the branch deletion included (F63).
    branch = stream
    branch_ref = f"refs/heads/{branch}"
    local = refs.get(branch_ref)
    tree = next((t["path"] for t in trees[1:] if t["branch"] == branch), None)
    in_main = bool(trees) and trees[0]["branch"] == branch
    squash = bool(merge["squash"] and local is not None and merge["head_oid"])
    squash_command = (_printable(_git(main, "update-ref", "-d", branch_ref,
                                      merge["head_oid"])) if squash else None)
    parts: List[str] = []
    if tree is not None:
        parts.append(_git(main, "worktree", "remove", tree))
    elif in_main:
        parts += [_clean(main), _git(main, "switch", base)]
    if local is not None and squash_command is None:
        parts.append(_git(main, "branch", "-d", branch))
    last_command = _printable(" && ".join(parts)) or NO_COMMAND
    files = evidence["worktree_files"]
    remove_step: Optional[int] = None
    if tree is not None and files != []:
        add("ask", f"remove the worktree {tree}: {_held_files(files)}. Run nothing here: "
                   "the last step runs it",
            label=f"Remove worktree {branch}", approves=last_command)
        remove_step = steps[-1]["n"]
    # 6. The squash-merged branch: asked here, run in the last step.
    if squash:
        add("ask", f"delete the squash-merged branch {branch} at the merged commit "
                   f"{merge['head_oid'][:7]} (git calls it unmerged, so branch -d "
                   "refuses it). Run nothing here: the last step runs it, after the "
                   "worktree removal",
            label=f"Delete branch {branch}", approves=squash_command or NO_COMMAND)
        squash_step = steps[-1]["n"]
    # 7. The report (F64: one statement either way).
    goes = (f"the worktree and the branch go next only if the user chose step "
            f"{remove_step}; else name the worktree {tree} and the branch {branch} as kept"
            if remove_step else "the worktree and the branch go next")
    add("run", f"report to {report_to or 'the user'}: {stream} closed — "
               f"{merge['detail']}; {goes}")
    # 8. Last, one Bash call.
    if local is None and tree is None:
        add("skip", "last: the branch and its worktree are gone")
    else:
        alt = None
        if squash_command is not None:
            chosen = " and ".join(str(n) for n in (remove_step, squash_step) if n)
            alt = f"when the user chose step{'s' if remove_step else ''} {chosen}: " + (
                _printable(" && ".join(parts + [squash_command])) or NO_COMMAND)
        title = "last, one Bash call" + (
            f", only when the user chose step {remove_step}" if remove_step else "")
        if parts:
            add("run", title, last_command, alt=alt)
        else:
            add("skip", "last: no worktree to remove and no branch left to delete "
                        "unless the user chose the squash step", alt=alt)
    plan["steps"] = steps
    asks = [step for step in steps if step["kind"] == "ask"]
    if asks:
        plan["question"] = {
            "options": [{"label": _option_label(step["label"] or step["title"], step["n"]),
                         "command": step["approves"] or NO_COMMAND} for step in asks],
            "record": _journal_batch(db_path, stream, "gate-decision", {
                "gate": "close-out", "question": CLOSEOUT_QUESTION_PLACEHOLDER,
                "decision": CLOSEOUT_CHOSEN_PLACEHOLDER, "mode": "ask",
                "raised_by": "user"}, actor="user") or NO_COMMAND,
        }
    return plan


def render_closeout(plan: Dict[str, Any]) -> str:
    """The plan as text for a model. Values are collapsed to one line; commands print
    whole, never clipped."""
    lines = [f"shipgate close-out — {_one_line(plan['stream'])}  (v{plan['version']})"]
    if plan["state"] == "needs-evidence":
        lines += [
            "merge        : not observed yet. Run this script in one Bash call; it writes "
            "the evidence into a fresh directory and prints it:",
            *("  " + line for line in plan["observe"].splitlines()),
            "then run     : " + (plan["rerun"] or NO_COMMAND),
            "The user's word is not evidence: the plan reads only the forge and git.",
        ]
        return "\n".join(lines)
    merge = plan["merge"]
    if plan["state"] == "not-merged":
        lines.append(
            f"merge        : not merged ({_one_line(merge['detail'])}) — nothing to close: "
            "no step runs, nothing is appended or removed.")
        return "\n".join(lines)
    lines.append(f"merge        : merged ({_one_line(merge['detail'])})")
    question = plan["question"]
    if question:
        options = "; ".join(f'"{_one_line(option["label"])}" runs: {option["command"]}'
                            for option in question["options"])
        lines.append(
            f'ask once     : AskUserQuestion, header "{CLOSEOUT_HEADER}", multi-select, '
            "one option per [ask] step, its command as the option's description "
            f"({options}); then record the answer: put the question and the chosen steps "
            "in place of the two placeholders and run these three lines in one Bash call:")
        # At column 0: the heredoc's delimiter line must stay as it is printed.
        lines += question["record"].splitlines()
    for step in plan["steps"]:
        head = f"  {step['n']}. [{step['kind']}] "
        if step["command"] and step["bare"]:
            lines.append(head + step["command"])
        elif step["command"]:
            lines.append(head + _one_line(step["title"]) + ": " + step["command"])
        else:
            lines.append(head + _one_line(step["title"]))
        if step["alt"]:
            lines.append("       " + step["alt"])
    lines.append(CLOSEOUT_RULE_LINE)
    return "\n".join(lines)


# ``gone`` is no branch and no PR/MR of the stream's name: the user decides (the
# user's round-4 ruling). ``unknown`` and ``keep`` append nothing.
_SWEEP_DISPOSITION = {"merged": ("flow-completed", "merged"),
                      "closed": ("flow-abandoned", "closed unmerged"),
                      "gone": ("unknown", None)}


def observed_at(directory: Path) -> datetime:
    """When the evidence was observed: the newest mtime of its files, else now."""
    stamps = []
    for name in OBSERVED_FILES.values():
        try:
            stamps.append((directory / name).stat().st_mtime)
        except OSError:
            continue
    if not stamps:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(max(stamps), tz=timezone.utc)


def _forge_of_dormant_urls(conn: sqlite3.Connection) -> Optional[str]:
    """The forge CLI most dormant streams' ``mr-opened`` URLs name, or None."""
    counts: Dict[str, int] = {}
    for stream in list_streams(conn):
        if not is_work_stream(stream):
            continue
        events = read_events(conn, stream=stream)
        if not events:
            continue
        folded = fold_stream(events)
        forge = forge_from_url((folded["pull_request"] or {}).get("url"))
        if folded["dormant"] and forge is not None:
            counts[forge] = counts.get(forge, 0) + 1
    return max(counts, key=lambda name: counts[name]) if counts else None


def build_sweep(conn: sqlite3.Connection, project_dir: Path, db_path: Path,
                observed: Optional[Path] = None,
                start: Optional[Path] = None) -> Dict[str, Any]:
    """A disposition for each dormant stream (ADR 0025, FR-018). Writes nothing.

    Dormant is judged at the time the evidence was observed, so the proposal and
    ``--apply`` see the same streams. ``merged`` proposes ``flow-completed`` and
    ``closed`` ``flow-abandoned``; ``gone`` (no branch and no PR/MR of the stream's
    name) is ``unknown`` for the user to decide; anything else is ``keep``. A stream
    with an event after the observation ``moved``.
    """
    forge = configured_forge(project_dir, start) or _forge_of_dormant_urls(conn)
    plan: Dict[str, Any] = {"state": "needs-evidence", "proposals": [], "observe": None,
                            "observed": str(observed) if observed else None,
                            "prefix": " ".join(_journal_prefix(db_path))}
    if observed is None:
        plan["observe"] = observe_script("sweep", {"project_dir": str(project_dir)}, forge)
        return plan
    plan["state"] = "ready"
    at = observed_at(observed)
    evidence = read_observed(observed)
    base = evidence["base"] or "main"
    for stream in list_streams(conn):
        if not is_work_stream(stream):
            continue
        events = read_events(conn, stream=stream)
        if not events:
            continue
        observed_fold = fold_stream(
            [e for e in events if (_parse_ts(e.ts) or at) <= at], now=at)
        if not observed_fold["dormant"]:
            continue
        pr = observed_fold["pull_request"] or {}
        facts = {"stream": stream, "branch": stream, "base": base, "url": pr.get("url")}
        merge = merge_evidence(facts, evidence["prs"], evidence["refs"], evidence["merged"],
                               evidence["first_parent"], sweep=True)
        event_type, reason = _SWEEP_DISPOSITION.get(merge["state"], ("keep", None))
        plan["proposals"].append({
            "stream": stream, "disposition": event_type, "reason": reason,
            "idle_days": observed_fold["age_days"], "merge": merge,
            "version": observed_fold["version"],
            "moved": len(events) > len([e for e in events
                                        if (_parse_ts(e.ts) or at) <= at]),
        })
    return plan


def render_sweep(plan: Dict[str, Any]) -> str:
    if plan["state"] == "needs-evidence":
        return "\n".join([
            "shipgate sweep — the dormant streams",
            "evidence     : not observed yet. Run this script in one Bash call; it runs "
            "one forge list query and prints the directory it filled:",
            *("  " + line for line in plan["observe"].splitlines()),
            f"then run     : {plan['prefix']} sweep --observed=<the directory it printed>",
        ])
    proposals = plan["proposals"]
    if not proposals:
        return "shipgate sweep — no dormant streams"
    lines = ["shipgate sweep — the dormant streams"]
    for p in proposals:
        lines.append(
            f"  {p['disposition']:<15} {_one_line(p['stream'])}  dormant {p['idle_days']}d  "
            + _one_line(p["merge"]["detail"])
            + ("  (moved after the evidence was observed)" if p["moved"] else ""))
    counts = {kind: sum(p["disposition"] == kind for p in proposals)
              for kind in ("flow-completed", "flow-abandoned", "unknown", "keep")}
    apply = _printable(f"{plan['prefix']} sweep "
                       f"--observed={shlex.quote(plan['observed'])} --apply") or NO_COMMAND
    lines.append(
        f"proposed: {counts['flow-completed']} flow-completed, "
        f"{counts['flow-abandoned']} flow-abandoned, {counts['unknown']} unknown (you "
        f"decide; --apply appends nothing for them), {counts['keep']} keep — after one "
        f"confirmation: {apply}")
    return "\n".join(lines)


def apply_sweep(conn: sqlite3.Connection, plan: Dict[str, Any],
                project_dir: Path) -> List[str]:
    """Append the proposed terminal events (FR-020); git is never touched. A stream
    that moved after the observation, or while this runs, is skipped and named."""
    out: List[str] = []
    for p in plan["proposals"]:
        stream = _one_line(p["stream"])
        if p["disposition"] in ("keep", "unknown"):
            continue
        if p["moved"]:
            out.append(f"skipped {stream}: it moved after the evidence was observed")
            continue
        data = {"reason": p["reason"], "evidence": _clip(p["merge"]["detail"])}
        if p["merge"]["url"]:
            data["url"] = p["merge"]["url"]
        try:
            result = append_event(conn, p["stream"], p["disposition"], data, project_dir,
                                  expect=p["version"])
        except (VersionConflict, GateViolation) as error:
            out.append(f"skipped {stream}: {_one_line(error)}")
            continue
        out.append(f"appended {p['disposition']} to {stream} (seq {result.seq})")
    return out or ["nothing to append"]
