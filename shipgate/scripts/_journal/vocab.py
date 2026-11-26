"""Exit codes and their errors, phases, the event vocabulary, payload shapes and limits."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, TypedDict, get_args


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

EXIT_OK = 0
EXIT_INFRA = 1
EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_GATE = 4
EXIT_CHECK = 5
EXIT_IMPORT_CONFLICT = 6

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000


# The phases in their declared order. `Phase` is the closed vocabulary the JSON contract
# types against (ADR 0009); `PHASE_ORDER` is the same list at runtime, derived so the
# two cannot drift.
Phase = Literal[
    "workspace",
    "route-and-map",
    "explore",
    "clarify",
    "design",
    "implement",
    "review",
    "capture",
]
PHASE_ORDER: List[str] = list(get_args(Phase))

FEATURE_STREAM_PREFIX = "feature/"
NEEDS_CLARIFICATION = "[NEEDS CLARIFICATION]"

DEFAULT_ARTIFACT_HOMES = {
    "prd": "docs/prd/*.md",
    "adr": "docs/adr/*.md",
    "worklog": "docs/prd/*.worklog.md",
}

# The canonical event vocabulary — the single source of truth. Skills quote these names;
# the gates key off them exactly. An event whose type is not here is inert: it records
# something, but no gate, fold, or report will ever look at it, which is a worse outcome
# than not recording at all because it reads as success. So `append` refuses an unlisted
# type and points at the nearest candidates; `--new-type` mints one deliberately.
EVENT_VOCABULARY: Dict[str, str] = {
    # lifecycle of a piece of work
    "flow-started": "work began — request and branch",
    "phase-entered": "moved into a phase",
    "deviation": "diverged from the plan, or corrected an earlier record",
    "flow-suspended": "work parked",
    "flow-resumed": "work picked back up",
    "flow-completed": "work finished — capture done, stream leaves the brief",
    "flow-abandoned": "work dropped for good",
    # gates and decisions
    "gate-decision": "a decision taken at a gate (this is the one for 'decision')",
    "go-requested": "the flow put one gate (commit, publish) of one stream to the user",
    "reply-witnessed": "the user replied to a go request with no exact go (hook-written)",
    "clarify-passed": "the clarify gate closed — PRD has no open questions",
    "design-committed": "design + build plan landed",
    "design-queued": "a design parked for a later child issue",
    "design-invalidated": "a queued design broken by what merged",
    # building
    "task-done": "a build-plan task completed",
    "verify-run": "evidence from a verification run (this is the one for 'verify-passed')",
    # debugging
    "bug-reproduced": "the defect was reproduced — expected vs actual",
    "debug-root-cause": "root cause established, with the evidence for it",
    # review and delivery
    "review-verdict": "review concluded",
    "review-disposition": "a review finding's state, recorded when it is decided",
    "mr-opened": "an MR/PR was opened",
    "review-feedback": "reviewer feedback arrived",
    "capture-done": "ledger triaged, learnings promoted or dropped",
    # written by hooks and setup, not by a skill
    "artifact-written": "an artifact file changed (hook-written)",
    "session-started": "a session began (hook-written)",
    "session-ended": "a session ended (hook-written)",
    "gate-blocked": "Stop hook blocked a session over missing events (hook-written)",
    "setup-completed": "setup created or updated this project",
    "schema-migrated": "the journal schema moved version",
    "imported": "events were imported from a JSONL export",
    # MR-watcher streams
    "baseline": "watcher's first observation of an MR",
    "pipeline-flip": "CI status changed",
    "comments-added": "new reviewer comments",
    "merge-status": "mergeability changed",
    "conflicts": "conflicts appeared",
    "approved": "the MR was approved",
    "merged": "the MR merged",
    "closed": "the MR closed unmerged",
}

# The payload shape each type must satisfy — the counterpart to the vocabulary above:
# the vocabulary makes an event *findable*, the shape makes it *readable*. A type absent
# here has no shape on purpose (hook and watcher payloads answer to their writer, not to
# a gate). Per type:
#   required      keys that must be present
#   enums         key -> the only values accepted for it
#   lists         keys whose value must be a JSON list
#   aliases       old key -> canonical key, renamed before validation
#   value_aliases key -> {old value: canonical value}
#   defaults      key -> value filled in when absent
#   strings       keys whose value must be a JSON string
#   map_enums     key -> the only values accepted for each value of the JSON object at
#                 that key
#   objects       key -> a sub-shape: the value must be a JSON object that passes it
#   list_objects  key -> a sub-shape: the value must be a JSON list, and each of its
#                 items a JSON object that passes it
#   string_lists  keys whose value must be a JSON list of non-empty strings
#   integers      keys whose value must be a non-negative JSON integer (a boolean is
#                 refused)
#   booleans      keys whose value must be JSON true or false (1 and 0 are refused)
#   string_maps   keys whose value must be a JSON object, each of its values a
#                 non-empty string
#   max_chars     key -> the most characters a string value may hold
# A sub-shape takes the validating kinds above (required, enums, lists, strings,
# string_lists, integers, booleans, string_maps, max_chars, map_enums, objects,
# list_objects);
# aliases and defaults apply at the top level only.
# `normalize_payload` enforces every kind, and `vocab --shape` prints them.
#
# The closed values below are declared once as `Literal`s, so the JSON contract
# (`status --json`, `position`) and the append check read the same list.
GateMode = Literal["ask", "executive"]
RaisedBy = Literal["user", "orchestrator"]
# The marker of the user's go (ADR 0015, ADR 0023). `dialog`: the HUD's publish dialog.
# `shell`: the user's own `!` command. `question`: the recorder, from a question answer.
# `prompt`: the recorder, from a typed reply. The model writes no marker: 0.28.0's `read`
# is retired (#52, ADR 0023 amendment A3), and `append` refuses it (`_refuse_read_go`).
DecisionSource = Literal["dialog", "shell", "question", "prompt"]
# The gates a go answers (ADR 0023 §1). A publish go also satisfies the commit gate.
GoGate = Literal["commit", "publish"]
# How a reply reached the recorder: a typed prompt, or a question answer.
ReplyVia = Literal["prompt", "question"]
VerifyOutcome = Literal["pass", "fail"]
ReviewVerdict = Literal["ready", "not-ready"]
# A `review-verdict`'s optional maps (ADR 0009): a PRD success criterion's status, and
# what the orchestrator did with a review finding. The shape below closes them with
# `map_enums`.
CriterionStatus = Literal["met", "unmet"]
Disposition = Literal["fixed", "rejected", "deferred"]
# A finding's state as `review-disposition` records it when it is decided (ADR 0014):
# the verdict's three closed states, and `fixing` while a fix is in progress. `fixing`
# exists only on that event; a verdict's `dispositions` stay closed.
FindingState = Literal["fixing", "fixed", "rejected", "deferred"]
# Which security review a verdict rests on (#40): the built-in `/security-review` on a
# commit, a reviewer briefed with its criteria on the working tree, or none.
SecurityReviewKind = Literal["builtin", "briefed", "none"]
# Where the structure half of the code signals came from (#10, ADR 0013): the code
# graph, the regex scanner, or nothing at all (`signals.py` unavailable).
SignalSource = Literal["graph", "regex", "none"]
# A `signals.py` label: a quartile over this repository, or null when it has no value.
SignalLabel = Literal["low", "mid", "high", "top"]
SIGNAL_BUCKETS: List[Optional[str]] = [*get_args(SignalLabel), None]
# The risk ranking a phase used (ADR 0013). `signals.py hotspots --json` prints it as
# `ranking`; `design-committed` and `review-verdict` carry it unchanged.
RANKING_SHAPE: Dict[str, Any] = {
    "required": ["source"],
    "enums": {"source": list(get_args(SignalSource))},
    # Why the signals were unavailable (`no-git`, `shallow`), with `source: none`.
    "strings": ["unavailable"],
    # A list, not an object keyed by path: the journal stores payloads with sorted
    # keys, and the ranking's order is the point of it.
    "list_objects": {
        "files": {
            "required": ["path"],
            "strings": ["path"],
            "enums": {
                "fix": SIGNAL_BUCKETS,
                "churn": SIGNAL_BUCKETS,
                "fan_in": SIGNAL_BUCKETS,
            },
        },
    },
}


# The security review a verdict rests on (#40). `files` is how many files it read; a
# `builtin` or `briefed` review needs at least one (`check_security_review`). `ref` is the
# commit the built-in command read.
SECURITY_REVIEW_SHAPE: Dict[str, Any] = {
    "required": ["kind"],
    "enums": {"kind": list(get_args(SecurityReviewKind))},
    "integers": ["files"],
    "strings": ["ref"],
}


class EventShape(TypedDict, total=False):
    """One ``EVENT_SHAPES`` entry: the rule kinds above, each optional for a type.

    ``strings`` and ``map_enums`` are the payload rules of ADR 0009:
    ``gate-decision.decision`` is a string, and ``review-verdict`` closes the values of
    ``criteria`` and ``dispositions``. ``integers`` is ADR 0014's:
    ``review-disposition.round`` is a non-negative integer. ``string_maps`` is its
    0.22.0 amendment: ``review-disposition.labels`` maps a finding key to a name.
    ``booleans`` is ADR 0031's: ``phase-entered.ui`` is JSON ``true`` or ``false``, and
    nothing else. An enum of the two would take ``1`` and ``0``, because Python counts
    them equal to ``True`` and ``False``.
    """

    required: List[str]
    enums: Dict[str, List[str]]
    lists: List[str]
    aliases: Dict[str, str]
    value_aliases: Dict[str, Dict[str, str]]
    defaults: Dict[str, Any]
    strings: List[str]
    string_lists: List[str]
    integers: List[str]
    booleans: List[str]
    string_maps: List[str]
    max_chars: Dict[str, int]
    map_enums: Dict[str, List[str]]
    objects: Dict[str, Dict[str, Any]]
    list_objects: Dict[str, Dict[str, Any]]


EVENT_SHAPES: Dict[str, EventShape] = {
    # `report_to` names where the flow reports; `handoff` prints the newest (ADR 0021).
    "flow-started": {"required": ["request"], "strings": ["report_to"]},
    "phase-entered": {
        "required": ["phase"],
        # The style skills the config's Style section names, `[]` when it names none
        # (#11). `implement` and `review` carry it.
        "string_lists": ["style"],
        # `route-and-map` carries the signals it computed, always with their source
        # (#10). A map without them records a deviation (ADR 0011).
        "objects": {
            "signals": {
                "required": ["source"],
                "enums": {"source": list(get_args(SignalSource))},
                "strings": ["unavailable"],
                # In an umbrella: each touched repo's own source; `source` is the weakest.
                "map_enums": {"repos": list(get_args(SignalSource))},
            },
        },
        # `route-and-map` carries the computed UI flag when the project sets `ui.globs`
        # (ADR 0031): true when `hotspots --json` counts a UI file, else false.
        "booleans": ["ui"],
    },
    "deviation": {
        "required": ["note"],
        "aliases": {"correction": "note", "what": "note"},
        # `kind` groups deviations in `stats` (`signals-missing`, `style-missing`); `auto`
        # marks the one `append` writes itself (ADR 0011). `gate-waived` with `task_ids`
        # waives those boxes at the Stop gate (ADR 0020). `report_to` moves the target
        # `handoff` prints (ADR 0021).
        "strings": ["kind", "report_to"],
        "lists": ["task_ids"],
    },
    "gate-decision": {
        "required": ["gate", "question", "decision", "mode"],
        "enums": {
            "mode": list(get_args(GateMode)),
            "raised_by": list(get_args(RaisedBy)),
            "source": list(get_args(DecisionSource)),
        },
        "aliases": {"chosen": "decision", "kind": "gate"},
        "defaults": {"raised_by": "orchestrator"},
        # ADR 0023: an exact go names the go request it answers.
        "strings": ["decision"],
        "integers": ["request"],
    },
    # ADR 0023 §3: one gate of one live stream, put to the user. No implied phase.
    "go-requested": {
        "required": ["gate", "question"],
        "enums": {"gate": list(get_args(GoGate))},
        "strings": ["question"],
    },
    # ADR 0023 §7: the recorder's record of a reply that is no exact go. No text.
    "reply-witnessed": {
        "required": ["request", "gate", "via", "session"],
        "enums": {"gate": list(get_args(GoGate)), "via": list(get_args(ReplyVia))},
        "integers": ["request"],
        "strings": ["session", "prompt_id", "tool_use_id"],
    },
    "clarify-passed": {"required": ["prd"]},
    "design-committed": {
        "required": ["worklog"],
        "objects": {"ranking": RANKING_SHAPE},
    },
    "task-done": {"required": ["task_id"]},
    # ADR 0033: `commands` names each run; `outcome` is derived from the exits when
    # left out, and the journal owns OBSERVED_KEY and CONTRADICTED_KEY.
    "verify-run": {
        "required": ["task_ids", "commands"],
        "enums": {"outcome": list(get_args(VerifyOutcome))},
        "lists": ["task_ids", "commands"],
        "aliases": {"result": "outcome", "tasks": "task_ids"},
        "list_objects": {
            "commands": {"required": ["cmd", "exit"], "strings": ["cmd"],
                         "integers": ["exit"]},
        },
    },
    "review-verdict": {
        "required": ["verdict"],
        "enums": {"verdict": list(get_args(ReviewVerdict))},
        "value_aliases": {"verdict": {"pass": "ready", "fail": "not-ready"}},
        "map_enums": {
            "criteria": list(get_args(CriterionStatus)),
            "dispositions": list(get_args(Disposition)),
        },
        # A verdict that enters review by implication still says what it named (#11).
        "string_lists": ["style"],
        "objects": {"ranking": RANKING_SHAPE, "security_review": SECURITY_REVIEW_SHAPE},
    },
    # A finding's state the moment it is decided (ADR 0014). No implied phase: `fixing`
    # is appended in the fix round, while the flow is back in implement.
    "review-disposition": {
        "required": ["dispositions", "round"],
        "map_enums": {"dispositions": list(get_args(FindingState))},
        "integers": ["round"],
        "strings": ["note"],
        # A short human name beside a finding key; the key stays `<path>:<line|?>`.
        "string_maps": ["labels"],
    },
    "capture-done": {
        "required": ["promoted", "dropped"],
        "lists": ["promoted", "dropped"],
    },
    # ADR 0025: a close-out or a sweep says why the stream ended and what showed it.
    # Nothing is required, so an append of an older release still works.
    "flow-completed": {"strings": ["reason", "evidence", "url"]},
    "flow-abandoned": {"strings": ["reason", "evidence", "url"]},
}


class _GateDecisionKeys(TypedDict):
    gate: str
    question: str
    decision: str
    mode: GateMode
    raised_by: RaisedBy


class GateDecisionPayload(_GateDecisionKeys, total=False):
    """A ``gate-decision`` payload as ``normalize_payload`` leaves it (ADR 0009).

    ``decision`` is a string: a list or an object is refused at append (T010, the
    ``strings`` rule kind), so no reader ever has to stringify one. That stringifying is
    how a list-valued decision authorized in the HUD and was refused by ``mr-opened``
    (audit D6). ``raised_by`` is always present, because the shape's default fills it.
    Rows written before T010 may break any of this; readers of old rows type them as
    ``Dict[str, Any]``. ``source`` is optional: the HUD's publish dialog writes
    ``dialog``, the user's own ``!`` command writes ``shell`` (ADR 0015). The recorder
    writes ``question`` or ``prompt`` with ``request``, the seq of the go request the
    reply answers (ADR 0023). A row of 0.28.0 may still hold ``witness`` and ``words``
    of its retired read go; no reader takes them.
    """

    rationale: str
    source: DecisionSource
    request: int


class _ReviewVerdictKeys(TypedDict):
    verdict: ReviewVerdict


class ReviewVerdictPayload(_ReviewVerdictKeys, total=False):
    """A ``review-verdict`` payload as ``normalize_payload`` leaves it (ADR 0009, T016).

    ``criteria`` maps a PRD success criterion id (``SC-001``) to its status;
    ``dispositions`` maps a review finding (``<path>:<line or ?>``) to what was done with
    it. Both are optional — a verdict may judge neither — and a value outside its
    vocabulary is refused at append (the ``map_enums`` rule kind). ``style`` and
    ``ranking`` (#11, #10) are optional too; ``objects`` and ``string_lists`` check them.
    ``security_review`` (#40) is optional: which security review ran and how many files
    it read; ``check_security_review`` refuses one that read no file.
    A ``dispositions`` key that is not a location is refused (``check_location_keys``),
    and a ``ready`` verdict that leaves a folded key at ``fixing`` is refused unless
    forced with a reason (``_validate_review_verdict``, ADR 0014 amended 0.23.0).
    """

    criteria: Dict[str, CriterionStatus]
    dispositions: Dict[str, Disposition]
    style: List[str]
    ranking: "RankingPayload"
    security_review: "SecurityReviewPayload"


class _SecurityReviewKeys(TypedDict):
    kind: SecurityReviewKind


class SecurityReviewPayload(_SecurityReviewKeys, total=False):
    """`security_review` on `review-verdict` (#40): the kind, the files read, the commit."""

    files: int
    ref: str


class _ReviewDispositionKeys(TypedDict):
    dispositions: Dict[str, FindingState]
    round: int


class ReviewDispositionPayload(_ReviewDispositionKeys, total=False):
    """A ``review-disposition`` payload as ``normalize_payload`` leaves it (ADR 0014).

    ``dispositions`` maps a review finding (``<path>:<line or ?>``, as on the verdict) to
    its state now; ``round`` is the review round it belongs to. A state outside
    ``FindingState`` is refused (``map_enums``), and so is a ``round`` that is not a
    non-negative integer (``integers``). ``note`` is optional text. ``labels`` is
    optional too: it maps a finding key to a short human name, each name a non-empty
    string (``string_maps``). The name travels beside the key, never in its place.
    Every key of ``dispositions`` and ``labels`` must be a location
    (``check_location_keys``, ADR 0014 amended 0.23.0).
    """

    note: str
    labels: Dict[str, str]


class RankingFile(TypedDict, total=False):
    """One file of a risk ranking (ADR 0013); a label is null when it has no value."""

    path: str
    fix: Optional[SignalLabel]
    churn: Optional[SignalLabel]
    fan_in: Optional[SignalLabel]


class _RankingKeys(TypedDict):
    source: SignalSource


class RankingPayload(_RankingKeys, total=False):
    """`ranking` on `design-committed` and `review-verdict`, as `signals.py hotspots
    --json` prints it (ADR 0013): `files` in risk order, or `unavailable` with
    `source: none`."""

    files: List[RankingFile]
    unavailable: str

# Events that can only happen inside one phase, so appending one *is* entering it.
# ADR 0002: `append` records the transition rather than refusing the event.
PHASE_OF_EVENT: Dict[str, str] = {
    "clarify-passed": "clarify",
    "design-committed": "design",
    "design-queued": "design",
    "verify-run": "implement",
    "task-done": "implement",
    "review-verdict": "review",
    "capture-done": "capture",
}

# `actor` is `role[@label]` (ADR 0003) — the role says who decided, the label which
# session or agent.
ACTOR_ROLES = ("orchestrator", "worker", "user", "hook", "watcher")

# Types after which a stream has nothing left to report.
TERMINAL_TYPES = ("flow-completed", "flow-abandoned")

# A finished stream reopens only on an event that says work restarted. A late
# `deviation`, or a hook's `artifact-written` on a file someone reread, leaves it
# finished — otherwise a stream could never leave the brief for good.
REVIVING_TYPES = frozenset(
    {"flow-started", "flow-resumed", "phase-entered", *PHASE_OF_EVENT}
)

# Roles whose label is never a session id. The watcher runs outside any Claude session,
# so a session id would attribute its events to a session that did not write them;
# a `user` label names a person, which is why `stats` drops the label from its session
# count — defaulting a session id in would put it back and inflate that count.
SESSIONLESS_ROLES = frozenset({"watcher", "user"})

# A `user` row still runs in some session: the one that recorded the user's decision.
# `append` writes that session into the payload under this key (ADR 0010), apart from the
# actor, so `event_session` can bind the session to the stream without the label ever
# naming one. The watcher has no session to record.
RECORDED_BY_KEY = "recorded_by"
RECORDED_BY_ROLES = frozenset({"user"})

# Claude Code sets this in every shell and hook it starts, subagents' included (they get
# the parent's id). It names the session that is appending. It is the only source:
# `meta.current_session` names the one that started last, so two sessions open on one
# project would label each other's events (#46). A mod's `$.process.run` child does not
# get it; the HUD passes it in `env` when it records an approval.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"

# A `capture-done` with nothing after it is a flow that ended without saying so; give
# it two days in case review feedback lands, then treat it as finished.
CAPTURE_TERMINAL_HOURS = 48
DORMANT_DAYS = 7
# The brief marks a stream another session wrote within this many minutes (ADR 0024).
OWNERSHIP_MINUTES = 30
# The brief is injected into every session, so it pays for the last few decisions per
# stream, not for all of them, and never for a line that wraps a terminal three times.
# The stream matching the current branch is the work being resumed, so it gets the full
# five; the others are context and get three.
BRIEF_DECISION_LIMIT = 5
BRIEF_DECISION_LIMIT_OTHER = 3
BRIEF_TASK_IDS = 5
BRIEF_LINE_CHARS = 160

# The journal records state and evidence pointers; the worklog, PRD and ADRs hold the
# prose. A payload past this is a document being pasted into an event, at the writer's
# token expense on every brief that reprints it.
PAYLOAD_CAP_BYTES = 1024

# One file write reaches the journal twice — PostToolUse sees the tool call, FileChanged
# sees the same bytes land — so an observation (`disk`, or a row that names no author)
# repeating a path at the same mtime this recently is the second hook, not a second write.
ARTIFACT_DEDUPE_SECONDS = 5.0

# An authored claim (`tool`, `bash`) is a repeat only when its own session already
# claimed that write (ADR 0008). The repeat can come late: a Bash call reports when it
# ends, and Claude Code's Bash timeout tops out at 10 minutes, so the lookback covers that
# with a minute to spare. A repeat past it is a duplicate row, never a wrong author.
ARTIFACT_CLAIM_DEDUPE_SECONDS = 11 * 60.0

# Streams the tool owns. Everything else is a work stream — named for its branch
# (`fix/1290-…`) or its feature slug, both of which are legitimate.
META_STREAM = "shipgate"
WATCH_STREAM_PREFIX = "watch/"

DEFAULT_LEDGER = "docs/ledger.md"
# The knowledge-base skill's own threshold for nudging about an un-triaged ledger.
LEDGER_NUDGE_THRESHOLD = 15

# A Build Plan task line: the box, the id (bare, or bold as `**T001**` or `**T001:**`),
# then the rest of the line (`parse_build_plan`). Groups: 1 the box, 2 a bold id, 3 a bare
# id, 4 the rest.
_PLAN_TASK_RE = re.compile(
    r"^\s*[-*]\s*\[([ xX])\]\s*(?:\*\*(T\d+):?\*\*|(T\d+)\b)([^\n]*)", re.MULTILINE
)
_PLAN_HEADING_RE = re.compile(r"^#+[ \t]+(\S[^\n]*?)[ \t]*$", re.MULTILINE)
_BUILD_PLAN_RE = re.compile(r"^(#+)\s*Build Plan\s*$", re.MULTILINE | re.IGNORECASE)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class JournalError(Exception):
    """Base error carrying the process exit code to use."""

    exit_code = EXIT_INFRA


class InfraError(JournalError):
    exit_code = EXIT_INFRA


class UsageError(JournalError):
    exit_code = EXIT_USAGE


class GateViolation(JournalError):
    exit_code = EXIT_GATE


class VersionConflict(JournalError):
    exit_code = EXIT_CONFLICT

    def __init__(self, stream: str, expected: int, current: int) -> None:
        super().__init__(
            f"version conflict on stream {stream!r}: expected version {expected}, "
            f"current version is {current}"
        )
        self.stream = stream
        self.expected = expected
        self.current = current


# ADR 0011: a `route-and-map` entry without `signals` is a recorded deviation, not a
# silent pass. `append` writes it right after the entry, in the same transaction.
SIGNALS_MISSING_KIND = "signals-missing"
SIGNALS_MISSING_NOTE = (
    "route-and-map entered without a signals block: the map's risk signals were not "
    "recorded (route-and-map step 3)"
)


# The `deviation` kind that waives a Stop gate finding, and the meta key that holds the
# last recorded check (ADR 0020).
GATE_WAIVED = "gate-waived"

# ADR 0031: the evidence store of UI tasks.
SCREENS_WAIVED = "screens-waived"
# Beside DORMANT_DAYS: a constant, not a setting, because one root holds every project.
EVIDENCE_KEEP_DAYS = 30
EVIDENCE_PARTS = ("shipgate", "evidence")
# Names inside the evidence root. ASCII digits only: `\d` would accept other scripts'
# digits. Always matched with `fullmatch`.
EVIDENCE_PROJECT_RE = re.compile(r"[0-9a-f]{12}")
EVIDENCE_FILE_RE = re.compile(r"(T[0-9]+)-([0-9]+)(?:-([2-9]))?\.png")
EVIDENCE_TMP_RE = re.compile(r"\.T[0-9]+-[0-9]+(?:-[2-9])?\.png\.[0-9]+\.tmp")
TASK_ID_RE = re.compile(r"T[0-9]+")

# ADR 0032 and ADR 0033: the run log of the Bash hooks. A session's files go this many
# days after their last write, and a `verify-run` append reads at most this much of them.
RUNS_KEEP_DAYS = 7
RUNS_READ_BYTES = 1024 * 1024
# The keys of a `verify-run` the journal owns (ADR 0033): set at append from the run log,
# after the cap check, like RECORDED_BY_KEY; a caller's own value never survives.
OBSERVED_KEY = "observed"
CONTRADICTED_KEY = "contradicted"


CLOSEOUT_QUESTION_PLACEHOLDER = "<the close-out question>"
CLOSEOUT_CHOSEN_PLACEHOLDER = "<the steps the user chose>"
