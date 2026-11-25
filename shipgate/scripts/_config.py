"""shipgate config reader — the one walk over `.claude/shipgate.md` and its layers.

Private to the scripts: ``signals.py``, ``journal.py`` and ``lean_config.py`` load it by
path, because ``scripts/`` is not a package. ``lean_config.py`` keeps its own block
parser. It uses the placeholder test (``is_placeholder_value``), and its
``--move-settings`` mode uses the legacy reader and the resolver. Python 3 standard
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

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import (
    Any, Callable, Dict, Iterator, List, NamedTuple, Optional, Sequence, Tuple,
)

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


def _walk_section(text: str, section: str) -> Iterator[Tuple[str, bool]]:
    """Yield `(line, fenced)` for each line of one `## <section>` (lower-case name): the
    one walk every config reader uses.

    HTML comments are removed first. A fence opens outside the section only at an indent
    of three spaces or less (CommonMark); inside it, at any indent (a fence nested in a
    bullet). A fence's marker lines and its content come back with `fenced` True, and a
    heading inside a fence does not end the section. The section ends at the next
    heading of its level or higher; a deeper heading comes back as a line, except one
    that repeats the section's name, which narrows the section to itself.
    """
    text = _COMMENT_RE.sub("", text)
    in_section = False
    section_level = 0
    fence: Optional[str] = None  # the open fence's marker
    for raw in text.splitlines():
        indent_ok = (lambda m: in_section or len(m.group(1)) <= 3)
        if fence is not None:
            close = _FENCE_CLOSE_RE.match(raw)
            if close and indent_ok(close) and close.group(2)[0] == fence[0] and \
                    len(close.group(2)) >= len(fence):
                fence = None
            if in_section:
                yield raw, True
            continue
        opening = _FENCE_OPEN_RE.match(raw)
        if opening and indent_ok(opening):
            fence = opening.group(2)
            if in_section:
                yield raw, True
            continue
        heading = _HEADING_RE.match(raw)
        if heading:
            level = len(heading.group(1))
            if in_section and level <= section_level:
                return
            if heading.group(2).strip().lower() == section:
                # A deeper heading that repeats the name narrows the section to it.
                in_section = True
                section_level = level
                continue
            if not in_section:
                continue
        if in_section:
            yield raw, False


def section_bullets(text: str, section: str,
                    keep_case: bool = False) -> List[Tuple[str, str]]:
    """The `- Key: value` bullets of one `## <section>` (lower-case name), in order.

    Keys come back lower-cased, or as written with `keep_case`; a wrapped continuation
    line joins its bullet. HTML comments and fenced code are inert (`_walk_section`).
    """
    bullets: List[Tuple[str, str]] = []
    for raw, fenced in _walk_section(text, section):
        if fenced:
            continue
        bullet = _BULLET_RE.match(raw)
        if bullet:
            key = bullet.group(1).strip()
            bullets.append((key if keep_case else key.lower(), bullet.group(2)))
        elif bullets and raw[:1].isspace() and raw.strip():
            key, value = bullets[-1]
            bullets[-1] = (key, value + " " + raw.strip())  # wrapped continuation
    return bullets


_LIST_MARKER_RE = re.compile(r"^\s*[-*+]\s+")
_KEY_VALUE_RE = re.compile(r"^([^:]+?)\s*:\s*(.*)$")


def _placeholder_item(item: str) -> bool:
    """True when one list item or paragraph line (marker stripped, continuation lines
    joined) is a placeholder: wholly `<…>`, or `Key: <…>`. A `Key:` with no value is
    text (a lead-in to the bullets under it), not a placeholder."""
    if is_placeholder_value(item):
        return True
    key_value = _KEY_VALUE_RE.match(item)
    if key_value is None or not key_value.group(2).strip():
        return False
    return not _value_present(key_value.group(2))


def section_lines(text: str, section: str) -> List[str]:
    """The lines of one `## <section>` (lower-case name), as written, for quoting.

    The same walk as `section_bullets` (`_walk_section`). Blank lines are dropped. An
    item whose text is a placeholder (`- <domains, e.g. billing>`, `- Mode: <ask |
    executive>`) is dropped with its continuation lines. Fenced code is kept as written.
    [] when the section is absent or holds only placeholders. Unlike `section_bullets`,
    a bullet need not be `Key: value`, so a prose section (Security-sensitive areas)
    reads whole.
    """
    items: List[List[Tuple[str, bool]]] = []  # each item's lines, with `fenced`
    in_fence = False
    for raw, fenced in _walk_section(text, section):
        if fenced:
            # An indented fence belongs to the item above it, and drops with it.
            if in_fence or (items and raw[:1].isspace()):
                items[-1].append((raw, True))
            else:
                items.append([(raw, True)])
            in_fence = True
            continue
        in_fence = False
        if not raw.strip():
            continue
        if items and raw[:1].isspace() and not _LIST_MARKER_RE.match(raw):
            items[-1].append((raw, False))  # a wrapped continuation of the item above
        else:
            items.append([(raw, False)])
    lines: List[str] = []
    for item in items:
        text_lines = [line for line, fenced in item if not fenced]
        # An item that is only a fence is code, never a placeholder.
        if text_lines and _placeholder_item(" ".join(
            [_LIST_MARKER_RE.sub("", text_lines[0], count=1).strip()]
            + [line.strip() for line in text_lines[1:]]
        )):
            continue
        lines.extend(line.rstrip() for line, _fenced in item)
    return lines


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
                user_path: Optional[Path],
                read: Optional[Callable[[Path], Optional[str]]] = None
                ) -> List[ConfigFile]:
    """The config files that exist, in precedence order (nearest first, the user file
    last), each read once.

    CANDIDATES are `(path, role)` pairs, nearest first, with role `project` or
    `umbrella`. Duplicates by resolved path keep the first occurrence, so a user file
    that is also an umbrella candidate reads as an umbrella file. Then `Inherit: none`
    in the nearest project-side file (a `project` file, else the nearest `umbrella`
    one) drops every other `umbrella` file. READ, given a path, returns its text or
    None for a file that does not exist; the default reads the disk. A caller that
    resolves a planned state (`lean_config.py --move-settings`) passes its own.
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
        text = (read or _read)(path)
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


