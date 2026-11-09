#!/usr/bin/env python3
"""shipgate lean config: remove the template's explanation text from a project config.

Python 3 standard library only. See ADR 0019 and ``shipgate/docs/prd/shipgate-0.25.0.md``
(FR-013, SC-005). The placeholder rule comes from ``_config.py`` (loaded by path), so this
script and the config readers agree on what a placeholder is.

The script parses a config into blocks: a heading, an HTML comment, a bullet with its
continuation lines, a paragraph, a fenced code block and blank lines. An anchor selects a
block for a check:

- a comment whose whitespace-normalised text starts with a comment anchor in ``ANCHORS``;
- a paragraph or a comment whose text starts with a prose anchor;
- a bullet whose text starts with a bullet anchor;
- a bullet whose key is ``Executive contract``.

A selected block is removed only when every sentence in it is catalogued boilerplate: it
equals a sentence in ``BOILERPLATE_SENTENCES`` or matches a ``BOILERPLATE_PATTERNS`` entry.
A selected block with any other sentence stays whole and is reported as mixed, with a hint
for the edit to make by hand. The catalogue holds every prose sentence of the current
template, of its earlier versions, of the header and contract that ``setup`` wrote, and of
the known ``Executive contract`` paraphrases. A bullet whose value is an angle-bracket
placeholder, such as ``- Mode: <ask | executive>``, is removed when none of its nested
bullets holds a real value.

Then it removes the residue. The ``---`` rule after the title goes when every block between
the title and the rule went. A ``##`` heading goes when its section lost a block and has no
other content left. A run of blank lines that touches a removal collapses to one, or to
none at the start or the end of the file.

A block that matches no anchor stays. An edited anchor is a keep. A mixed block is a kept
block for every residue rule. A ``- Key: value`` bullet with a real value stays. The title
line, fenced code, and a comment with text after its ``-->`` always stay. With ``--apply``,
the mixed blocks are reported at their line numbers in the written file.

With ``--user <path>``, the script reports each ``##`` section whose body equals the same
section in the user file, after it removes comments and collapses whitespace.
``--drop-equal`` removes those sections, heading included. With ``--umbrella <path>``
(repeatable), an equal section that an umbrella file holds present is shadowed: it is
reported and never dropped, because the umbrella's section would replace it. A project
file with ``Inherit: none`` has no umbrella, so nothing is shadowed. ``--only-equal`` leaves
the boilerplate alone and handles only the equal sections. The summary's block count leaves
the dropped sections out; ``--json`` lists every removal.

The script prints a summary line and a unified diff. It writes the file only with
``--apply``, through a temporary file in the same directory, and keeps each kept line's
line ending. A second run on its own output finds nothing to remove.

Exit codes (also printed by ``--help``):

    0  ok, whether or not there is anything to remove
    1  infrastructure failure (the file cannot be read or written, or the install is
       incomplete)
    2  usage error (missing file, bad flag)
"""

from __future__ import annotations

import argparse
import difflib
import errno
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Set, Tuple, Union

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

EXIT_OK = 0
EXIT_INFRA = 1
EXIT_USAGE = 2


