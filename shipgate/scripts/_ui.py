"""The UI function of shipgate (ADR 0031): which paths are UI files, and the pixel width
of a PNG screenshot.

Standard library only. ``signals.py`` and the journal package (``_journal/plugin.py``)
both load this file by path, so every caller decides "UI" with the one rule.
"""

from __future__ import annotations

import os
import struct
from fnmatch import fnmatchcase
from typing import List, Sequence, Union

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# The signature (8), the IHDR chunk's length (4) and type (4), its width (4) and height (4).
_PNG_HEAD_BYTES = 24


def is_ui(path: str, globs: Sequence[str]) -> bool:
    """True when PATH matches one of GLOBS by the rule of the artifact homes
    (``artifacts._matches_glob``): the glob as written, or ``*/`` and the glob, so a
    project-relative glob also matches a deeper or absolute path. A leading ``./`` goes
    from the path and from each glob. The match is case-sensitive on every platform. An
    empty GLOBS gives False."""
    normalized = path.replace(os.sep, "/").removeprefix("./")
    for glob in globs:
        pattern = glob.removeprefix("./")
        if fnmatchcase(normalized, pattern) or fnmatchcase(normalized, "*/" + pattern):
            return True
    return False


def png_width(path: Union[str, os.PathLike]) -> int:
    """The pixel width in the IHDR chunk of the PNG at PATH, from its first 24 bytes.

    ValueError when the file is shorter ("truncated"), when its signature or first chunk
    is not a PNG's, or when the width is 0 ("not a PNG"). An OSError from the read
    propagates: the caller reports it.
    """
    with open(path, "rb") as handle:
        head = handle.read(_PNG_HEAD_BYTES)
    if len(head) < _PNG_HEAD_BYTES:
        raise ValueError(f"truncated: {len(head)} bytes, a PNG header needs "
                         f"{_PNG_HEAD_BYTES}")
    if head[:8] != PNG_SIGNATURE:
        raise ValueError("not a PNG: no PNG signature")
    if head[12:16] != b"IHDR":
        raise ValueError("not a PNG: the first chunk is not IHDR")
    (width,) = struct.unpack(">I", head[16:20])
    if width == 0:
        raise ValueError("not a PNG: width 0")
    return width


def match_width(px: int, widths: Sequence[int]) -> List[int]:
    """The set WIDTHS w, in their order and without repeats, for which PX is w, 2w or 3w:
    a screenshot of a high-density screen is 2 or 3 pixels per CSS pixel."""
    out: List[int] = []
    for width in widths:
        if width not in out and px in (width, 2 * width, 3 * width):
            out.append(width)
    return out