# Where an umbrella checkout holds its nested repos: `hooks/session_start.py`
# (NESTED_REPO_PARENTS, NESTED_ENTRY_LIMIT, NESTED_REPO_LIMIT) scans the same places
# with the same bounds.
NESTED_REPO_PARENTS = ("", "source", "packages")
NESTED_ENTRY_LIMIT = 512
NESTED_REPO_LIMIT = 64


def _child_repo_dirs(base: Path) -> List[Path]:
    """The real child directories of BASE that hold a `.git` entry of their own (a
    directory or a `gitdir:` file, never a symlink), sorted. Dot-names, `node_modules`
    and symlinks are left out, and at most NESTED_ENTRY_LIMIT entries are examined. []
    when BASE is a symlink or cannot be read."""
    if os.path.islink(str(base)):
        return []
    try:
        with os.scandir(str(base)) as entries:
            names = []
            for index, entry in enumerate(entries):
                if index >= NESTED_ENTRY_LIMIT:
                    break
                if entry.name.startswith(".") or entry.name == "node_modules":
                    continue
                if entry.is_dir(follow_symlinks=False):
                    names.append(entry.name)
    except OSError:
        return []
    out = []
    for name in sorted(names):
        git = os.path.join(str(base), name, ".git")
        if os.path.lexists(git) and not os.path.islink(git):
            out.append(base / name)
    return out


def nested_repo_dirs(root: Path) -> List[Path]:
    """The nested repos of the project at ROOT: each child directory of ROOT,
    `ROOT/source` and `ROOT/packages` with a `.git` entry of its own, in that order and
    sorted within each place, at most NESTED_REPO_LIMIT in all. Dot-directories,
    `node_modules` and symlinks are left out. It never raises."""
    found: List[Path] = []
    for parent in NESTED_REPO_PARENTS:
        for repo in _child_repo_dirs(root / parent if parent else root):
            if repo not in found:
                found.append(repo)
            if len(found) >= NESTED_REPO_LIMIT:
                return found
    return found


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


# --------------------------------------------------------------------------
# Settings (ADR 0028): the settings files, the schema and the per-key resolver
# --------------------------------------------------------------------------

SETTINGS_RELPATH = os.path.join(".claude", "shipgate.json")
# The user settings file. No walk for `.claude/shipgate.json` finds this name, so it
# never marks a project as journaled (PRD FR-004).
USER_SETTINGS_NAME = "shipgate.settings.json"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "settings.schema.json"

SOURCE_PROJECT = "project"
SOURCE_USER = "user"
# A setting's `x-scope`: `project` keys come from the project settings file only.
SCOPE_PROJECT = "project"
SCOPE_ANY = "any"
SOURCE_LEGACY = "legacy"
SOURCE_DEFAULT = "default"

# Problem kinds. `bad-value`, `not-json` and `bad-legacy` carry the key's file; the
# first two stop a strict reader (`Resolved.require`), the others are warnings.
BAD_VALUE = "bad-value"
BAD_LEGACY = "bad-legacy"
UNKNOWN_KEY = "unknown-key"
SCOPE = "scope"
NEWER_VERSION = "version"
NOT_JSON = "not-json"

EXIT_INFRA = 1
EXIT_USAGE = 2


def user_settings_path() -> Optional[Path]:
    """`$CLAUDE_CONFIG_DIR/shipgate.settings.json` when the variable is set and not
    empty, else `~/.claude/shipgate.settings.json`; None when the home directory cannot
    be found. The rule of `user_config_path`."""
    config = user_config_path()
    return None if config is None else config.with_name(USER_SETTINGS_NAME)


_SCHEMA_CACHE: List[Dict[str, Any]] = []


def load_schema() -> Dict[str, Any]:
    """`settings.schema.json`, parsed once per process. The plugin ships it beside
    `scripts/`; a missing or broken file is an incomplete install, so this raises
    OSError. Callers read the result and never change it."""
    if _SCHEMA_CACHE:
        return _SCHEMA_CACHE[0]
    with open(SCHEMA_PATH, encoding="utf-8") as handle:
        try:
            schema = json.load(handle)
        except ValueError as exc:
            schema = exc
    if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
        # An OSError, so every caller's install-error path reports it (exit 1).
        detail = f": {schema}" if isinstance(schema, ValueError) else ""
        raise OSError(f"{SCHEMA_PATH} is not a settings schema (shipgate install "
                      f"incomplete){detail}")
    _SCHEMA_CACHE.append(schema)
    return schema