def _load_config_module():
    """The config reader shared with `signals.py` and `journal.py`, loaded by path:
    `scripts/` is not a package. Without it there is no placeholder rule, so the script
    stops with an infrastructure error (exit 1), as `journal.py` does.
    """
    import importlib.util

    path = Path(__file__).resolve().parent / "_config.py"
    try:
        spec = importlib.util.spec_from_file_location("shipgate_config", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    except (OSError, ImportError) as exc:
        sys.exit(f"error: cannot load {path} (shipgate install incomplete): {exc}")
    return module


_config = _load_config_module()

COMMENT = "comment"  # an anchor for an HTML comment only
PROSE = "prose"  # an anchor for a paragraph or a comment
BULLET = "bullet"  # an anchor for a bullet's text, marker stripped

# The anchor catalogue: (block kind, normalised prefix). Add a new boilerplate form here.
ANCHORS: List[Tuple[str, str]] = [
    # The template's header and the header `setup` wrote before 0.25.0.
    (PROSE, "Copy this file into your project as"),
    (PROSE, "Every section is **optional**"),
    (PROSE, "Division of labor with `CLAUDE.md`"),
    (PROSE, "Subagents don't read this file themselves"),
    (PROSE, "Project configuration for the `shipgate` plugin."),
    # The 0.25.0 template's header. The layer list is one paragraph block: its items are
    # consecutive lines, and the anchor holds the first two so a hand-written list stays.
    (PROSE, "**How the config files layer.**"),
    (PROSE, "1. the repo's `.claude/shipgate.md`; 2. the umbrella's `.claude/shipgate.md`"),
    (PROSE, "1. the repo's `.claude/shipgate.md` files, from the working directory up to the "
            "repo root; 2. the umbrella's `.claude/shipgate.md`"),
    (PROSE, "The config is resolved per section."),
    (PROSE, "A nested config can take nothing from the umbrella."),
    (PROSE, "The user file uses the same section vocabulary"),
    (PROSE, "Subagents don't read these files themselves"),
    (PROSE, "`setup` writes a lean file"),
    # Per-section comments. Short leads, so a paragraph that opens the same way stays.
    (COMMENT, "Default when absent"),
    (COMMENT, "Only needed for umbrella"),
    (COMMENT, "Usually personal: belongs in the user file"),
    (COMMENT, "Read by `shipgate/scripts/signals.py`"),
    (COMMENT, "Read by `scripts/signals.py`"),
    (COMMENT, "Read by `signals.py`"),
    # Journal.
    (PROSE, "When this section is present the project is **journaled**"),
    (BULLET, "**Position is recorded, not guessed.**"),
    (BULLET, "**Recording is enforced by the plugin's hooks**"),
    (BULLET, "**Capture is enforced by the plugin's hooks**"),
    (BULLET, "**The database is local, disposable state.**"),
    (PROSE, "**The journal does not replace the ledger.**"),
    (PROSE, "**Event names and payload shapes are a fixed vocabulary.**"),
    (PROSE, "**Event names are a fixed vocabulary.**"),
    (PROSE, "**One stream per issue, named for its branch**"),
    (PROSE, "Dial enforcement down by setting"),
    # Code signals, Worker guardrails, Orchestration.
    (PROSE, "The one section a script reads rather than the model"),
    (PROSE, "Hard rules for anyone editing this repo"),
    (PROSE, "`workflow` runs that phase's fan-out"),
    (PROSE, "Degradation is automatic and never blocks"),
    # MR watcher.
    (BULLET, "If declared, two skills honor it"),
    (BULLET, "The watcher is strictly read-only"),
    (BULLET, "Optional, when a **Journal** is configured"),
]

PLACEHOLDER = "placeholder"
EXECUTIVE_CONTRACT = "executive-contract"
EMPTY_SECTION = "empty-section"
RULE = "rule"
EQUAL_TO_USER = "equal-to-user"

HINT_CONTRACT = "add the extra cases to an Extra escalations line, then delete this bullet"
HINT_PROSE = "move the project sentences to their own paragraph or section"

# The catalogue of boilerplate sentences, normalised by `normalise_sentence`. Generated
# from the sources the module docstring names; a template edit adds its new sentences here.
BOILERPLATE_SENTENCES = frozenset({
    'A <placeholder> counts as absent',
    'A Ranking exclude value replaces the built-in ranking excludes',
    "A large lens plugin costs skill-listing space in every session — descriptions get truncated past the listing's budget and stop triggering — so install and map only what you need",
    'A nested config can take nothing from the umbrella',
    "A project file that declares this section replaces the user file's section whole, so repeat the Library docs line there when you add a project line",
    'A section is present when its heading exists and it holds at least one value that is not an angle-bracket placeholder',
    'A section present in a nearer file replaces the farther one whole',
    'A section with placeholders only, or with no bullets, is absent, and the next layer shows through',
    'An absent section falls back to the next layer below, and in the end to the default noted per section',
    'An empty value (``) turns them off',
    "An epic's children are separate branches and so separate streams; a stream carrying two issues has a phase, a gate history and a verdict that describe neither of them",
    'Artifact inference is not a fallback here — a missing event reads as "still in the previous phase" until it is recorded',
    "Capture is enforced by the plugin's hooks, not by remembering: artifact writes are recorded automatically, and a session cannot end while an expected event is missing",
    'Copy this file into your project as `.claude/shipgate.md` and fill in what applies',
    'Copy this file into your project as `.claude/shipgate.md` and fill in what applies, or run `/shipgate:setup`',
    'Default when absent: 12-month window, the built-in fix pattern (conventional-commit fix types + fix/bug/hotfix/revert/regression words), the built-in excludes (vendor, node_modules, dist, build, lockfiles, generated)',
    'Default when absent: 12-month window, the built-in fix pattern (conventional-commit fix types + fix/bug/hotfix/revert/regression words), the built-in excludes (vendor, node_modules, dist, build, lockfiles, generated), and the built-in ranking excludes (/CHANGELOG.md, /.claude-plugin/plugin.json, .claude-plugin/marketplace.json)',
    'Default when absent: PRDs to docs/prd/, ADRs to docs/adr/, worklogs beside the PRD as <name>.worklog.md — plain markdown committed to the repo; knowledge capture to repo docs; no wiki',
    'Default when absent: `<type>/<issue-id>-<slug>`, type ∈ feat | fix | chore, branched off the detected integration branch',
    'Default when absent: `agents` for both — the hand-driven Agent fan the skills have always used',
    "Default when absent: `ask` — every gate question goes to the user, exactly the skills' built-in behavior",
    'Default when absent: auth, secrets, payments — the built-in judgment',
    'Default when absent: detect from `git remote get-url origin` — github.com → gh + PRs, gitlab → glab + MRs',
    'Default when absent: epics are driven issue-by-issue with a stop (merge + go-ahead) between issues; decomposition is manual; design-ahead depth 1-2',
    'Default when absent: library docs from a context7-style MCP (resolve a library id, then query its docs) when the session has one, else training knowledge / WebFetch; no LSP preference (grep/read); code graph `auto`',
    'Default when absent: local logs, failing tests, debugger; browser via chrome-devtools if present',
    'Default when absent: match surrounding code; no extra skill invoked',
    'Default when absent: no journal — phase is inferred from artifact shape (checkbox state, [NEEDS CLARIFICATION] markers) exactly as shipgate has always worked',
    "Default when absent: no lens skills are invoked — the phase skills apply each lens inline (each names it where it's used, with the condition it applies under)",
    "Default when absent: no lens skills are invoked — the phase skills apply each lens's idea inline (each describes it in one line where it's used)",
    'Default when absent: no library-docs integration (training knowledge / WebFetch); no LSP preference (grep/read)',
    'Default when absent: no library-docs integration (training knowledge / WebFetch); no LSP preference (grep/read); code graph `auto`',
    'Default when absent: no project-specific guardrails',
    'Default when absent: no project-specific guardrails — worker briefs carry only the built-in discipline from `model-tiers` (branch check, no commit/staging, evidence in the report)',
    'Default when absent: no watcher — the flow ends at "MR opened" and resumes only when the user asks',
    'Default when absent: no watcher — the flow ends at "MR/PR opened" and resumes only when the user asks',
    'Default when absent: plain — the documents shipgate writes into this repo and forge (PRD, ADR, worklog, ledger lines, MR/PR body, tracker comments) keep the prose style they have today',
    'Default: the working directory is the repo',
    'Defaults when absent: 12-month window, built-in fix pattern, built-in excludes',
    'Degradation is automatic and never blocks: when the `Workflow` tool is unavailable in the harness or the user refuses the call, the phase runs its `agents` path and records a `deviation` event',
    'Degradation is automatic and never blocks: when the `Workflow` tool is unavailable in the host or the user refuses the call, the phase runs its `agents` path and records a `deviation` event',
    "Delete what you don't need",
    "Delete what you don't need; anything absent falls back to the defaults noted per section",
    'Dial enforcement down by setting `enforce.stop_gate` or `enforce.auto_capture` to false in the sidecar (both default true)',
    "Division of labor with `CLAUDE.md`: the repo's `CLAUDE.md` files stay the source of truth for routing and code conventions (where code belongs, build/test commands); this file carries the process tooling — where artifacts live, which forge/tracker, branch naming, which integrations to reach for",
    "Division of labor with `CLAUDE.md`: the repo's `CLAUDE.md` files stay the source of truth for routing and code conventions: where code belongs, build and test commands",
    "Don't duplicate CLAUDE.md content here",
    "Don't park a learning in the journal — it is machine-local and gitignored, so anything durable left there is lost to your teammates and to your next machine",
    'Each line here is an instruction the skills follow verbatim',
    'Event names and payload shapes are a fixed vocabulary',
    'Event names are a fixed vocabulary',
    'Every section is optional',
    'Every worker brief still carries the built-in worker discipline block in the `model-tiers` skill, word for word: branch check, no commit or staging, the git index, no --no-verify, no repo-wide formatter, stop and report, comments, evidence in the report',
    'Extra escalations add cases to it',
    'For each `##` section, the nearest file where the section is present supplies the whole section',
    'Gitignore it (`shipgate.db`); the artifacts in git or your wiki remain the portable record',
    'Hard rules for anyone editing this repo, written to be pasted verbatim into every worker brief — `model-tiers` requires them word-for-word, because a summarized guardrail is a broken one',
    'How the config files layer',
    'If a bot runs a shipgate phase, it runs it on the host',
    'If declared, two skills honor it',
    'If that sidecar is absent, every hook exits immediately and the project behaves as un-journaled',
    'Issue context read via whatever CLI/MCP is available',
    'It holds what is personal and the same in every project',
    'It is prose the model reads, not parsed config',
    'It still escalates one-way doors (schema, public API, shared write paths, data migrations), user-visible scope changes, and genuine 50/50s',
    'It still escalates: one-way doors (schema, public API, shared write paths, data migrations), user-visible scope changes, anything in Security-sensitive areas, and genuine 50/50s where it cannot form a recommendation',
    'It still escalates: one-way doors, user-visible scope changes, anything in Security-sensitive areas above, and genuine 50/50s where it cannot form a recommendation',
    'It suggests; the user triggers every resume',
    "It's prose read by the model, not parsed config — write it the way you'd brief a new teammate",
    'Keep entries short and imperative',
    'Keep entries short and imperative — each line here is an instruction the skills will follow verbatim',
    'Map it: reviewer comments → the review-feedback cycle (defined in the `review` skill); own MR merged → residual ledger triage only — the main capture already ran when review passed (then next epic child, if any); watched MR merged → resume the held work per its note; conflicts / failed CI → fix before review continues',
    'Map it: reviewer comments → the review-feedback cycle (defined in the `review` skill); own MR/PR merged → residual ledger triage only — the main Capture already ran when review passed (then the next child issue, if any); a watched one merged → resume the held work per its note; conflicts / failed CI → fix before review continues',
    'Map it: reviewer comments → the review-feedback cycle (defined in the `review` skill); own MR/PR merged → residual ledger triage only — the main capture already ran when review passed (then next epic child, if any); a watched one merged → resume the held work per its note; conflicts / failed CI → fix before review continues',
    'Moving machines degrades to un-journaled behavior unless you carry it over with `journal.py export` / `import`',
    'Neither is cheaper than the `agents` path — the fan-out itself is the cost, and the gain is structure, dedupe and context hygiene',
    "Never mount it into a container: the journal runs in SQLite's WAL mode, which needs filesystem locks a bind mount doesn't provide, and because WAL is a property of the file the breakage outlives the container (recover with `PRAGMA journal_mode=DELETE` from the host)",
    'Never repeat a built-in rule here',
    'One imperative line per rule, no rationale, no grouping',
    'One stream per issue, named for its branch (`fix/1290-date-off-by-one`)',
    'Only needed for umbrella / multi-repo checkouts',
    "Optional, when a Journal is configured: a watcher may append what it observes to `watch/<project>!<iid>` streams via the plugin's `journal.py` (`baseline`, `pipeline-flip`, `comments-added`, `merge-status`, `conflicts`, `approved`, `merged`, `closed`)",
    'Pass `--new-type` to mint a genuinely new concept on purpose',
    'Phase transitions, gate decisions, verify evidence, and review verdicts are appended as events; `feature` routes from the journal alone',
    'Position is recorded, not guessed',
    'Project configuration for the `shipgate` plugin',
    "Recording is enforced by the plugin's hooks, not by remembering: artifact writes are auto-captured, and the Stop hook blocks a session from ending while an expected event is missing",
    'Review additionally sends its top-severity findings to refuters that must cite the line disproving them (capped, and off for the rest); explore just runs its lenses in parallel and merges their essential files',
    'Run `journal.py doctor` when anything looks stale',
    "Say what you're registering as you do it",
    'Sections never merge line by line',
    'Skills read this at the start of a flow; it overrides their built-in defaults',
    'So write sections to be liftable on their own',
    'Stream names are free: `feature/<slug>` or the branch (`fix/1290-date-off-by-one`) both work',
    "Subagents don't read these files themselves",
    "Subagents don't read this file themselves — the dispatching skill pastes the relevant excerpt into each brief",
    "Suggestion, not a requirement — a watcher that doesn't do this still works exactly as described above",
    'The Library docs line is the personal one',
    "The comments in this template and the README explain each section; a project's config does not repeat them",
    'The config carries the process tooling: where artifacts live, which forge and tracker, branch naming, which integrations to reach for',
    'The config is resolved per section',
    "The contract is the plugin's, so this section never restates it",
    'The database is local, disposable state',
    'The dispatching skill pastes the relevant excerpt into each brief, so write each section to be liftable on its own',
    'The fan still happens, just the old way',
    'The hooks read `.claude/shipgate.json` (a generated sidecar holding the database path, the artifact-home globs, and the ledger path) — `setup` writes it; never hand-edit it, re-run `setup` instead',
    'The journal does not replace the ledger',
    'The journal holds operational state and is never emptied',
    'The layers, nearest first',
    'The ledger holds prose learnings mid-flow and is deliberately lossy — entries are promoted to a durable home or dropped at triage, then removed, so an empty ledger is the healthy steady state',
    'The note must name the held work AND its next action (e.g. "unblocks #1234 — rebase + open the request"), so the unblock event arrives as an instruction, not trivia',
    "The one section a script reads rather than the model: `scripts/signals.py` takes these four bullets' backticked values (command-line flags still win), so the terminal and the flow compute the same numbers",
    "The one section a script reads rather than the model: `scripts/signals.py` takes these three bullets' backticked values (command-line flags still win), so the terminal and the flow compute the same numbers",
    'The sections marked "Usually personal" below belong there',
    "The sidecar does carry the ledger's path, so `status` can report how many untriaged entries are waiting; that is the `knowledge-base` skill's ~15-entry nudge made mechanical, and it is information only — the ledger never gates a session",
    'The skills read the config at the start of a flow and treat it as overriding their built-in defaults',
    'The user file and the built-in defaults still apply',
    'The user file uses the same section vocabulary as this template',
    'The watcher is strictly read-only',
    "This header and the README's Configuration section are the two homes of the rule; every skill cites them",
    'This is how shipgate adapts to a project without forking the plugin',
    'This is how shipgate adapts to a project without forking the plugin: the skills read this file at the start of a flow and treat it as overriding their built-in defaults',
    'This section adds the rules only this repo needs',
    'This section is written by `/shipgate:setup`; you rarely hand-write it',
    'This section overrides that with a lens skill to invoke, e.g. one from cc-thinking-skills (https://github.com/tjboudreaux/cc-thinking-skills)',
    'To do that, put the line `Inherit: none` under its title, before the first section (bare or as a bullet, backticks optional, any case)',
    'Triage still writes learnings to the stores above; the journal only records that it happened, as a `capture-done` event',
    'Usually personal: belongs in the user file',
    'Values must be in backticks; a <placeholder> counts as absent',
    'Watchers typically keep a single overwritten snapshot file, so a missed or crashed tick loses the intervening history; journalling makes the snapshot a cache and the history reconstructable',
    'When this section is present the project is journaled, and three things change',
    'Write it the way you would brief a new teammate',
    "`agents` keeps every subagent's full report inline, which costs context but leaves all of the judgment in the orchestrator's context",
    "`agents` keeps every subagent's full report inline, which costs context but leaves all of the judgment in the session",
    '`executive`: the orchestrator answers routine gate questions itself, records them and escalates the rest, by the executive contract in the `feature` skill',
    '`journal.py doctor` reports any off-vocabulary events already in a journal',
    '`journal.py vocab` lists the types, `vocab --shape <type>` prints the payload each one takes, and `append` refuses anything else — an event named something plausible-but-unlisted is inert: it records, and no gate or report ever reads it, which looks like success',
    '`journal.py vocab` lists them and `append` refuses anything else, because an event named something plausible-but-unlisted is inert — it records, and no gate or report ever reads it, which looks like success',
    '`setup` writes a lean file: a one-line title and `- Key: value` bullets only, with no comments and no prose that explains the plugin',
    '`ste-80` applies the same "Writing for people" rule the reports to the person driving the flow already follow: sentences of about 20 words with one idea each, common words, one term per concept, one action per step, every fact kept',
    "`workflow` runs that phase's fan-out through the `Workflow` tool and a script bundled with the plugin: the fan becomes deterministic (fixed lenses, in-script dedupe) and the raw reviewer/explorer reports never land in the orchestrator's context — findings come back schema-typed and deduped across lenses, and the coordinator reads only that return",
    "`workflow` runs that phase's fan-out through the `Workflow` tool and a script bundled with the plugin: the fan becomes deterministic (fixed lenses, in-script dedupe) and the raw reviewer/explorer reports never land in the orchestrator's context — findings come back schema-typed and deduped across lenses, and the orchestrator reads only that return",
    'feature, resume detection: a watcher event naming an issue is a valid resume trigger',
    "review, after opening the MR/PR: if this work is now blocked on someone else's request, or has follow-up work gated on this one merging, register it with the watcher's watch list",
    "review, after opening the MR: if this work is now blocked on someone else's MR, or has follow-up work gated on this MR merging, register it with the watcher's watch list",
    'the built-in defaults noted per section',
    'the orchestrator makes and RECORDS routine decisions itself (clarify answers in the PRD\'s "Assumptions (executive)" list, design choices in the ADR) and reports them so the user can veto',
    'the orchestrator makes and RECORDS routine decisions itself — clarify answers land in the PRD\'s "Assumptions (executive)" list — and reports them in each phase summary so the user can veto',
    'the orchestrator makes and RECORDS routine decisions itself — clarify answers land in the PRD\'s "Assumptions (executive)" list, design choices in the ADR, small calls in the ledger — and reports them in each phase summary so the user can veto',
    'the orchestrator makes and RECORDS routine decisions itself — clarify answers land in the PRD\'s "Assumptions (executive)" list, design choices in the ADR, small calls in the ledger — and reports them in each phase summary so they can be vetoed',
    'the orchestrator makes and RECORDS routine decisions itself — design choices in the ADR — and reports them in the phase summary so the user can veto',
    "the repo's `.claude/shipgate.md` files, from the working directory up to the repo root",
    "the umbrella's `.claude/shipgate.md`, in an umbrella checkout",
    'the user file: `$CLAUDE_CONFIG_DIR/shipgate.md` when that variable is set and not empty, else `~/.claude/shipgate.md`',
})

# Catalogued sentences with a variable part, matched whole against a normalised sentence.
BOILERPLATE_PATTERNS = [
    # The header `setup` wrote before 0.25.0, with the date it ran.
    re.compile(r"Written by `/shipgate:setup` on \d{4}-\d{2}-\d{2} — re-run it to change the "
               r"journal or artifact homes rather than hand-editing those"),
    # The Code signals comment `setup` wrote, with the version tag of its time.
    re.compile(r"Read by `shipgate/scripts/signals\.py` itself \(v\d+\.\d+\+\): backticked "
               r"values only, flags win"),
    # Templates up to 0.10.0 named a real branch and issue here; the numbers stay out of
    # this repo, so the shape is catalogued instead.
    re.compile(r"Stream names are free: `feature/<slug>` or the branch \(`fix/\d+-[a-z0-9-]+`\) "
               r"both work"),
    re.compile(r'The note must name the held work AND its next action \(e\.g\. "unblocks #\d+ '
               r'— rebase \+ open MR"\), so the unblock event arrives as an instruction, not '
               r'trivia'),
]

HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]|$)")
RULE_RE = re.compile(r"^ {0,3}-{3,}[ \t]*$")
BULLET_RE = re.compile(r"^[ \t]*[-*+][ \t]+")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
# A closing fence is the bare marker: a line with an info string does not close it.
FENCE_CLOSE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")
# A bare `Inherit:` line always starts its own block, so it never joins a removed paragraph.
INHERIT_RE = re.compile(r"^[ \t]*`?inherit`?[ \t]*:", re.I)
COMMENT_SPAN_RE = re.compile(r"<!--.*?-->", re.S)
SPACE_RE = re.compile(r"\s+")
# The `Executive contract` key, with optional emphasis and a parenthesis, up to its colon.
CONTRACT_KEY_RE = re.compile(r"^[*`\s]*executive contract[*`]*\s*(?:\([^()]*\))?[*`\s]*:[*`]*",
                             re.I)
LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+\Z")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
ORDERED_ITEM_RE = re.compile(r"^\s*\d+[.)]\s+")
EMPHASIS_RE = re.compile(r"\*+|(?<!\w)_+|_+(?!\w)")
NO_SPLIT_RE = re.compile(r"(?:^|\W)(?:e\.g|i\.e|vs)\.$", re.I)
TRAILING_PUNCT_RE = re.compile(r"[\s.;:,!?]+$")


class Block(NamedTuple):
    kind: str  # heading | comment | bullet | paragraph | fence | rule | blank
    start: int  # 0-based line index
    end: int  # 0-based, inclusive
    text: str  # normalised text, markers stripped; a bullet's own text, nested bullets out
    level: int  # heading level; 0 for any other kind
    removable: bool  # False for an unclosed comment or one with text after its `-->`
    subs: Tuple[str, ...]  # a bullet's nested bullets, each normalised, markers stripped
    body: str  # the raw text the sentences come from: comment markers and bullet marker out


class Removal(NamedTuple):
    start: int  # 0-based line index
    end: int  # 0-based, inclusive
    kind: str
    anchor: str


class Mixed(NamedTuple):
    start: int  # 0-based line index
    end: int  # 0-based, inclusive
    kind: str
    anchor: str
    hint: str


class Plan(NamedTuple):
    removals: List[Removal]
    mixed: List[Mixed]
    equal_sections: List[str]
    shadowed_sections: List[str]
    result: str
    before: List[str]  # the lines without their endings, for the diff
    after: List[str]
    new_line: Dict[int, int]  # a kept line's 0-based index → its index in the result


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def normalise(text: str) -> str:
    return SPACE_RE.sub(" ", text).strip()


