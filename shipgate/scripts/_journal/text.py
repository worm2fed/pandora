"""Pure helpers over strings and payload values."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .vocab import BRIEF_LINE_CHARS


def _in_backticks(command: Optional[str]) -> str:
    """`` (`command`)`` to follow the words it runs, or nothing for no command."""
    return f" (`{command}`)" if command else ""


def _one_line(value: Any) -> str:
    """Collapse every run of whitespace, newlines included, to a single space.

    The brief is injected into the session prompt, so a payload that carries a
    newline would otherwise be able to add lines to it — a heading, a fake section
    divider — and the reader has no way to tell those from the journal's own.
    """
    return " ".join(str(value).split())


def _clip(line: str) -> str:
    flat = _one_line(line)
    if len(flat) <= BRIEF_LINE_CHARS:
        return flat
    return flat[: BRIEF_LINE_CHARS - 1] + "…"


def _short_ts(ts: Any) -> str:
    """Minute precision — the brief is read to orient, never to reconcile.

    Collapsed before it is cut: an imported row can carry anything in `ts`, and 16
    characters of a newline-bearing string would still reach the brief as two lines.
    """
    return _one_line(ts)[:16]


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _normalized_ref(path: str) -> str:
    return "/".join(s for s in path.replace("\\", "/").split("/") if s not in ("", "."))


def _string_or_none(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


def _vocabulary_map(value: Any, allowed: Sequence[str]) -> Dict[str, Any]:
    """The entries of a JSON object whose value is in ``allowed``; {} for a non-object."""
    if not isinstance(value, dict):
        return {}
    return {
        key: item for key, item in value.items()
        if isinstance(item, str) and item in allowed
    }


def _printable(command: str) -> Optional[str]:
    return command if command.isprintable() else None