class Problem(NamedTuple):
    kind: str  # bad-value | bad-legacy | unknown-key | scope | version | not-json
    path: str  # the file that holds it
    key: Optional[str]  # `group.leaf`, a group, a top-level key; None for the file
    value: Any
    message: str  # one line: the file, the key, the value and what is allowed


class Setting(NamedTuple):
    value: Any
    source: str  # project | user | legacy | default
    path: Optional[str]  # the file; None for a default
    section: Optional[str] = None  # the config section of a legacy value
    # Why a strict reader refuses this value: a value outside its set in the settings
    # file that decided the key (the value is then the default), or a settings file the
    # walk reached that cannot be read (the walk skipped it). None when it is sound.
    problem: Optional["Problem"] = None


class LegacyLine(NamedTuple):
    path: str
    section: str
    bullet: str
    key: str
    value: str  # as written


class SettingsError(Exception):
    """A strict reader's refusal: exit 2 for a value outside its set, 1 for a settings
    file that cannot be read as a JSON object."""

    def __init__(self, problem: Problem) -> None:
        super().__init__(problem.message)
        self.problem = problem
        self.exit_code = EXIT_INFRA if problem.kind == NOT_JSON else EXIT_USAGE


class Resolved(NamedTuple):
    settings: Dict[str, Setting]  # every leaf key, schema order
    problems: List[Problem]
    legacy: List[LegacyLine]  # every legacy line the layers hold
    legacy_until: Optional[str]  # the schema's grace date
    legacy_ended: bool  # the grace date is in the past

    def get(self, key: str) -> Setting:
        return self.settings[key]

    def keys(self, key: str) -> List[str]:
        """The leaf keys KEY names: itself, or each leaf of a group. KeyError for a
        key the schema and the files do not hold."""
        if key in self.settings:
            return [key]
        leaves = [k for k in self.settings if k.startswith(key + ".")]
        if not leaves:
            raise KeyError(key)
        return leaves

    def value(self, key: str) -> Any:
        """The value of a leaf, or a dict of the leaves of a group. The default on a
        problem: the hook-path rule (PRD FR-006)."""
        leaves = self.keys(key)
        if leaves == [key]:
            return self.settings[key].value
        return {k[len(key) + 1:]: self.settings[k].value for k in leaves}

    def require(self, key: str) -> Any:
        """``value(key)``, or SettingsError when a leaf of KEY carries a problem: a
        value outside its set in the settings file that decided it (exit 2), or a
        settings file that the walk reached and could not read (exit 1). A value
        outside its set wins over a file that cannot be read. An extra kind of a group
        (`artifact_homes.design`) with a value outside its set is refused with its group.
        """
        leaves = self.keys(key)
        found = [self.settings[leaf].problem for leaf in leaves
                 if self.settings[leaf].problem is not None]
        groups = {leaf.split(".", 1)[0] for leaf in leaves}
        found += [p for p in self.problems
                  if p.kind == BAD_VALUE and p.key is not None and "." in p.key
                  and p.key not in self.settings and p.key.split(".", 1)[0] in groups]
        for problem in sorted(found, key=lambda p: p.kind != BAD_VALUE):
            raise SettingsError(problem)
        return self.value(key)


def _json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _is_int(value: Any) -> bool:
    # `bool` is an `int` in Python, and `true` is no count.
    return isinstance(value, int) and not isinstance(value, bool)


_TYPE_CHECKS: Dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": _is_int,
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _valid(value: Any, node: Dict[str, Any]) -> bool:
    """VALUE against the schema subset the settings use: type, enum, minimum,
    maximum, minLength, pattern, items, minItems, anyOf and `x-format: regex`."""
    if "anyOf" in node:
        return any(_valid(value, option) for option in node["anyOf"])
    if "enum" in node and value not in node["enum"]:
        return False
    types = node.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else list(types)
        if not any(_TYPE_CHECKS[t](value) for t in types):
            return False
    if _is_int(value):
        if "minimum" in node and value < node["minimum"]:
            return False
        if "maximum" in node and value > node["maximum"]:
            return False
    if isinstance(value, str):
        if len(value) < node.get("minLength", 0):
            return False
        if "pattern" in node and not _matches(node["pattern"], value):
            return False
        if node.get("x-format") == "regex":
            try:
                re.compile(value)
            except re.error:
                return False
    if isinstance(value, list):
        if len(value) < node.get("minItems", 0):
            return False
        if "items" in node:
            return all(_valid(item, node["items"]) for item in value)
    return True


def _matches(pattern: str, value: str) -> bool:
    """`pattern` as JSON Schema reads it (ECMA-262): a `$` at the end matches only at
    the end of the value. Python's `$` also matches before a final line break."""
    match = re.search(pattern, value)
    if match is None:
        return False
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        return match.end() == len(value)
    return True