def split_lines(text: str) -> List[str]:
    """The lines of TEXT, each with its own line ending (the last may have none)."""
    return LINE_RE.findall(text)


def _starts_block(line: str) -> bool:
    stripped = line.lstrip()
    return bool(
        FENCE_RE.match(line) or HEADING_RE.match(line) or RULE_RE.match(line)
        or stripped.startswith("<!--") or BULLET_RE.match(line) or INHERIT_RE.match(line)
    )


def _comment(lines: Sequence[str], start: int) -> Tuple[Optional[int], str, bool]:
    """(end line or None when unclosed, inner text, nothing after `-->`)."""
    opening = lines[start].index("<!--") + 4
    for j in range(start, len(lines)):
        close = lines[j].find("-->", opening if j == start else 0)
        if close < 0:
            continue
        if j == start:
            body = lines[start][opening:close]
        else:
            body = "\n".join([lines[start][opening:]] + list(lines[start + 1:j])
                             + [lines[j][:close]])
        return j, body, not lines[j][close + 3:].strip()
    return None, "", False


def _bullet_parts(first: str, rest: Sequence[str]) -> Tuple[str, Tuple[str, ...]]:
    own: List[str] = [first]
    subs: List[List[str]] = []
    for line in rest:
        if not line.strip():
            continue
        nested = BULLET_RE.match(line)
        if nested:
            subs.append([line[nested.end():]])
        elif subs:
            subs[-1].append(line)
        else:
            own.append(line)
    return normalise("\n".join(own)), tuple(normalise("\n".join(s)) for s in subs)


