"""Payload shape validation, size cap, location keys, vocabulary checks."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .vocab import (
    EVENT_SHAPES, EVENT_VOCABULARY, GateViolation, PAYLOAD_CAP_BYTES, UsageError,
)
from .fold import _finding_key, is_work_stream


def suggest_event_types(event_type: str) -> List[str]:
    """Candidate canonical names for an unrecognized type.

    Textual similarity alone is not enough: `decision` and `verify-passed` are near
    misses of real names, but `workspace-ready` shares no substring with
    `flow-started` even though it means it. So this offers word-overlap matches where
    they exist and falls back to naming the whole vocabulary — the point is to get the
    caller to the right name, not to be clever.
    """
    from difflib import get_close_matches

    known = list(EVENT_VOCABULARY)
    close = get_close_matches(event_type, known, n=3, cutoff=0.5)
    words = {w for w in re.split(r"[-_]", event_type.lower()) if w}
    for candidate in known:
        if candidate in close:
            continue
        if words & {w for w in candidate.split("-") if w}:
            close.append(candidate)
    return close[:4]


def normalize_payload(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite a payload to its canonical shape, or refuse it.

    Aliases are renamed and defaults filled before anything is checked, so a caller
    using an older spelling is corrected rather than rejected. What is left must
    satisfy the required keys, the enums and the list types — a gate reading
    ``data.outcome`` cannot do its job on a payload that spells it ``result``.

    Two keys that mean the same thing are refused rather than resolved: silently
    dropping one of them would discard a value the caller meant to record, and there
    is no way to tell which of the two they meant.

    After the shape, the finding maps of ``LOCATION_KEYED_MAPS`` must hold location
    keys only (``check_location_keys``, ADR 0014 amended 0.23.0), and a verdict's
    ``security_review`` must have read a file (``check_security_review``, #40).
    """
    shape = EVENT_SHAPES.get(event_type)
    if not shape:
        return dict(data)

    aliases = shape.get("aliases", {})
    payload: Dict[str, Any] = {}
    written_by: Dict[str, str] = {}
    for key, value in data.items():
        canonical = aliases.get(key, key)
        if canonical in written_by:
            raise GateViolation(
                f"{event_type}: data.{written_by[canonical]} and data.{key} both "
                f"mean {canonical!r} — send one of them"
                + _shape_hint(event_type)
            )
        written_by[canonical] = key
        payload[canonical] = value
    for key, mapping in shape.get("value_aliases", {}).items():
        value = payload.get(key)
        if isinstance(value, str) and value in mapping:
            payload[key] = mapping[value]
    for key, value in shape.get("defaults", {}).items():
        payload.setdefault(key, value)

    _validate_shape(event_type, payload, shape, "data")
    check_location_keys(event_type, payload)
    check_security_review(event_type, payload)
    return payload


def check_security_review(event_type: str, payload: Dict[str, Any]) -> None:
    """Refuse a ``builtin`` or ``briefed`` security review that read no file (#40).

    The built-in command reads commits only, so before the commit its diff is empty and
    it reports no finding on no code. A count of 0, or none, records that as a review.
    A ``builtin`` review also names the commit it read in ``ref``. A payload check, like
    the shape: ``--force`` does not waive it. An imported row is not checked again. Runs
    after ``_validate_shape``, so ``files`` is absent or a non-negative integer and
    ``ref`` absent or a string.
    """
    review = payload.get("security_review")
    if event_type != "review-verdict" or not isinstance(review, dict):
        return
    kind = review.get("kind")
    if kind in ("builtin", "briefed") and not review.get("files"):
        raise GateViolation(
            f"{event_type}: data.security_review of kind {kind!r} read no file — a "
            "review of an empty diff is no review. Give data.security_review.files the "
            'number of files it read, or record {"kind": "none"} when no security '
            "review ran"
        )
    if kind == "builtin" and not str(review.get("ref", "")).strip():
        raise GateViolation(
            f"{event_type}: data.security_review of kind 'builtin' names no commit — "
            "the built-in command reads a commit; give its sha in "
            "data.security_review.ref"
        )


_EXITS_SHOWN = 10


def _settle_verify_outcome(event_type: str, payload: Dict[str, Any]) -> None:
    """Derive a ``verify-run``'s ``outcome`` from its exits, or refuse it (ADR 0033).

    With items in ``commands``, the outcome is ``pass`` when every ``exit`` is 0, else
    ``fail``: an absent ``outcome`` is set to it, and one that differs is refused. An
    empty list is the way out for a check that is no Bash command, so it needs the
    ``outcome``. A payload check, like the shape: ``--force`` does not waive it. Runs
    after ``_validate_shape``, so ``commands`` is a list of objects with an integer
    ``exit`` each, and ``outcome`` is absent or in the enum.
    """
    if event_type != "verify-run":
        return
    commands = payload["commands"]
    outcome = payload.get("outcome")
    if not commands:
        if outcome is None:
            raise GateViolation(
                f"{event_type}: data.commands is empty, so data.outcome is required — "
                "an empty list is for a check that is no Bash command: name the check "
                "in data.scope and give its data.outcome"
            )
        return
    exits = [item["exit"] for item in commands]
    derived = "pass" if all(code == 0 for code in exits) else "fail"
    if outcome is None:
        payload["outcome"] = derived
        return
    if outcome != derived:
        shown = ", ".join(str(code) for code in exits[:_EXITS_SHOWN])
        more = len(exits) - _EXITS_SHOWN
        raise GateViolation(
            f"{event_type}: data.outcome is {outcome!r}, but data.commands exit "
            f"{shown}" + (f" and {more} more" if more > 0 else "")
            + f", which is {derived!r} — leave data.outcome out and the journal "
            "derives it from the exits"
        )