def _allowed(node: Dict[str, Any]) -> str:
    """What NODE allows, in words, for a refusal."""
    if "x-allowed" in node:
        return str(node["x-allowed"])
    if "anyOf" in node:
        return " or ".join(_allowed(option) for option in node["anyOf"])
    if "enum" in node:
        return ", ".join(v if isinstance(v, str) else _json_text(v) for v in node["enum"])
    types = node.get("type")
    types = [types] if isinstance(types, str) else list(types or [])
    words = []
    for kind in types:
        if kind == "integer":
            low, high = node.get("minimum"), node.get("maximum")
            if low is not None and high is not None:
                words.append(f"an integer from {low} to {high}")
            elif low is not None:
                words.append(f"an integer of {low} or more")
            else:
                words.append("an integer")
        elif kind == "string":
            if node.get("x-format") == "regex":
                words.append("a valid regex")
            elif "pattern" in node:
                words.append(f"a string that matches {node['pattern']}")
            else:
                words.append("a non-empty string")
        elif kind == "array":
            words.append("a list of non-empty strings")
        elif kind == "boolean":
            words.append("true or false")
        elif kind == "object":
            words.append("an object")
        elif kind == "null":
            words.append("null")
    return " or ".join(words) or "a valid value"


def _bad_value(path: str, key: str, value: Any, node: Dict[str, Any],
               kind: str = BAD_VALUE, where: str = "") -> Problem:
    # A key can carry a name from the file (an extra artifact kind): JSON-encode one
    # that is no plain name, so the message stays on one line.
    shown = key if re.fullmatch(r"[\w.-]+", key) else _json_text(key)
    return Problem(kind, path, key, value,
                   f"{path}{where}: {shown} = {_json_text(value)} is not one of: "
                   f"{_allowed(node)}")


def _read_settings_file(path: Optional[Path],
                        problems: List[Problem]) -> Optional[Dict[str, Any]]:
    """The JSON object of one settings file; None when it is absent or unreadable (a
    `not-json` problem for one that exists but is no JSON object)."""
    if path is None:
        return None
    try:
        if not path.is_file():
            return None
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    except ValueError as exc:  # UnicodeDecodeError
        problems.append(Problem(NOT_JSON, str(path), None, None,
                                f"{path} is not valid UTF-8: {exc}"))
        return None
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError) as exc:  # RecursionError: nesting too deep
        problems.append(Problem(NOT_JSON, str(path), None, None,
                                f"{path} is not valid JSON: {exc}"))
        return None
    if not isinstance(data, dict):
        problems.append(Problem(NOT_JSON, str(path), None, None,
                                f"{path} must contain a JSON object"))
        return None
    return data


def _leaf_nodes(schema: Dict[str, Any]
                ) -> List[Tuple[str, Optional[str], Dict[str, Any]]]:
    """`(key, leaf, node)` for every leaf of the schema, in schema order; `leaf` is
    None for a key that is no object of named leaves."""
    out: List[Tuple[str, Optional[str], Dict[str, Any]]] = []
    for key, node in schema["properties"].items():
        if node.get("type") == "object" and "properties" in node:
            for leaf, sub in node["properties"].items():
                out.append((key, leaf, sub))
        else:
            out.append((key, None, node))
    return out


def _file_layer(data: Optional[Dict[str, Any]], path: Optional[Path], role: str,
                schema: Dict[str, Any], problems: List[Problem]) -> Dict[str, Any]:
    """The valid leaf values of one settings file, `group.leaf` keyed. Each value
    outside its set, unknown key, `project` key in the user file and newer version is
    a problem."""
    out: Dict[str, Any] = {}
    if data is None or path is None:
        return out
    where = str(path)
    props = schema["properties"]
    newest = schema.get("x-version")
    for key, value in data.items():
        node = props.get(key)
        if node is None:
            problems.append(Problem(UNKNOWN_KEY, where, key, value,
                                    f"{where}: unknown key {_json_text(key)}; it is ignored"))
            continue
        if key == "version":
            # The format of this file: each file has its own, never a scope problem.
            if not _valid(value, node):
                problems.append(_bad_value(where, key, value, node))
                continue
            if _is_int(newest) and value > newest:
                problems.append(Problem(
                    NEWER_VERSION, where, key, value,
                    f"{where} declares version {value}; this shipgate knows version "
                    f"{newest} and reads only the keys it knows. Update shipgate."))
            if role == SOURCE_PROJECT:
                out[key] = value
            continue
        if role == SOURCE_USER and node.get("x-scope") == SCOPE_PROJECT:
            problems.append(Problem(
                SCOPE, where, key, value,
                f"{where}: {key} is a project setting; the user settings file cannot set "
                f"it, so it is ignored"))
            continue
        if node.get("type") == "object" and "properties" in node:
            if not isinstance(value, dict):
                problems.append(_bad_value(where, key, value, node))
                continue
            extra = node.get("additionalProperties")
            for leaf, leaf_value in value.items():
                name = f"{key}.{leaf}"
                sub = node["properties"].get(leaf)
                if sub is None and isinstance(extra, dict):
                    sub = extra
                if sub is None:
                    problems.append(Problem(
                        UNKNOWN_KEY, where, name, leaf_value,
                        f"{where}: unknown key {_json_text(name)}; it is ignored"))
                    continue
                if _valid(leaf_value, sub):
                    out[name] = leaf_value
                else:
                    problems.append(_bad_value(where, name, leaf_value, sub))
            continue
        if _valid(value, node):
            out[key] = value
        else:
            problems.append(_bad_value(where, key, value, node))
    return out