def _continues(line: str) -> bool:
    return (line[:1] in (" ", "\t") and not line.lstrip().startswith("<!--")
            and not FENCE_RE.match(line))


def _bullet_end(lines: Sequence[str], start: int) -> int:
    """The index after the bullet at START: its indented continuation lines, across
    blank lines while the next non-blank line is indented deeper than the marker."""
    indent = _indent(lines[start])
    j = start + 1
    while j < len(lines):
        if lines[j].strip():
            if not _continues(lines[j]):
                break
            j += 1
            continue
        k = j
        while k < len(lines) and not lines[k].strip():
            k += 1
        if k == len(lines) or not _continues(lines[k]) or _indent(lines[k]) <= indent:
            break
        j = k
    return j


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def parse_blocks(lines: Sequence[str]) -> List[Block]:
    """Blocks over LINES, which carry no line endings."""
    blocks: List[Block] = []
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        if not line.strip():
            blocks.append(Block("blank", i, i, "", 0, False, (), ""))
            i += 1
            continue
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            j = i + 1
            while j < n:
                close = FENCE_CLOSE_RE.match(lines[j])
                if close and close.group(1)[0] == marker[0] and len(close.group(1)) >= len(marker):
                    break
                j += 1
            end = min(j, n - 1)
            blocks.append(Block("fence", i, end, "", 0, False, (), ""))
            i = end + 1
            continue
        heading = HEADING_RE.match(line)
        if heading:
            title = line.strip()[len(heading.group(1)):].strip().rstrip("#")
            blocks.append(Block("heading", i, i, normalise(title), len(heading.group(1)),
                                False, (), ""))
            i += 1
            continue
        if RULE_RE.match(line):
            blocks.append(Block("rule", i, i, "", 0, False, (), ""))
            i += 1
            continue
        if line.lstrip().startswith("<!--"):
            end, body, clean = _comment(lines, i)
            if end is None:
                # An unclosed comment hides the rest of the file; never remove it.
                blocks.append(Block("comment", i, n - 1, "", 0, False, (), ""))
                break
            blocks.append(Block("comment", i, end, normalise(body), 0, clean, (), body))
            i = end + 1
            continue
        bullet = BULLET_RE.match(line)
        if bullet:
            j = _bullet_end(lines, i)
            text, subs = _bullet_parts(line[bullet.end():], lines[i + 1:j])
            body = "\n".join([line[bullet.end():]] + list(lines[i + 1:j]))
            blocks.append(Block("bullet", i, j - 1, text, 0, True, subs, body))
            i = j
            continue
        j = i + 1
        while j < n and lines[j].strip() and not _starts_block(lines[j]):
            j += 1
        body = "\n".join(lines[i:j])
        blocks.append(Block("paragraph", i, j - 1, normalise(body), 0, True, (), body))
        i = j
    return blocks


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def is_placeholder_bullet(text: str) -> bool:
    """True when a bullet's text is a placeholder (`<e.g. …>`) or its value after the
    first `:` is one (`Mode: <ask | executive>`), by `_config.is_placeholder_value`."""
    if _config.is_placeholder_value(text):
        return True
    if ":" not in text:
        return False
    return _config.is_placeholder_value(text.split(":", 1)[1])


