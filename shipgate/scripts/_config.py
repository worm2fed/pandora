"""shipgate config reader — the one walk over `.claude/shipgate.md` and its layers.

Private to the scripts: ``signals.py``, ``journal.py`` and ``lean_config.py`` load it by
path, because ``scripts/`` is not a package. ``lean_config.py`` keeps its own block
parser and uses only the placeholder test (``is_placeholder_value``). Python 3 standard
library only. See ADR 0018.

A config is a stack of files, nearest first: the repo's `.claude/shipgate.md` files
(from the start directory up to the repo root), the umbrella's, then the user file
(``$CLAUDE_CONFIG_DIR/shipgate.md``, else ``~/.claude/shipgate.md``). Each ``##``
section comes whole from the nearest file that holds it with a value that is not an
angle-bracket placeholder; sections never merge line by line. ``Inherit: none`` before
the first section heading of the nearest project-side file drops the umbrella's files.

The callers build the candidate list (only ``signals.py`` knows how to find an
umbrella); this module reads, filters and resolves it. Nothing here writes or exits.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Sequence, Tuple

CONFIG_RELPATH = os.path.join(".claude", "shipgate.md")
USER_CONFIG_NAME = "shipgate.md"
KNOWLEDGE_SECTION = "knowledge base"

ROLE_PROJECT = "project"
ROLE_UMBRELLA = "umbrella"
ROLE_USER = "user"

INHERIT_UMBRELLA = "umbrella"
INHERIT_NONE = "none"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+([^:]+?)\s*:\s*(.*)$")
# A title-level `Key: value` line without a bullet marker; it starts at column 0 so
# that an indented line stays a continuation of the bullet above it.
_BARE_RE = re.compile(r"^([A-Za-z][\w-]*(?: [\w-]+){0,3})\s*:\s*(.*)$")
BACKTICK_RE = re.compile(r"`([^`]*)`")
_BACKTICK_RE = BACKTICK_RE
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# CommonMark: a backtick fence's info string holds no backtick (else it is inline
# code); a closing fence is the bare marker. Indentation is checked by the caller.
_FENCE_OPEN_RE = re.compile(r"^(\s*)(`{3,}(?!.*`)|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*$")


# The text between two top-level `<…>` groups of one placeholder: whitespace, with an
# optional separator and an optional `Label:` of one to four words
# (`<GitHub | GitLab | …> — CLI: <gh | glab | …>`).
_GAP_RE = re.compile(r"^\s*(?:[—–\-|,]\s*)?(?:[A-Za-z][\w-]*(?: [\w-]+){0,3}:\s)?\s*$")
_URI_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*://|mailto:)", re.IGNORECASE)


def _angle_groups(value: str) -> Optional[List[Tuple[int, int]]]:
    """The `(start, end)` index of each top-level `<…>` group, nesting counted; None
    when a bracket is unbalanced."""
    groups: List[Tuple[int, int]] = []
    depth = 0
    start = 0
    for index, char in enumerate(value):
        if char == "<":
            if depth == 0:
                start = index
            depth += 1
        elif char == ">":
            if depth == 0:
                return None
            depth -= 1
            if depth == 0:
                groups.append((start, index))
    return groups if depth == 0 else None


def is_placeholder_value(value: str) -> bool:
    """True when VALUE, stripped and with one pair of surrounding backticks removed, is
    an angle-bracket placeholder: one or more balanced top-level `<…>` groups joined
    by whitespace (optionally with a separator or a `Label:`). An empty value is not a
    placeholder here. Joined without whitespace (`<type>/<slug>`), joined by `:` alone
    (`<type>: <summary>`), or holding a URI (`<https://…>`, `<mailto:…>`) or an `@`
    (`<@alice>`), it is a real value. The one placeholder rule every script uses."""
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        value = value[1:-1].strip()
    if not (value.startswith("<") and value.endswith(">")):
        return False
    groups = _angle_groups(value)
    if not groups:
        return False
    for start, end in groups:
        inner = value[start + 1:end]
        if _URI_RE.match(inner) or "@" in inner:
            return False
    for (_, end), (start, _) in zip(groups, groups[1:]):
        gap = value[end + 1:start]
        if not re.search(r"\s", gap) or not _GAP_RE.match(gap):
            return False
    return True


def is_placeholder(value: str) -> bool:
    """Empty, or an angle-bracket placeholder (`is_placeholder_value`)."""
    return not value.strip() or is_placeholder_value(value)


_is_angle_placeholder = is_placeholder_value


def section_bullets(text: str, section: str) -> List[Tuple[str, str]]:
    """The `- Key: value` bullets of one `## <section>` (lower-case name), in order.

    Keys come back lower-cased; a wrapped continuation line joins its bullet. HTML
    comments and fenced code are inert. The one walk every config reader uses.
    """
    text = _COMMENT_RE.sub("", text)
    in_section = False
    section_level = 0
    bullets: List[Tuple[str, str]] = []
    fence: Optional[str] = None  # the open fence's marker; its lines are inert
    for raw in text.splitlines():
        # Inside the section any indentation counts (a fence nested in a bullet).
        indent_ok = (lambda m: in_section or len(m.group(1)) <= 3)
        if fence is not None:
            close = _FENCE_CLOSE_RE.match(raw)
            if close and indent_ok(close) and close.group(2)[0] == fence[0] and \
                    len(close.group(2)) >= len(fence):
                fence = None
            continue
        opening = _FENCE_OPEN_RE.match(raw)
        if opening and indent_ok(opening):
            fence = opening.group(2)
            continue
        heading = _HEADING_RE.match(raw)
        if heading:
            level = len(heading.group(1))
            if in_section and level <= section_level:
                break
            if heading.group(2).strip().lower() == section:
                in_section = True
                section_level = level
            continue
        if not in_section:
            continue
        bullet = _BULLET_RE.match(raw)
        if bullet:
            bullets.append((bullet.group(1).strip().lower(), bullet.group(2)))
        elif bullets and raw[:1].isspace() and raw.strip():
            key, value = bullets[-1]
            bullets[-1] = (key, value + " " + raw.strip())  # wrapped continuation
    return bullets


def title_bullets(text: str) -> List[Tuple[str, str]]:
    """The `Key: value` lines before the first heading of level 2 or deeper, in order.

    A line counts as a bullet (`- Key: value`, any indent) or bare (`Key: value` at
    column 0). Level-1 title lines are skipped. Keys come back lower-cased. HTML
    comments and fenced code (at any indent) are inert; a wrapped continuation line
    joins its bullet.
    """
    text = _COMMENT_RE.sub("", text)
    bullets: List[Tuple[str, str]] = []
    fence: Optional[str] = None
    for raw in text.splitlines():
        if fence is not None:
            close = _FENCE_CLOSE_RE.match(raw)
            if close and close.group(2)[0] == fence[0] and len(close.group(2)) >= len(fence):
                fence = None
            continue
        opening = _FENCE_OPEN_RE.match(raw)
        if opening:
            fence = opening.group(2)
            continue
        heading = _HEADING_RE.match(raw)
        if heading:
            if len(heading.group(1)) >= 2:
                break
            continue
        line = _BULLET_RE.match(raw) or _BARE_RE.match(raw)
        if line:
            bullets.append((line.group(1).strip().lower(), line.group(2)))
        elif bullets and raw[:1].isspace() and raw.strip():
            key, value = bullets[-1]
            bullets[-1] = (key, value + " " + raw.strip())
    return bullets


def inherit_mode(text: str) -> str:
    """`none` when the title block says `Inherit: none` (backticks optional, any
    case, Markdown emphasis ignored, trailing text ignored), else `umbrella`. The first
    `Inherit` line decides, by the first word of its value."""
    for key, value in title_bullets(text):
        if key == "inherit":
            word = re.match(r"\s*([a-z]*)", re.sub(r"[`*_]", "", value).lower())
            first = word.group(1) if word else ""
            return INHERIT_NONE if first == INHERIT_NONE else INHERIT_UMBRELLA
    return INHERIT_UMBRELLA


def _value_present(value: str) -> bool:
    # A whole value in angle brackets is a placeholder, backticks inside or not
    # (the template's `<path, e.g. `docs/prd/` or a wiki path>`).
    if is_placeholder_value(value):
        return False
    spans = BACKTICK_RE.findall(value)
    if spans:
        # An empty span is a deliberate empty value (`Ranking exclude: ``` turns
        # the built-in list off), so only an angle-bracket span is a placeholder.
        return any(not is_placeholder_value(span) for span in spans)
    return not is_placeholder(value)


def section_present(text: str, section: str) -> bool:
    """True when `## <section>` holds at least one bullet whose value is not a
    placeholder (FR-002). Placeholders only, or no bullets, is absent."""
    return any(_value_present(value) for _, value in section_bullets(text, section))


def bullet_value(value: str) -> Optional[str]:
    """The first backticked span, else the bare value, stripped; None for a
    placeholder or an empty value. A whole value in angle brackets is a placeholder
    even when it holds backticks."""
    if is_placeholder(value):
        return None
    spans = BACKTICK_RE.findall(value)
    found = spans[0].strip() if spans else value.strip()
    return None if is_placeholder(found) else found


def user_config_path() -> Optional[Path]:
    """`$CLAUDE_CONFIG_DIR/shipgate.md` when the variable is set and not empty, else
    `~/.claude/shipgate.md`; None when the home directory cannot be found. A set
    variable replaces the directory: there is no fallback to the home directory."""
    directory = os.environ.get("CLAUDE_CONFIG_DIR")
    if directory:
        return Path(directory).expanduser() / USER_CONFIG_NAME
    try:
        home = Path.home()
    except (RuntimeError, KeyError):
        return None
    return home / ".claude" / USER_CONFIG_NAME


class ConfigFile(NamedTuple):
    path: Path
    role: str  # project | umbrella | user
    text: str


def _read(path: Path) -> Optional[str]:
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return path


def read_layers(candidates: Sequence[Tuple[Path, str]],
                user_path: Optional[Path]) -> List[ConfigFile]:
    """The config files that exist, in precedence order (nearest first, the user file
    last), each read once.

    CANDIDATES are `(path, role)` pairs, nearest first, with role `project` or
    `umbrella`. Duplicates by resolved path keep the first occurrence, so a user file
    that is also an umbrella candidate reads as an umbrella file. Then `Inherit: none`
    in the nearest project-side file (a `project` file, else the nearest `umbrella`
    one) drops every other `umbrella` file.
    """
    pairs = list(candidates)
    if user_path is not None:
        pairs.append((user_path, ROLE_USER))
    files: List[ConfigFile] = []
    seen = set()
    for path, role in pairs:
        key = _resolved(path)
        if key in seen:
            continue
        text = _read(path)
        if text is None:
            continue
        seen.add(key)
        files.append(ConfigFile(path, role, text))
    decider = nearest_project_side(files)
    if decider is not None and inherit_mode(decider.text) == INHERIT_NONE:
        files = [f for f in files if f.role != ROLE_UMBRELLA or f is decider]
    return files


def nearest_project_side(files: Sequence[ConfigFile]) -> Optional[ConfigFile]:
    """The nearest `project` file, else the nearest `umbrella` one, else None."""
    for role in (ROLE_PROJECT, ROLE_UMBRELLA):
        for config in files:
            if config.role == role:
                return config
    return None


def section_owner(files: Sequence[ConfigFile], section: str,
                  present: Optional[Callable[[str], bool]] = None
                  ) -> Optional[ConfigFile]:
    """The first file in FILES whose `## <section>` is present, else None. PRESENT,
    given a file's text, replaces the general rule (`section_present`) for a section
    with a stricter one."""
    for config in files:
        if (present(config.text) if present is not None
                else section_present(config.text, section)):
            return config
    return None