# --------------------------------------------------------------------------
# Legacy lines: settings an existing config still writes as `- Key: value` bullets.
# The parse of each section is the one its reader used before ADR 0028, so a legacy
# line gives today's value. `lean_config.py --move-settings` shares this reader.
# --------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def _legacy_word(value: str) -> Optional[str]:
    """The first word of a bullet value (its first backticked span, else the bare
    text), lower-cased with emphasis dropped; None for a placeholder or no word. The
    way a model reads `Mode: **executive** — …`."""
    found = bullet_value(value)
    if found is None:
        return None
    match = _WORD_RE.search(re.sub(r"[`*_]", "", found).lower())
    return match.group(0) if match else None


def legacy_code_graph(value: str) -> Optional[str]:
    """The first backticked span, else the bare value, lower-cased; None for a
    placeholder. The `Code graph` rule before ADR 0028 (`signals.parse_code_graph`)."""
    found = bullet_value(value)
    return None if found is None else found.lower()


def legacy_handoff(value: str) -> Optional[str]:
    """A `Handoff:` value as the settings file writes it (`500k`, `off`), or None for
    a placeholder. Not checked: `_legacy_value` checks it against the schema."""
    found = bullet_value(value)
    return None if found is None else found.strip("`").strip().lower()


def forge_cli(value: Optional[str]) -> Optional[str]:
    """The CLI a **Forge & tracker** ``Forge:`` value names (``GitHub — CLI: gh``), or
    the one its forge implies; None for a placeholder or another forge."""
    if not value or is_placeholder_value(value.strip()):
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


FORGE_OF_CLI = {"gh": "github", "glab": "gitlab"}
CLI_OF_FORGE = {forge: cli for cli, forge in FORGE_OF_CLI.items()}


def _legacy_forge(value: str) -> Optional[str]:
    if is_placeholder(value):
        return None
    cli = forge_cli(value)
    # Another forge reads as a bad value: no CLI the close-out can run.
    return FORGE_OF_CLI.get(cli, value.strip()) if cli else value.strip()


CODE_SIGNALS_KEYS = {"window": "window_months", "fix pattern": "fix_pattern",
                     "exclude": "exclude", "ranking exclude": "ranking_exclude"}


def code_signals_lines(text: str, max_window: int = 1200
                       ) -> Tuple[Dict[str, Any], List[Tuple[str, str, str]]]:
    """The `## Code signals` section: `(values, bad)`. Only backticked values count.

    VALUES holds the keys that carry a usable value. BAD holds `(key, bullet, value)`
    for a bullet with a backticked value that is not usable: a window that is no
    integer from 1 to MAX_WINDOW, or a regex that does not compile. A `<placeholder>`
    or a bare value is absent, as before. A `Ranking exclude` whose backticked spans
    are all empty is `[]`, which turns the built-in ranking excludes off.
    """
    out: Dict[str, Any] = {}
    bad: List[Tuple[str, str, str]] = []
    for key, value in section_bullets(text, "code signals", keep_case=True):
        name = CODE_SIGNALS_KEYS.get(key.lower())
        if name is None or name in out:
            continue
        spans = [s.strip() for s in BACKTICK_RE.findall(value)]
        if name == "ranking_exclude" and spans and not any(spans):
            out[name] = []
            continue
        spans = [s for s in spans if not is_placeholder(s)]
        if not spans:
            continue
        if name == "window_months":
            try:
                months = int(spans[0])
            except ValueError:
                bad.append((name, key, value))
                continue
            if 1 <= months <= max_window:
                out[name] = months
            else:
                bad.append((name, key, value))
        elif name == "fix_pattern":
            try:
                re.compile(spans[0])
            except re.error:
                bad.append((name, key, value))
                continue
            out[name] = spans[0]
        else:
            # Separate spans or one comma-separated span: both are a list of globs.
            globs = [g.strip() for span in spans for g in span.split(",")]
            out[name] = [g for g in globs if g]
    return out, bad


# Per section: how a bullet reads (None for Code signals, which reads whole), and the
# rule that makes the section present (ADR 0018's general rule unless named).
_LEGACY_PARSERS: Dict[str, Callable[[str], Optional[Any]]] = {
    "autonomy": _legacy_word,
    "orchestration.review": _legacy_word,
    "orchestration.explore": _legacy_word,
    "writing_style": _legacy_word,
    "code_graph": legacy_code_graph,
    "handoff": legacy_handoff,
    "forge": _legacy_forge,
    # The Knowledge base bullets (the user's decision, 2026-11-24): a repo path only; a
    # wiki home is words, so it gives no value and no `bad-legacy` problem.
    "ledger": lambda raw: legacy_home("ledger", raw),
    "artifact_homes.prd": lambda raw: legacy_home("prd", raw),
    "artifact_homes.adr": lambda raw: legacy_home("adr", raw),
    "artifact_homes.worklog": lambda raw: legacy_home("worklog", raw),
}

# The settings a `## Knowledge base` bullet sets: a legacy line only when it gives a value.
HOME_KEYS = ("ledger", "artifact_homes.prd", "artifact_homes.adr", "artifact_homes.worklog")
_PRD_KEY = "artifact_homes.prd"
_WORKLOG_KEY = "artifact_homes.worklog"
_BESIDE_RE = re.compile(r"beside the prd", re.IGNORECASE)


def _beside_the_prd(raw: str) -> bool:
    """True for a `Worklog home` with no directory of its own, the form `setup` wrote:
    "beside the PRD as `<name>.worklog.md`"."""
    found = bullet_value(raw)
    if found is not None and "/" not in found and found.lower().endswith(".worklog.md"):
        return True
    return _BESIDE_RE.search(raw) is not None