def is_executive_contract(text: str) -> bool:
    return CONTRACT_KEY_RE.match(text) is not None


def normalise_sentence(sentence: str) -> str:
    """Whitespace collapsed, one pair of surrounding backticks and the trailing
    punctuation dropped. Emphasis markers are gone before the split."""
    sentence = normalise(sentence)
    if len(sentence) >= 2 and sentence[0] == sentence[-1] == "`" and sentence.count("`") == 2:
        sentence = sentence[1:-1]
    return TRAILING_PUNCT_RE.sub("", sentence)


def _split(text: str) -> List[str]:
    """Split on `.`, `!` or `?` before a space and an uppercase letter, a backtick, `*`,
    `(`, `[` or a digit; never inside backticks, never after `e.g.`, `i.e.` or `vs.`."""
    parts: List[str] = []
    start = 0
    code = False
    for i, char in enumerate(text):
        if char == "`":
            code = not code
        elif char in ".!?" and not code and text[i + 1:i + 2] == " ":
            following = text[i + 2:i + 3]
            if following and (following.isupper() or following.isdigit()
                              or following in "`*([") \
                    and not NO_SPLIT_RE.search(text[start:i + 1]):
                parts.append(text[start:i + 1])
                start = i + 2
    parts.append(text[start:])
    return parts


def sentences(body: str) -> List[str]:
    """The normalised sentences of BODY. A list item starts on its own line; an ordered
    one (`1. the repo's …`) is one sentence."""
    items: List[List] = []
    for line in body.split("\n"):
        if not line.strip():
            continue
        item = LIST_ITEM_RE.match(line)
        if item:
            items.append([bool(ORDERED_ITEM_RE.match(line)), line[item.end():]])
        elif items:
            items[-1][1] += "\n" + line
        else:
            items.append([False, line])
    out: List[str] = []
    for ordered, text in items:
        text = normalise(EMPHASIS_RE.sub("", text))
        for part in ([text] if ordered else _split(text)):
            sentence = normalise_sentence(part)
            if sentence:
                out.append(sentence)
    return out


def is_catalogued(sentence: str) -> bool:
    return sentence in BOILERPLATE_SENTENCES or any(
        pattern.fullmatch(sentence) for pattern in BOILERPLATE_PATTERNS)


def select(block: Block) -> Optional[str]:
    """The anchor that selects BLOCK for the sentence check, `executive-contract`, or
    None."""
    if block.kind in ("paragraph", "comment"):
        if not block.removable:
            return None
        kinds = (COMMENT, PROSE) if block.kind == "comment" else (PROSE,)
        for kind, anchor in ANCHORS:
            if kind in kinds and block.text.startswith(anchor):
                return anchor
        return None
    if block.kind == "bullet":
        for kind, anchor in ANCHORS:
            if kind == BULLET and block.text.startswith(anchor):
                return anchor
        if is_executive_contract(block.text):
            return EXECUTIVE_CONTRACT
    return None


def block_sentences(block: Block, anchor: str) -> List[str]:
    """The sentences of a selected block; the `Executive contract` bullet's key is out."""
    if anchor == EXECUTIVE_CONTRACT:
        key = CONTRACT_KEY_RE.match(block.body)
        return sentences(block.body[key.end():] if key else block.body)
    return sentences(block.body)


def classify(block: Block) -> Tuple[Optional[str], bool]:
    """(label, removed). (None, False) keeps an unselected block; (anchor, False) keeps a
    mixed one; (label, True) removes the block."""
    anchor = select(block)
    if anchor == EXECUTIVE_CONTRACT and is_placeholder_bullet(block.text):
        return PLACEHOLDER, True
    if anchor is not None:
        return anchor, all(is_catalogued(s) for s in block_sentences(block, anchor))
    if block.kind == "bullet" and is_placeholder_bullet(block.text) \
            and all(is_placeholder_bullet(s) for s in block.subs):
        return PLACEHOLDER, True
    return None, False


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------