# The maps keyed by a review finding (ADR 0014, amended 0.23.0). Each key must be a
# location, as the HUD's `parseLocation` reads one; a free label never matches a finding,
# so its state would stay open on one side of the fold for good.
LOCATION_KEYED_MAPS: Dict[str, Tuple[str, ...]] = {
    "review-disposition": ("dispositions", "labels"),
    "review-verdict": ("dispositions",),
}
_LOCATION_LINE_RE = re.compile(r"[0-9]+")
_LOCATION_KEYS_SHOWN = 5


def is_location_key(key: Any) -> bool:
    """Whether ``key`` is a finding location ``<path>:<line|?>``.

    The same grammar as the HUD's ``parseLocation`` (shipgate-hud ``hooks/review.ts``):
    the text splits at its last ``:``, which must not be its first character; the path
    is the text before it with every leading ``./`` dropped, and must not be empty; the
    line after it is ``?`` or ASCII digits only.
    """
    if not isinstance(key, str):
        return False
    cut = key.rfind(":")
    if cut <= 0:
        return False
    if _finding_key(key[:cut]) == "":
        return False
    tail = key[cut + 1:]
    return tail == "?" or _LOCATION_LINE_RE.fullmatch(tail) is not None


def check_location_keys(event_type: str, payload: Dict[str, Any]) -> None:
    """Refuse a finding map key that is not a location (ADR 0014, amended 0.23.0).

    A payload check, like the shape: ``--force`` does not waive it. An imported row is
    not checked again. Runs after ``_validate_shape``, so each map is a JSON object.
    """
    for key in LOCATION_KEYED_MAPS.get(event_type, ()):
        value = payload.get(key)
        if not isinstance(value, dict):
            continue
        bad = [k for k in value if not is_location_key(k)]
        if not bad:
            continue
        shown = ", ".join(json.dumps(k) for k in bad[:_LOCATION_KEYS_SHOWN])
        more = len(bad) - _LOCATION_KEYS_SHOWN
        name_home = (
            "put a human name in data.labels, keyed by the location"
            if event_type == "review-disposition"
            else "put a human name in a review-disposition's labels, keyed by the "
            "location"
        )
        raise GateViolation(
            f"{event_type}: data.{key} has {len(bad)} key(s) that are not a finding "
            f"location: {shown}" + (f" and {more} more" if more > 0 else "")
            + " — a key is the finding's `<path>:<line|?>` (`src/a.ts:12`, "
            f"`src/a.ts:?`); {name_home}"
        )