class _BesidePrd(object):
    """The legacy value of a `Worklog home` beside the PRD: `resolve_settings` puts the
    worklog glob beside the resolved PRD home in its place (`beside_prd`)."""

    def __repr__(self) -> str:
        return "BESIDE_PRD"


BESIDE_PRD: Any = _BesidePrd()


def beside_prd(prd: Any) -> str:
    """The worklog glob beside the PRD glob PRD: its part before the last `/`, then
    `/*.worklog.md`."""
    if isinstance(prd, str) and "/" in prd:
        return prd.rsplit("/", 1)[0] + "/*.worklog.md"
    return "*.worklog.md"


def _gives(value: Any, node: Dict[str, Any]) -> bool:
    """True when a legacy VALUE is one: valid by NODE, or the worklog beside the PRD."""
    return value is BESIDE_PRD or (value is not None and _valid(value, node))


def _section_values(text: str, section: str,
                    keys: Sequence[Tuple[str, Dict[str, Any], str]]
                    ) -> List[Tuple[str, Dict[str, Any], str, str, Optional[Any]]]:
    """`(key, node, bullet, raw, value)` for each of KEYS (`(key, node, bullet)`) whose
    bullet the section SECTION of TEXT holds: its first bullet, read by the key's legacy
    rule. VALUE is None when the bullet gives none, and BESIDE_PRD for a `Worklog home`
    beside the PRD: the resolver places it beside the PRD home that applies."""
    bullets = section_bullets(text, section.lower(), keep_case=True)
    out: List[Tuple[str, Dict[str, Any], str, str, Optional[Any]]] = []
    for key, node, bullet in keys:
        raw = next((v for k, v in bullets if k.lower() == bullet.lower()), None)
        if raw is None:
            continue
        value = _LEGACY_PARSERS[key](raw)
        if value is None and key == _WORKLOG_KEY and _beside_the_prd(raw):
            value = BESIDE_PRD
        out.append((key, node, bullet, raw, value))
    return out


def _legacy_keys(schema: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any], str, str]]:
    """`(key, node, section, bullet)` for each leaf with an `x-legacy` source."""
    out = []
    for key, leaf, node in _leaf_nodes(schema):
        legacy = node.get("x-legacy")
        if isinstance(legacy, dict):
            name = key if leaf is None else f"{key}.{leaf}"
            out.append((name, node, str(legacy["section"]), str(legacy["key"])))
    return out


def legacy_keys(schema: Optional[Dict[str, Any]] = None
                ) -> List[Tuple[str, Dict[str, Any], str, str]]:
    """`(key, schema node, section, bullet)` for each setting with a legacy line, in
    schema order. The plugin's schema unless SCHEMA is given."""
    return _legacy_keys(schema if schema is not None else load_schema())


def setting_node(key: str, schema: Optional[Dict[str, Any]] = None
                 ) -> Optional[Dict[str, Any]]:
    """The schema node of a leaf key (`autonomy`, `orchestration.review`, an extra kind
    such as `artifact_homes.design`), or None for a key the schema does not know."""
    props = (schema if schema is not None else load_schema())["properties"]
    group, _, leaf = key.partition(".")
    node = props.get(group)
    if node is None or not leaf:
        return node
    if node.get("type") != "object" or "properties" not in node:
        return None
    sub = node["properties"].get(leaf)
    extra = node.get("additionalProperties")
    return sub if sub is not None else (extra if isinstance(extra, dict) else None)


def valid_setting(key: str, value: Any, schema: Optional[Dict[str, Any]] = None) -> bool:
    """True when a settings file can hold VALUE for the leaf KEY: the check the resolver
    makes (`_valid`)."""
    node = setting_node(key, schema)
    return node is not None and _valid(value, node)


def legacy_value(key: str, raw: str, schema: Optional[Dict[str, Any]] = None
                 ) -> Optional[Any]:
    """The value a legacy bullet gives for KEY, by the resolver's own parse of its
    section, or None when it gives none: a placeholder, a value the parse ignores (a
    bare Code signals value), or a value outside its set (a `bad-legacy` problem). RAW
    is the bullet's value as `section_bullets` reads it. KeyError for a key with no
    legacy line."""
    schema = schema if schema is not None else load_schema()
    for name, node, section, bullet in _legacy_keys(schema):
        if name != key:
            continue
        if section.lower() == "code signals":
            window = schema["properties"]["code_signals"]["properties"]["window_months"]
            values, _bad = code_signals_lines(f"## {section}\n- {bullet}: {raw}\n",
                                              window.get("maximum", 1200))
            value = values.get(key.split(".", 1)[1])
        else:
            value = _LEGACY_PARSERS[key](raw)
        if value is None or not _valid(value, node):
            return None
        return value
    raise KeyError(key)


_HOME_GLOBS = {"prd": "*.md", "adr": "*.md", "worklog": "*.worklog.md"}


_HOME_PART_RE = re.compile(r"<[^/<>]+>")
_HOME_CHARS_RE = re.compile(r"[\w.*/-]+")
_TRAILING = (",", ";", ".", ")")