def _section_spans(blocks: Sequence[Block]) -> List[Tuple[int, int]]:
    """(heading block index, end block index exclusive) for each `##` section."""
    spans = []
    for bi, block in enumerate(blocks):
        if block.kind != "heading" or block.level != 2:
            continue
        end = bi + 1
        while end < len(blocks) and not (blocks[end].kind == "heading" and blocks[end].level <= 2):
            end += 1
        spans.append((bi, end))
    return spans


def section_bodies(lines: Sequence[str], blocks: Sequence[Block]) -> List[Tuple[str, int, int, str]]:
    """(name, heading block index, end block index exclusive, normalised body) per section."""
    out = []
    for head, end in _section_spans(blocks):
        first = blocks[head].end + 1
        last = blocks[end - 1].end if end - 1 > head else blocks[head].end
        body = "\n".join(lines[first:last + 1])
        out.append((blocks[head].text, head, end, normalise(COMMENT_SPAN_RE.sub(" ", body))))
    return out


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


def _title_index(blocks: Sequence[Block]) -> Optional[int]:
    for bi, block in enumerate(blocks):
        if block.kind == "heading":
            return bi if block.level == 1 else None
    return None


CUT = -1  # where a removed range stood, in the render list


def _render(raw: Sequence[str], blocks: Sequence[Block],
            removed: Set[int]) -> List[Optional[int]]:
    """The kept line indices; None stands for an added blank line. A run of blank lines
    that touches a removal collapses to one blank line, or to none at the start or the end
    of the file; every other run stays. A removal with no blank line around it, between
    two paragraphs, leaves one blank line so the paragraphs do not join."""
    blank = {b.start for b in blocks if b.kind == "blank"}
    kind_of: Dict[int, str] = {}
    for block in blocks:
        for i in range(block.start, block.end + 1):
            kind_of[i] = block.kind
    items: List[int] = []
    for i in range(len(raw)):
        if i in removed:
            if not items or items[-1] != CUT:
                items.append(CUT)
        else:
            items.append(i)
    out: List[Optional[int]] = []
    k = 0
    while k < len(items):
        if items[k] != CUT and items[k] not in blank:
            out.append(items[k])
            k += 1
            continue
        run_end = k
        while run_end < len(items) and (items[run_end] == CUT or items[run_end] in blank):
            run_end += 1
        run = items[k:run_end]
        blanks = [i for i in run if i != CUT]
        if CUT not in run:
            out.extend(blanks)
        elif blanks and out and run_end < len(items):
            out.append(blanks[0])
        elif out and run_end < len(items) and out[-1] is not None \
                and kind_of[out[-1]] == "paragraph" and kind_of[items[run_end]] == "paragraph":
            out.append(None)
        k = run_end
    return out


def _boilerplate(blocks: Sequence[Block]) -> Tuple[Dict[int, Tuple[str, str]], List[Mixed]]:
    """Block index → (kind, anchor) for each catalogued or placeholder block and its
    residue; and the mixed blocks, which stay."""
    title = _title_index(blocks)
    marks: Dict[int, Tuple[str, str]] = {}
    mixed: List[Mixed] = []
    for bi, block in enumerate(blocks):
        if bi == title:
            continue
        anchor, removed = classify(block)
        if anchor is None:
            continue
        if removed:
            marks[bi] = (block.kind, anchor)
        else:
            hint = HINT_CONTRACT if anchor == EXECUTIVE_CONTRACT else HINT_PROSE
            mixed.append(Mixed(block.start, block.end, block.kind, anchor, hint))

    first = title + 1 if title is not None else 0
    for bi in range(first, len(blocks)):
        if blocks[bi].kind == "heading":
            break
        if blocks[bi].kind == "rule":
            between = [x for x in range(first, bi) if blocks[x].kind != "blank"]
            if between and all(x in marks for x in between):
                marks[bi] = ("rule", RULE)
            break

    for head, end in _section_spans(blocks):
        content = [x for x in range(head + 1, end) if blocks[x].kind != "blank"]
        if content and all(x in marks for x in content):
            marks[head] = ("heading", EMPTY_SECTION)
    return marks, mixed


def plan(text: str, user_text: Optional[str] = None, drop_equal: bool = False,
         umbrella_texts: Sequence[str] = (), only_equal: bool = False) -> Plan:
    """ONLY_EQUAL leaves the boilerplate alone: only the sections equal to the user
    file's are reported, and removed with DROP_EQUAL."""
    raw = split_lines(text)
    lines = [line.rstrip("\r\n") for line in raw]
    blocks = parse_blocks(lines)
    marks, mixed = ({}, []) if only_equal else _boilerplate(blocks)

    removals = [Removal(blocks[bi].start, blocks[bi].end, kind, anchor)
                for bi, (kind, anchor) in marks.items()]

    equal_sections: List[str] = []
    shadowed_sections: List[str] = []
    if user_text is not None:
        user_lines = [line.rstrip("\r\n") for line in split_lines(user_text)]
        user_bodies: Dict[str, str] = {}
        for name, _h, _e, body in section_bodies(user_lines, parse_blocks(user_lines)):
            user_bodies.setdefault(name.lower(), body)
        # `Inherit: none` drops the umbrella's files, so no umbrella section shadows.
        if _config.inherit_mode(text) == _config.INHERIT_NONE:
            umbrella_texts = ()
        for name, head, end, body in section_bodies(lines, blocks):
            if not body or user_bodies.get(name.lower()) != body:
                continue
            equal_sections.append(name)
            if any(_config.section_present(u, name.lower()) for u in umbrella_texts):
                shadowed_sections.append(name)
                continue
            if not drop_equal:
                continue
            last = head
            for x in range(head + 1, end):
                if blocks[x].kind != "blank":
                    last = x
            start, stop = blocks[head].start, blocks[last].end
            removals = [r for r in removals if r.end < start or r.start > stop]
            mixed = [m for m in mixed if m.end < start or m.start > stop]
            removals.append(Removal(start, stop, "section", EQUAL_TO_USER))

    removals.sort(key=lambda r: r.start)
    if not removals:
        return Plan([], mixed, equal_sections, shadowed_sections, text, lines, lines,
                    {i: i for i in range(len(lines))})
    removed: Set[int] = set()
    for r in removals:
        removed.update(range(r.start, r.end + 1))
    kept = _render(raw, blocks, removed)
    out: List[str] = []
    after: List[str] = []
    new_line: Dict[int, int] = {}
    for position, i in enumerate(kept):
        if i is not None:
            new_line[i] = position
        if i is None:
            previous = kept[position - 1]
            assert previous is not None
            out.append(raw[previous][len(lines[previous]):])
            after.append("")
        else:
            out.append(raw[i])
            after.append(lines[i])
    return Plan(removals, mixed, equal_sections, shadowed_sections, "".join(out), lines, after,
                new_line)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def unified_diff(path: str, result: Plan) -> str:
    if result.before == result.after:
        return ""
    lines = difflib.unified_diff(result.before, result.after,
                                 fromfile="a/" + path, tofile="b/" + path, lineterm="")
    return "\n".join(lines) + "\n"