def _validate_shape(
    event_type: str, payload: Dict[str, Any], shape: Dict[str, Any], where: str
) -> None:
    """Check PAYLOAD against SHAPE's validating rule kinds, or refuse it.

    WHERE names the object in the refusal: `data` at the top level, `data.signals`
    inside an `objects` sub-shape, `data.ranking.files[0]` inside a `list_objects`
    one. The top-level messages read as they always have.
    """
    missing = [
        key for key in shape.get("required", []) if payload.get(key) in (None, "")
    ]
    if missing:
        if where == "data":
            raise GateViolation(
                f"{event_type} is missing required data key(s): {', '.join(missing)}"
                + _shape_hint(event_type)
            )
        raise GateViolation(
            f"{event_type}: {where} is missing required key(s): {', '.join(missing)}"
            + _shape_hint(event_type)
        )
    for key in shape.get("lists", []):
        if key in payload and not isinstance(payload[key], list):
            raise GateViolation(
                f"{event_type}: {where}.{key} must be a list" + _shape_hint(event_type)
            )
    for key in shape.get("strings", []):
        if key in payload and not isinstance(payload[key], str):
            raise GateViolation(
                f"{event_type}: {where}.{key} must be a string, got "
                f"{json.dumps(payload[key], sort_keys=True)}" + _shape_hint(event_type)
            )
    for key in shape.get("string_lists", []):
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise GateViolation(
                f"{event_type}: {where}.{key} must be a list of non-empty strings, got "
                f"{json.dumps(value, sort_keys=True)}" + _shape_hint(event_type)
            )
    for key in shape.get("integers", []):
        if key not in payload:
            continue
        value = payload[key]
        # `bool` is an `int` in Python, and `true` is no round number.
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise GateViolation(
                f"{event_type}: {where}.{key} must be a non-negative integer, got "
                f"{json.dumps(value, sort_keys=True)}" + _shape_hint(event_type)
            )
    for key in shape.get("booleans", []):
        if key in payload and not isinstance(payload[key], bool):
            raise GateViolation(
                f"{event_type}: {where}.{key} must be true or false, got "
                f"{json.dumps(payload[key], sort_keys=True)}" + _shape_hint(event_type)
            )
    for key in shape.get("string_maps", []):
        if key not in payload:
            continue
        _require_object(event_type, payload[key], f"{where}.{key}")
        wrong = {
            k: v for k, v in payload[key].items()
            if not isinstance(v, str) or not v.strip()
        }
        if wrong:
            raise GateViolation(
                f"{event_type}: each value of {where}.{key} must be a non-empty string, "
                f"got {json.dumps(wrong, sort_keys=True)}" + _shape_hint(event_type)
            )
    for key, most in shape.get("max_chars", {}).items():
        value = payload.get(key)
        if isinstance(value, str) and len(value) > most:
            raise GateViolation(
                f"{event_type}: {where}.{key} must be at most {most} characters, got "
                f"{len(value)}" + _shape_hint(event_type)
            )
    for key, allowed in shape.get("enums", {}).items():
        if key in payload and payload[key] not in allowed:
            raise GateViolation(
                f"{event_type}: {where}.{key} must be one of "
                f"{', '.join(_json_word(a) for a in allowed)}, got "
                f"{_json_got(payload[key])}" + _shape_hint(event_type)
            )
    for key, allowed in shape.get("map_enums", {}).items():
        if key not in payload:
            continue
        _require_object(event_type, payload[key], f"{where}.{key}")
        wrong = {k: v for k, v in payload[key].items() if v not in allowed}
        if wrong:
            raise GateViolation(
                f"{event_type}: each value of {where}.{key} must be one of "
                f"{', '.join(allowed)}, got {json.dumps(wrong, sort_keys=True)}"
                + _shape_hint(event_type)
            )
    for key, sub_shape in shape.get("objects", {}).items():
        if key not in payload:
            continue
        _require_object(event_type, payload[key], f"{where}.{key}")
        _validate_shape(event_type, payload[key], sub_shape, f"{where}.{key}")
    for key, sub_shape in shape.get("list_objects", {}).items():
        if key not in payload:
            continue
        if not isinstance(payload[key], list):
            raise GateViolation(
                f"{event_type}: {where}.{key} must be a list" + _shape_hint(event_type)
            )
        for index, value in enumerate(payload[key]):
            label = f"{where}.{key}[{index}]"
            _require_object(event_type, value, label)
            _validate_shape(event_type, value, sub_shape, label)


def _json_word(value: Any) -> str:
    """An allowed value as a caller writes it in JSON: a string bare, `null` not `None`."""
    return value if isinstance(value, str) else json.dumps(value)


def _json_got(value: Any) -> str:
    return repr(value) if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _require_object(event_type: str, value: Any, where: str) -> None:
    if not isinstance(value, dict):
        raise GateViolation(
            f"{event_type}: {where} must be a JSON object" + _shape_hint(event_type)
        )


def _shape_hint(event_type: str) -> str:
    return (
        f" — canonical shape (`journal.py vocab --shape {event_type}`): "
        + json.dumps(EVENT_SHAPES[event_type], sort_keys=True)
    )


def check_payload_size(
    stream: str,
    payload: Dict[str, Any],
    force: bool = False,
    force_reason: Optional[str] = None,
) -> None:
    """Refuse a payload carrying prose rather than a pointer to it (FR-013).

    Hook and watcher streams are exempt: their payloads are machine-sized already and
    nobody reads them in the brief. ``--force`` waives the cap only with a reason —
    every brief from here on reprints those bytes, so the waiver has to say why.
    """
    if not is_work_stream(stream):
        return
    size = len(json.dumps(payload, sort_keys=True).encode())
    if size <= PAYLOAD_CAP_BYTES:
        return
    if not force:
        raise GateViolation(
            f"payload is {size} bytes (cap {PAYLOAD_CAP_BYTES}): the worklog/PRD/ADR "
            "holds the prose, the event holds `refs` and one sentence — or --force "
            "with a reason"
        )
    if not force_reason:
        raise UsageError(
            f"--force on a {size}-byte payload (cap {PAYLOAD_CAP_BYTES}) needs "
            "--force-reason saying why the prose belongs in the event"
        )


def validate_event_type(event_type: str, allow_new: bool) -> None:
    """Refuse a type outside the vocabulary unless it is being minted deliberately."""
    if allow_new or event_type in EVENT_VOCABULARY:
        return
    suggestions = suggest_event_types(event_type)
    hint = (
        "closest canonical names: " + ", ".join(suggestions)
        if suggestions
        else "see `journal.py vocab` for the full list"
    )
    raise GateViolation(
        f"'{event_type}' is not in the event vocabulary, so no gate or report would "
        f"ever read it — {hint}. Run `journal.py vocab` to see them all, or pass "
        f"--new-type to mint '{event_type}' on purpose."
    )