def legacy_home(kind: str, raw: str) -> Optional[str]:
    """The setting value that a Knowledge base bullet names: a glob for KIND `prd`,
    `adr` or `worklog` (`artifact_homes`), a path for `ledger`. None when the bullet
    names no path in the repo that a setting can hold: a placeholder, a wiki path or
    URL, words, an absolute path, or one that leaves the repo.

    The value is the first backticked span; with no span, the first word of the bare
    value, less one trailing `,` `;` `.` or `)`. A leading `./` goes, and each `<...>`
    inside a segment reads as `*`. Then only `[\\w.*/-]` may remain. A home that names a
    directory (a `/`, and no `.` in its last segment) becomes `<dir>/*.md`, or
    `<dir>/*.worklog.md` for a worklog; a home that ends in `.md` and holds a `/` stays
    as written. A ledger is a path that ends in `.md`, with no `*`. Each step is linear
    in the length of RAW."""
    value = bullet_value(raw)
    if value is None:
        return None
    if not BACKTICK_RE.search(raw):
        words = value.split()
        if not words:
            return None
        value = words[0]
        if value.endswith(_TRAILING):
            value = value[:-1]
    while value.startswith("./"):
        value = value[2:]
    value = _HOME_PART_RE.sub("*", value)
    if (not _HOME_CHARS_RE.fullmatch(value) or value.startswith("/")
            or ".." in value.split("/")):
        return None
    if kind == "ledger":
        return value if value.endswith(".md") and "*" not in value else None
    if kind not in _HOME_GLOBS or "/" not in value:
        return None
    if value.endswith(".md"):
        return value
    directory = value.rstrip("/")
    if not directory or "." in directory.split("/")[-1]:
        return None
    return directory + "/" + _HOME_GLOBS[kind]