def summary(result: Plan, with_user: bool, with_umbrella: bool) -> str:
    blocks = [r for r in result.removals if r.anchor != EQUAL_TO_USER]
    line = "lean_config: {} block(s) to remove".format(len(blocks))
    if with_user:
        line += ", {} section(s) equal to the user file".format(len(result.equal_sections))
    if with_umbrella and result.shadowed_sections:
        line += ", {} shadowed by the umbrella".format(len(result.shadowed_sections))
    if result.mixed:
        line += ", {} mixed block(s) kept".format(len(result.mixed))
    return line


def written_mixed(result: Plan) -> List[Mixed]:
    """The mixed blocks at their line numbers in the result; a mixed block is kept whole."""
    return [m._replace(start=result.new_line[m.start], end=result.new_line[m.end])
            for m in result.mixed]


def mixed_lines(mixed: Sequence[Mixed]) -> List[str]:
    return ["mixed: lines {}-{} ({}) — {}".format(m.start + 1, m.end + 1, m.anchor, m.hint)
            for m in mixed]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lean_config.py",
        description="Remove the template's explanation text from a shipgate config. "
                    "A block goes only when every sentence in it is catalogued "
                    "boilerplate; a block that also holds project sentences stays and is "
                    "listed as mixed, with a hint. Prints a summary, the mixed blocks and "
                    "a unified diff; writes only with --apply.",
        epilog="exit codes: 0 ok (whether or not anything changes), 1 the file cannot be "
               "read or written, or the install is incomplete, 2 usage error",
    )
    parser.add_argument("path", help="the config file, e.g. .claude/shipgate.md")
    parser.add_argument("--apply", action="store_true", help="write the result to the file")
    parser.add_argument("--user", metavar="PATH",
                        help="the user file; report sections equal to its sections")
    parser.add_argument("--drop-equal", action="store_true",
                        help="with --user, remove the sections equal to the user file's")
    parser.add_argument("--only-equal", action="store_true",
                        help="with --user, leave the boilerplate alone: only the sections "
                             "equal to the user file's are reported (or dropped)")
    parser.add_argument("--umbrella", metavar="PATH", action="append", default=[],
                        help="an umbrella config (repeatable); an equal section it holds "
                             "present is shadowed and never dropped")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    return parser


def _read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def write_atomic(path: str, content: str) -> None:
    """Replace PATH's content through a temporary file in its directory. A file without
    write permission is refused, not replaced. The new file keeps the old file's mode, but
    it belongs to the current user, and a hard link to the old file is split."""
    target = os.path.realpath(path)
    if not os.access(target, os.W_OK):
        raise PermissionError(errno.EACCES, "file is not writable", target)
    mode = stat.S_IMODE(os.stat(target).st_mode)
    fd, tmp = tempfile.mkstemp(prefix=".lean_config-", dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.drop_equal and not args.user:
        parser.error("--drop-equal needs --user")
    if args.only_equal and not args.user:
        parser.error("--only-equal needs --user")
    given: List[str] = [args.path] + ([args.user] if args.user else []) + list(args.umbrella)
    for name in given:
        if not Path(name).is_file():
            print("error: no such file: {}".format(name), file=sys.stderr)
            return EXIT_USAGE
    try:
        text = _read(args.path)
        user_text = _read(args.user) if args.user else None
        umbrella_texts = [_read(name) for name in args.umbrella]
    except (OSError, UnicodeDecodeError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return EXIT_INFRA

    result = plan(text, user_text, args.drop_equal, umbrella_texts, args.only_equal)
    changed = result.result != text
    diff = unified_diff(args.path, result)

    mixed = result.mixed
    if args.apply and changed:
        try:
            write_atomic(args.path, result.result)
        except OSError as exc:
            print("error: {}".format(exc), file=sys.stderr)
            return EXIT_INFRA
        mixed = written_mixed(result)

    if args.json:
        report: Dict[str, Union[str, bool, list]] = {
            "path": args.path,
            "removals": [{"start": r.start + 1, "end": r.end + 1, "kind": r.kind,
                          "anchor": r.anchor} for r in result.removals],
            "equal_sections": result.equal_sections,
            "shadowed_sections": result.shadowed_sections,
            "mixed": [{"start": m.start + 1, "end": m.end + 1, "kind": m.kind,
                       "anchor": m.anchor, "hint": m.hint} for m in mixed],
            "changed": changed,
            "diff": diff,
        }
        print(json.dumps(report, sort_keys=True, indent=2))
        return EXIT_OK
    print(summary(result, args.user is not None, bool(args.umbrella)))
    for line in mixed_lines(mixed):
        print(line)
    if diff and not args.apply:
        sys.stdout.write(diff)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