def legacy_values(text: str, schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Per legacy key, the value TEXT gives when it owns each section: the resolver's
    own parse. A `Worklog home` beside the PRD gives BESIDE_PRD (`beside_prd` of the PRD
    home that applies is its value). A key whose bullet gives no value, or a value
    outside its set, is left out."""
    schema = schema if schema is not None else load_schema()
    by_section: Dict[str, List[Tuple[str, Dict[str, Any], str]]] = {}
    for key, node, section, bullet in _legacy_keys(schema):
        by_section.setdefault(section, []).append((key, node, bullet))
    out: Dict[str, Any] = {}
    for section, keys in by_section.items():
        if section.lower() == "code signals":
            window = schema["properties"]["code_signals"]["properties"]["window_months"]
            values, _bad = code_signals_lines(text, window.get("maximum", 1200))
            out.update({f"code_signals.{leaf}": value for leaf, value in values.items()})
            continue
        for key, node, _bullet, _raw, value in _section_values(text, section, keys):
            if _gives(value, node):
                out[key] = value
    return out


def legacy_lines(files: Sequence[ConfigFile], schema: Dict[str, Any]
                 ) -> List[LegacyLine]:
    """Every legacy line FILES hold: each bullet with a value (not a placeholder) that
    a schema key names as its `x-legacy` source. Read whole, owners aside. A home or
    ledger bullet (HOME_KEYS) counts only when it gives a value: a wiki home is words."""
    found: List[LegacyLine] = []
    homes: Dict[str, List[Tuple[str, Dict[str, Any], str]]] = {}
    for key, node, section, bullet in _legacy_keys(schema):
        if key in HOME_KEYS:
            homes.setdefault(section, []).append((key, node, bullet))
    for config in files:
        given = {key: (section, bullet, raw)
                 for section, keys in homes.items()
                 for key, node, bullet, raw, value in _section_values(config.text, section,
                                                                      keys)
                 if _gives(value, node)}
        for key, _node, section, bullet in _legacy_keys(schema):
            if key in HOME_KEYS:
                if key in given:
                    found.append(LegacyLine(str(config.path), section, bullet, key,
                                            given[key][2].strip()))
                continue
            for name, value in section_bullets(config.text, section.lower(),
                                               keep_case=True):
                if name.lower() == bullet.lower() and _value_present(value):
                    found.append(LegacyLine(str(config.path), section, bullet, key,
                                            value.strip()))
                    break
    return found


def _legacy_layer(files: Sequence[ConfigFile], schema: Dict[str, Any],
                  problems: List[Problem]) -> Dict[str, Tuple[str, Any, ConfigFile]]:
    """Per legacy key, the value its section owner gives (ADR 0018):
    `{key: (role, value, file)}`. A value outside its set is a `bad-legacy` problem
    and gives nothing, so the next layer applies."""
    out: Dict[str, Tuple[str, Any, ConfigFile]] = {}
    by_section: Dict[str, List[Tuple[str, Dict[str, Any], str]]] = {}
    for key, node, section, bullet in _legacy_keys(schema):
        by_section.setdefault(section, []).append((key, node, bullet))
    for section, keys in by_section.items():
        name = section.lower()
        if name == "code signals":
            window = schema["properties"]["code_signals"]["properties"]["window_months"]
            most = window.get("maximum", 1200)
            for config in files:
                values, bad = code_signals_lines(config.text, most)
                for leaf, bullet, value in bad:
                    node = schema["properties"]["code_signals"]["properties"][leaf]
                    problems.append(_bad_value(
                        str(config.path), f"code_signals.{leaf}", value.strip(), node,
                        BAD_LEGACY, f" ## {section} {bullet}"))
                if values:
                    for leaf, value in values.items():
                        out[f"code_signals.{leaf}"] = (config.role, value, config)
                    break
            continue
        owner = section_owner(files, name)
        if owner is None:
            continue
        for key, node, bullet, raw, value in _section_values(owner.text, section, keys):
            if value is None:
                continue
            if _gives(value, node):
                out[key] = (owner.role, value, owner)
            else:
                problems.append(_bad_value(str(owner.path), key, raw.strip(), node,
                                           BAD_LEGACY, f" ## {section} {bullet}"))
    return out


def _grace(schema: Dict[str, Any], today: Optional[date]) -> Tuple[Optional[str], bool]:
    until = schema.get("x-legacy-until")
    if not isinstance(until, str):
        return None, False
    try:
        last = date.fromisoformat(until)
    except ValueError:
        return until, False
    return until, (today or date.today()) > last


# The default of `resolve_settings`' PROJECT_DATA and USER_DATA: read the file.
READ_FILE: Any = object()


def resolve_settings(project_file: Optional[Path], md_files: Sequence[ConfigFile],
                     user_file: Optional[Path], schema: Optional[Dict[str, Any]] = None,
                     today: Optional[date] = None, project_data: Any = READ_FILE,
                     user_data: Any = READ_FILE) -> Resolved:
    """Each setting's value, source and problems (ADR 0028, L1). Per key, nearest
    first: the project settings file, a project-side legacy line, the user settings
    file, a user legacy line, the default. MD_FILES are `read_layers`' files.

    The walk stops at the first layer that decides a key: a valid value gives it, and
    a value outside its set in a settings file gives the default with a `bad-value`
    problem, so a farther layer never matters. A legacy line outside its set is a
    `bad-legacy` problem and the walk goes on. A settings file that cannot be read is
    skipped; the keys whose walk reached it carry that `not-json` problem. It never
    raises on a value and never exits: `Resolved.require` lets a strict caller refuse.
    The schema is read from the plugin unless SCHEMA is given. PROJECT_DATA and
    USER_DATA, when given, stand for a settings file's content (its JSON object, or
    None for no file) at PROJECT_FILE and USER_FILE, which are then not read: a caller
    resolves a planned state that way (`lean_config.py --move-settings`)."""
    schema = schema if schema is not None else load_schema()
    problems: List[Problem] = []
    if project_data is READ_FILE:
        project_data = _read_settings_file(project_file, problems)
    if user_data is READ_FILE:
        user_data = _read_settings_file(user_file, problems)
    project = _file_layer(project_data, project_file, SOURCE_PROJECT, schema, problems)
    user = _file_layer(user_data, user_file, SOURCE_USER, schema, problems)
    legacy = _legacy_layer(md_files, schema, problems)

    def file_state(path: Optional[Path]) -> Tuple[Optional[Problem], Dict[str, Problem]]:
        """The file's `not-json` problem, and its `bad-value` problems by key."""
        where = str(path) if path is not None else None
        broken = next((p for p in problems if p.kind == NOT_JSON and p.path == where),
                      None)
        bad = {p.key: p for p in problems
               if p.kind == BAD_VALUE and p.path == where and p.key is not None}
        return broken, bad

    project_broken, project_bad = file_state(project_file)
    user_broken, user_bad = file_state(user_file)

    settings: Dict[str, Setting] = {}
    leaves = [(k if leaf is None else f"{k}.{leaf}", node)
              for k, leaf, node in _leaf_nodes(schema)]
    # An extra artifact kind that a settings file names is a leaf too.
    known = {name for name, _ in leaves}
    for layer in (project, user):
        for name in layer:
            if name not in known:
                leaves.append((name, {}))
                known.add(name)
    props = schema["properties"]
    for name, node in leaves:
        group = name.split(".", 1)[0]
        scope = props.get(group, {}).get("x-scope", SCOPE_ANY)
        section = node.get("x-legacy", {}).get("section")
        default = Setting(node.get("default"), SOURCE_DEFAULT, None)
        reached: Optional[Problem] = None  # a skipped file this walk passed
        found: Optional[Setting] = None
        layers = (
            (project, project_broken, project_bad, project_file, SOURCE_PROJECT),
            "legacy-project",
            (user, user_broken, user_bad, user_file, SOURCE_USER),
            "legacy-user",
        )
        for layer in layers:
            if isinstance(layer, str):
                entry = legacy.get(name)
                if entry is None or (entry[0] == ROLE_USER) != (layer == "legacy-user"):
                    continue
                found = Setting(entry[1], SOURCE_LEGACY, str(entry[2].path), section)
                break
            values, broken, bad, path, source = layer
            if source == SOURCE_USER and scope == SCOPE_PROJECT:
                continue  # the user file cannot set a project key
            if broken is not None:
                reached = reached or broken
                continue
            refusal = bad.get(name) or bad.get(group)
            if refusal is not None:
                found = default._replace(problem=refusal)
                break
            if name in values:
                found = Setting(values[name], source, str(path))
                break
        found = found or default
        if found.value is BESIDE_PRD:
            prd = settings.get(_PRD_KEY)
            found = found._replace(value=beside_prd(prd.value if prd is not None else None))
        if reached is not None and found.problem is None:
            found = found._replace(problem=reached)
        settings[name] = found
    until, ended = _grace(schema, today)
    return Resolved(settings, problems, legacy_lines(md_files, schema), until, ended)
