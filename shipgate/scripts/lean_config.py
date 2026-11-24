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

``--move-settings <root>`` (ADR 0028) moves the legacy lines out of the configs into the
settings files. A legacy line is a ``- Key: value`` bullet that a schema key names in its
``x-legacy``. The parse is the resolver's own (``_config.legacy_lines``,
``_config.legacy_value``). The script reads the project config
``<root>/.claude/shipgate.md``, the config of each nested repo
(``_config.nested_repo_dirs``), and the user config. A nested repo with its own settings
file is a project of its own: the script skips it and says so.

- A line in the project config or a nested config goes to the project settings file
  ``<root>/.claude/shipgate.json``. A line in the user config goes to the user settings
  file, when its key has the scope ``any``.
- A user line that moves gets a note: a project whose own section hid that line takes
  the user's value after the move.
- A user line with a ``project`` key stays in the user config, because other projects
  still read it. Its value is copied into the project settings file only when that line
  set the key for this project before the move.
- A nested value now applies to every repo, and a note says so. Nested values that differ
  from each other, or from the value at the root, stay where they are (a conflict).
- A line whose value does not parse stays, and the script names it.
- A key that the target settings file sets already keeps that value. The line goes, and a
  note shows a different value.
- The ``Ledger``, ``PRD home``, ``ADR home`` and ``Worklog home`` bullets are legacy lines
  too (``_config.legacy_home``), but the script never writes them into a settings file,
  because the hooks would act on the value. A bullet of the project config goes only
  when the key resolves to the same value without it: the value the project settings
  file sets, else the default. A bullet with another value, or with no repo path, stays
  and is named. A bullet that goes takes its other words with it, and a note says so,
  except a ``Ledger`` bullet whose other text starts with the promotion targets: that
  text stays, as a ``- Promotion targets:`` bullet. Such a bullet in a nested or user
  config stays and is named.
- The project config's ``Database`` bullet goes, after a note shows how it differs from
  ``db``. One that holds more than its value stays whole.
- The residue rules above apply. A comment right under a removed bullet, and indented
  deeper, goes with it.
- A settings file keeps its keys and their order. New keys follow in schema order, an
  object gains its new leaves, and ``version`` becomes 2. A new project settings file
  starts with ``"version": 2, "db": null``: the project has no journal, and a note says so.
- Parity: from the root and from each nested repo, every setting resolves to the same
  value after the move as before, except ``version`` and a value that the project
  settings file now sets for every repo. Each other directory below the root with a
  config (a scan of at most 6 levels and 2,000 directories, with a note when it stops)
  keeps every value: a key whose value would change there keeps every line. A home or
  the ledger is never pinned: a bullet whose removal would change its value anywhere
  stays. A config section that hid a user line before
  gets its value pinned in the project settings file, with a note. When a value still
  differs, the script writes nothing and exits 1.

The script refuses (exit 1) when ``.claude``, ``shipgate.json`` or ``shipgate.md`` of the
project, or ``.claude`` or ``shipgate.md`` of a nested repo, is a symlink or resolves
outside the project root, and when the project settings file is a user file. It writes a
project-side file only as itself, never through a symlink; the user files may be links.
It refuses (exit 2) a root with no settings file below a directory that holds one: the
hooks take that directory as the project root.

The script prints a summary line, the notes, the lines that stay with the reason, and a
diff per file (a new file diffs from ``/dev/null``). A value from a config shows on one
line, a character that does not print shows as ``?``, and a value is at most 120
characters. A diff header names a path below the root relative to it, and a user file
with ``~`` for the home directory. ``--json`` prints ``{files, moved,
kept, notes, changed}``. With ``--apply`` it writes the settings files first, then the
configs, each through a temporary file in its directory. It never creates a directory.
A second run on the result changes nothing.

Exit codes (also printed by ``--help``):

    0  ok, whether or not there is anything to remove
    1  infrastructure failure (a file cannot be read or written, a settings file is no
       JSON object, a project file is a symlink, a move would change a setting, or the
       install is incomplete)
    2  usage error (missing file, bad flag, a root below a project root), or a settings
       file with a version this shipgate does not write
"""

from __future__ import annotations

import argparse
import collections
import difflib
import errno
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import (
    Any, Dict, FrozenSet, List, NamedTuple, Optional, Sequence, Set, Tuple, Union,
)

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
    # The header's settings paragraph since the config split (ADR 0028).
    (PROSE, "**Settings live in the settings files, not here.**"),
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
    (BULLET, "Optional, on a journaled project"),
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
    "After a design-committed append, and after a not-ready review verdict, the PostToolUse hook reads this session's context size from its transcript",
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
    'Default when absent: `Handoff: 500k`',
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
    'Default when absent: the close-out runs its built-in steps only',
    'Default: the working directory is the repo',
    'Defaults when absent: 12-month window, built-in fix pattern, built-in excludes',
    'Degradation is automatic and never blocks: when the `Workflow` tool is unavailable in the harness or the user refuses the call, the phase runs its `agents` path and records a `deviation` event',
    'Degradation is automatic and never blocks: when the `Workflow` tool is unavailable in the host or the user refuses the call, the phase runs its `agents` path and records a `deviation` event',
    "Delete what you don't need",
    "Delete what you don't need; anything absent falls back to the defaults noted per section",
    'Dial enforcement down by setting `enforce.stop_gate` or `enforce.auto_capture` to false in the sidecar (both default true)',
    'Dial enforcement down by setting `enforce.stop_gate`, `enforce.auto_capture` or `enforce.command_gate` to false in the sidecar (all three default true)',
    'With `enforce.command_gate` false, a model commits, pushes and opens an MR/PR with no recorded go from the user; an unattended project, which has no user to answer, needs that',
    "Division of labor with `CLAUDE.md`: the repo's `CLAUDE.md` files stay the source of truth for routing and code conventions (where code belongs, build/test commands); this file carries the process tooling — where artifacts live, which forge/tracker, branch naming, which integrations to reach for",
    "Division of labor with `CLAUDE.md`: the repo's `CLAUDE.md` files stay the source of truth for routing and code conventions: where code belongs, build and test commands",
    "Don't duplicate CLAUDE.md content here",
    "Don't park a learning in the journal — it is machine-local and gitignored, so anything durable left there is lost to your teammates and to your next machine",
    'Each line here is an instruction the skills follow verbatim',
    "Each step here waits for the user's one answer: a project's steps are arbitrary commands, so none runs with no question",
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
    'Map it: reviewer comments → the review-feedback cycle (defined in the `review` skill); own MR/PR merged → the close-out (`journal.py closeout`), whose first step is the residual ledger triage (then the next child issue, if any); a watched one merged → resume the held work per its note; conflicts / failed CI → fix before review continues',
    'Moving machines degrades to un-journaled behavior unless you carry it over with `journal.py export` / `import`',
    'Neither is cheaper than the `agents` path — the fan-out itself is the cost, and the gain is structure, dedupe and context hygiene',
    "Never mount it into a container: the journal runs in SQLite's WAL mode, which needs filesystem locks a bind mount doesn't provide, and because WAL is a property of the file the breakage outlives the container (recover with `PRAGMA journal_mode=DELETE` from the host)",
    'Never repeat a built-in rule here',
    'One imperative line per rule, no rationale, no grouping',
    'One stream per issue, named for its branch (`fix/1290-date-off-by-one`)',
    'Only needed for umbrella / multi-repo checkouts',
    "Optional, when a Journal is configured: a watcher may append what it observes to `watch/<project>!<iid>` streams via the plugin's `journal.py` (`baseline`, `pipeline-flip`, `comments-added`, `merge-status`, `conflicts`, `approved`, `merged`, `closed`)",
    'Pass `--new-type` to mint a genuinely new concept on purpose',
    'Past the threshold it adds one line that recommends a fresh session from the handoff brief (`journal.py handoff`)',
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
    'The value is a token count such as `500k`, `1m` or `300000`, or `off`',
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
    '`journal.py closeout` lists these steps after the update of the integration branch and before the report',
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
    # The template since the config split (ADR 0028): settings live in the settings files.
    'Settings live in the settings files, not here',
    'A setting is a value from a fixed set, such as `autonomy`, `writing_style` or `artifact_homes`',
    'Settings live in `.claude/shipgate.json` (the project settings file) and in `$CLAUDE_CONFIG_DIR/shipgate.settings.json`, else `~/.claude/shipgate.settings.json` (the user settings file)',
    "`journal.py config` prints each one with its source, and the README's Configuration section lists them all",
    'This file holds behaviour in words',
    'The config carries the process tooling in words: the knowledge stores, the tracker, branch naming, which integrations to reach for',
    'Default when absent: knowledge capture to repo docs; no wiki',
    'The PRD, ADR and worklog homes and the ledger path are settings (`artifact_homes`, `ledger`)',
    'Default when absent: issue context read via whatever CLI/MCP is available',
    'The forge itself is the `forge` setting: `github` (gh, PRs) or `gitlab` (glab, MRs); unset, the host of the PR/MR URL or of the git remote decides',
    "Optional, on a journaled project: a watcher may append what it observes to `watch/<project>!<iid>` streams via the plugin's `journal.py` (`baseline`, `pipeline-flip`, `comments-added`, `merge-status`, `conflicts`, `approved`, `merged`, `closed`)",
    'Default when absent: library docs from a context7-style MCP (resolve a library id, then query its docs) when the session has one, else training knowledge / WebFetch; no LSP preference (grep/read)',
    'The code graph is the `code_graph` setting',
    'Default when absent: no extra escalations',
    'The mode is the `autonomy` setting: `ask` (the default) sends every gate question to the user; `executive` lets the orchestrator answer routine gate questions itself, record them and escalate the rest, by the executive contract in the `feature` skill',
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
    result, after, new_line = _without(raw, lines, blocks, removed)
    return Plan(removals, mixed, equal_sections, shadowed_sections, result, lines, after,
                new_line)


def _without(raw: Sequence[str], lines: Sequence[str], blocks: Sequence[Block],
             removed: Set[int], replaced: Optional[Dict[int, Tuple[int, str]]] = None
             ) -> Tuple[str, List[str], Dict[int, int]]:
    """(the text without the REMOVED line indices, its lines without endings, a kept
    line's index → its index in the result). The blank-line rules of `_render` apply,
    and each kept line keeps its own line ending. REPLACED maps a block's first line to
    (its last line, the new text of the block, line endings included)."""
    replaced = replaced or {}
    swallowed = {i for start, (end, _text) in replaced.items() for i in range(start + 1, end + 1)}
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
        elif i in replaced:
            text = replaced[i][1]
            out.append(text)
            after.extend(line.rstrip("\r\n") for line in split_lines(text))
        elif i not in swallowed:
            out.append(raw[i])
            after.append(lines[i])
    return "".join(out), after, new_line


# --------------------------------------------------------------------------
# --move-settings (ADR 0028): legacy lines move into the settings files
# --------------------------------------------------------------------------

KIND_PROJECT = "project"
KIND_NESTED = "nested"
KIND_USER = "user"

REASON_NO_PARSE = "does not parse"
REASON_CONFLICT = "conflict"
REASON_PROSE = "holds prose"
REASON_PROJECT_KEY = ("a project setting: the user config keeps it for other projects until "
                      "the grace date")
REASON_DUPLICATE = "more than one bullet for this key"
REASON_NOT_LOCATED = "cannot be removed safely: edit it by hand"
REASON_NO_PROJECT_DIR = "no .claude directory at the project root for the settings file"
REASON_NO_USER_DIR = "no directory for the user settings file"
REASON_NO_REPO_PATH = ("gives no repo path that a setting can hold (a wiki, or words): keep "
                       "it as words, or set {} in .claude/shipgate.json by hand")
REASON_NOT_SET = ("differs from the default and the settings file does not set {0}: set {0} "
                  "to {1} in .claude/shipgate.json, or delete the line")
ECHO_CHARS = 120

# The bullets whose value a settings file holds already: (section, bullet, setting). No
# reader reads them, so they never go into a settings file; the settings file, or its
# default, wins today.
SETTINGS_BULLETS = (
    ("Journal", "Database", "db"),
    ("Knowledge base", "Ledger", "ledger"),
    ("Knowledge base", "PRD home", "artifact_homes.prd"),
    ("Knowledge base", "ADR home", "artifact_homes.adr"),
    ("Knowledge base", "Worklog home", "artifact_homes.worklog"),
)
LEDGER = "ledger"
PROMOTION_KEY = "Promotion targets"

# A `- Key: value` bullet as `_config.section_bullets` reads it.
KEY_BULLET_RE = re.compile(r"^\s*[-*+]\s+([^:]+?)\s*:\s*(.*)$")
VALUE_SPAN_RE = re.compile(r"`[^`\n]*`")
VALUE_NOTE_RE = re.compile(r"[ \t]*\([^()]*\)")
LEAD_PUNCT_RE = re.compile(r"^[\s.,;:—–-]+")
PROMOTION_LEAD_RE = re.compile(r"promotion targets\b[^:\n]{0,60}:[ \t]*", re.I)


class MoveError(Exception):
    """A refusal: CODE is the exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


class Source(NamedTuple):
    """A config that the move reads and may edit."""
    path: Path
    kind: str  # project | nested | user
    text: str  # as read, line endings kept
    raw: List[str]  # the lines with their endings
    lines: List[str]  # the lines without endings
    blocks: List[Block]


class Line(NamedTuple):
    """A legacy line whose value parses, and the blocks its removal takes."""
    source: Source
    key: str
    section: str
    bullet: str
    raw: str  # the value as written
    value: Any
    cut: FrozenSet[int]  # block indices


class Moved(NamedTuple):
    key: str
    from_path: str
    section: str
    bullet: str
    value: str
    to: str


class Kept(NamedTuple):
    path: str
    section: str
    bullet: str
    value: str
    reason: str


class MovePlan(NamedTuple):
    # {path, changed, created, diff}: the configs, then the settings files
    files: List[Dict[str, Any]]
    moved: List[Moved]
    kept: List[Kept]
    notes: List[str]
    # (path, content, created, trusted): the settings files first. Only a user file may be
    # reached through a symlink.
    writes: List[Tuple[str, str, bool, bool]]


def _echo(value: Any, limit: int = ECHO_CHARS) -> str:
    """A value from a checkout, as a note or a kept line shows it: on one line, each
    character that does not print shown as `?`, at most LIMIT characters."""
    flat = _printable(" ".join(str(value).split()))
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


def _printable(text: str) -> str:
    return "".join(c if c.isprintable() else "?" for c in text)


def _shown(value: Any) -> str:
    return _echo(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))


def _header_path(path: Path, root: Path) -> Tuple[str, bool]:
    """(PATH as a diff header names it, whether it lies below ROOT): relative to ROOT
    below it, else with `~` for the home directory, else absolute."""
    absolute = os.path.abspath(str(path))
    base = os.path.abspath(str(root))
    if absolute.startswith(base.rstrip(os.sep) + os.sep):
        return os.path.relpath(absolute, base), True
    home = os.path.expanduser("~")
    if home != "~" and absolute.startswith(home.rstrip(os.sep) + os.sep):
        return "~/" + os.path.relpath(absolute, home), False
    return absolute, False


def _inside(path: Path, root_real: str) -> bool:
    real = os.path.realpath(str(path))
    return real == root_real or real.startswith(root_real.rstrip(os.sep) + os.sep)


def _refuse_link(path: Path, root_real: str) -> None:
    """MoveError (exit 1) when PATH is a symlink, or resolves outside the project root:
    a checkout could point a write at a file outside it."""
    if os.path.islink(str(path)) or (os.path.lexists(str(path))
                                     and not _inside(path, root_real)):
        raise MoveError("{} is a symlink or resolves outside the project root {}; "
                        "--move-settings writes nothing through it. Replace it with the "
                        "file itself, then run this again".format(path, root_real),
                        EXIT_INFRA)


def _ancestor_project(root: Path) -> Optional[str]:
    """The nearest directory above ROOT that holds `.claude/shipgate.json`: the walk of
    the hooks (`hooks/_common.journaled_root`)."""
    current = os.path.abspath(str(root))
    while True:
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
        if os.path.isfile(os.path.join(current, _config.SETTINGS_RELPATH)):
            return current


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _real(path: Path) -> str:
    return os.path.realpath(str(path))


def _strip_path(value: str) -> str:
    while value.startswith("./"):
        value = value[2:]
    return value.rstrip("/")


def _leaf_keys(schema: Dict[str, Any]) -> List[str]:
    """Every leaf key of the schema, `group.leaf` for an object, in schema order."""
    out: List[str] = []
    for key, node in schema["properties"].items():
        if node.get("type") == "object" and "properties" in node:
            out.extend(key + "." + leaf for leaf in node["properties"])
        else:
            out.append(key)
    return out


def _sets(data: Optional[Dict[str, Any]], key: str) -> bool:
    """True when a settings file's DATA decides KEY: it holds the key, or holds its group
    as a value that is no object (the resolver then refuses the whole group)."""
    if data is None:
        return False
    group, _, leaf = key.partition(".")
    if not leaf:
        return key in data
    return group in data and (not isinstance(data[group], dict) or leaf in data[group])


def _setting(data: Optional[Dict[str, Any]], key: str) -> Any:
    if data is None:
        return None
    group, _, leaf = key.partition(".")
    value = data.get(group)
    if not leaf:
        return value
    return value.get(leaf) if isinstance(value, dict) else value


def _merged(data: Optional[Dict[str, Any]], writes: Dict[str, Any],
            schema: Dict[str, Any], no_journal: bool) -> Dict[str, Any]:
    """DATA with WRITES added: its keys keep their order, new keys follow in schema order,
    an object gains leaves, and `version` is the schema's. A new file starts with
    `version`, and with `"db": null` when NO_JOURNAL."""
    newest = schema.get("x-version", 2)
    if data is None:
        out: Dict[str, Any] = {"version": newest}
        if no_journal:
            out["db"] = None
    elif "version" in data:
        out = dict(data)
        out["version"] = newest
    else:
        out = {"version": newest}
        out.update(data)
    for key in _leaf_keys(schema):
        if key not in writes:
            continue
        group, _, leaf = key.partition(".")
        if leaf:
            sub = dict(out[group]) if isinstance(out.get(group), dict) else {}
            sub[leaf] = writes[key]
            out[group] = sub
        else:
            out[key] = writes[key]
    return out


def _read_settings(path: Optional[Path], newest: int
                   ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(the JSON object, the text) of a settings file; (None, None) when there is none.
    MoveError: exit 1 when it cannot be read as a JSON object, 2 when its version is no
    version or one this shipgate does not write."""
    if path is None or not os.path.lexists(str(path)):
        return None, None
    if not os.path.isfile(str(path)):
        raise MoveError("{} is not a file".format(path), EXIT_INFRA)
    try:
        with open(str(path), "rb") as handle:
            content = handle.read()
    except OSError as exc:
        raise MoveError("{}: {}".format(path, exc.strerror or exc), EXIT_INFRA)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise MoveError("{} is not valid UTF-8".format(path), EXIT_INFRA) from None
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise MoveError("{} is not valid JSON: {}".format(path, exc), EXIT_INFRA) from None
    if not isinstance(data, dict):
        raise MoveError("{} must contain a JSON object".format(path), EXIT_INFRA)
    version = data.get("version", newest)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise MoveError("{}: version = {} is not a version (an integer of 1 or more)".format(
            path, json.dumps(version)), EXIT_USAGE)
    if version > newest:
        raise MoveError("{} declares version {}; this shipgate writes version {}. Update "
                        "shipgate, then run this again.".format(path, version, newest),
                        EXIT_USAGE)
    return data, text


def _source(path: Path, kind: str) -> Source:
    try:
        text = _read(str(path))
    except (OSError, UnicodeDecodeError) as exc:
        raise MoveError("{}: {}".format(path, exc), EXIT_INFRA) from None
    raw = split_lines(text)
    lines = [line.rstrip("\r\n") for line in raw]
    return Source(path, kind, text, raw, lines, parse_blocks(lines))


def _sources(root: Path, user_config: Optional[Path], notes: List[str]
             ) -> Tuple[List[Source], List[Path]]:
    """The configs the move reads, each once: the project's, each nested repo's (`_config.
    nested_repo_dirs`), the user's. And the nested repos whose config is read. MoveError
    for a nested config reached through a symlink."""
    root_real = os.path.realpath(str(root))
    found: List[Source] = []
    seen: Set[str] = set()

    def add(path: Path, kind: str) -> bool:
        if not path.is_file() or _real(path) in seen:
            return False
        found.append(_source(path, kind))
        seen.add(_real(path))
        return True

    add(root / _config.CONFIG_RELPATH, KIND_PROJECT)
    repos: List[Path] = []
    for repo in _config.nested_repo_dirs(root):
        config = repo / _config.CONFIG_RELPATH
        if not os.path.lexists(str(config)):
            continue
        _refuse_link(repo / ".claude", root_real)
        _refuse_link(config, root_real)
        if not config.is_file():
            continue
        if os.path.lexists(str(repo / _config.SETTINGS_RELPATH)):
            notes.append("skipped {}: it holds its own settings file, so it is a project of "
                         "its own; run --move-settings there".format(repo))
            continue
        if add(config, KIND_NESTED):
            repos.append(repo)
    if user_config is not None:
        add(user_config, KIND_USER)
    return found, repos


def _candidates(root: Path, start: Path) -> List[Tuple[Path, str]]:
    """journal.py's layer list (`_journal/project.config_candidates`) from START, a
    directory at or below ROOT: each config from START up to the repo that holds it is a
    project file, then the configs of that repo's parent and of the root are umbrella
    files. With no repo below the root, every config from START up to the root is a
    project file."""
    chain = [start]
    while chain[-1] != root and chain[-1].parent != chain[-1]:
        chain.append(chain[-1].parent)
    repo = next((d for d in chain if os.path.lexists(str(d / ".git"))), None)
    if repo is None or repo == root:
        return [(d / _config.CONFIG_RELPATH, _config.ROLE_PROJECT) for d in chain]
    candidates = [(d / _config.CONFIG_RELPATH, _config.ROLE_PROJECT)
                  for d in chain[:chain.index(repo) + 1]]
    for directory in dict.fromkeys((repo.parent, root)):
        candidates.append((directory / _config.CONFIG_RELPATH, _config.ROLE_UMBRELLA))
    return candidates


def _disk_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
    except OSError:
        return None


def _section_blocks(blocks: Sequence[Block], section: str) -> List[int]:
    """The block indices of the section SECTION (lower-case) as `_config._walk_section`
    reads it: from the first heading with that name, of any level, to the next heading of
    its level or higher. A deeper heading that repeats the name moves that end."""
    inside = False
    level = 0
    out: List[int] = []
    for bi, block in enumerate(blocks):
        if block.kind == "heading":
            if inside and block.level <= level:
                break
            if block.text.lower() == section:
                inside, level = True, block.level
                continue
        if inside:
            out.append(bi)
    return out


def _bullet_key(line: str) -> Optional[str]:
    match = KEY_BULLET_RE.match(line)
    return match.group(1).strip().lower() if match else None


def _the_bullet(source: Source, section: str, bullet: str) -> Optional[int]:
    """The block of the one top-level `- <bullet>:` bullet of SECTION; None when there is
    none, more than one, or it holds a comment marker."""
    blocks, lines = source.blocks, source.lines
    hits = [bi for bi in _section_blocks(blocks, section.lower())
            if blocks[bi].kind == "bullet"
            and _bullet_key(lines[blocks[bi].start]) == bullet.lower()]
    if len(hits) != 1:
        return None
    block = blocks[hits[0]]
    if any("<!--" in lines[i] or "-->" in lines[i] for i in range(block.start, block.end + 1)):
        return None
    return hits[0]


def _reads_as(before: str, after: str, section: str, bullet: str,
              new_key: Optional[str] = None) -> bool:
    """True when AFTER reads, by `_config.section_bullets`, as BEFORE with its one BULLET
    of SECTION gone, or, with NEW_KEY, replaced by one NEW_KEY bullet with a value."""
    old = _config.section_bullets(before, section.lower(), keep_case=True)
    new = _config.section_bullets(after, section.lower(), keep_case=True)
    at = [i for i, (key, _value) in enumerate(old) if key.lower() == bullet.lower()]
    if len(at) != 1:
        return False
    i = at[0]
    if new_key is None:
        return new == old[:i] + old[i + 1:]
    if any(key.lower() == new_key.lower() for key, _value in old) or len(new) != len(old):
        return False
    return (new[i][0] == new_key and bool(new[i][1].strip())
            and new[:i] + new[i + 1:] == old[:i] + old[i + 1:])


def _bullet_cut(source: Source, section: str, bullet: str) -> Optional[FrozenSet[int]]:
    """The blocks that the removal of the one BULLET of SECTION takes: the bullet, and
    each closed comment right under it and indented deeper (a continuation). None when
    the bullet is not one whole block, or its removal would change another bullet."""
    bi = _the_bullet(source, section, bullet)
    if bi is None:
        return None
    blocks, lines = source.blocks, source.lines
    cut = {bi}
    indent = _indent(lines[blocks[bi].start])
    j = bi + 1
    while (j < len(blocks) and blocks[j].kind == "comment" and blocks[j].removable
           and blocks[j].start == blocks[j - 1].end + 1
           and _indent(lines[blocks[j].start]) > indent):
        cut.add(j)
        j += 1
    removed = {i for x in cut for i in range(blocks[x].start, blocks[x].end + 1)}
    trial = "".join(line for i, line in enumerate(source.raw) if i not in removed)
    return frozenset(cut) if _reads_as(source.text, trial, section, bullet) else None


def _after_value(block_text: str, bullet: str) -> Optional[Tuple[str, str]]:
    """(the marker, the text after the value) of a `- <bullet>: value …` block. The
    value is its first backticked span, else its first word. A note in parentheses right
    after the value goes with it, and so does the punctuation that follows. None when
    text comes before the value."""
    head = re.match(r"([ \t]*[-*+][ \t]+)" + re.escape(bullet) + r"[ \t]*:[ \t]*",
                    block_text, re.I)
    if head is None:
        return None
    rest = block_text[head.end():]
    span = VALUE_SPAN_RE.match(rest)
    if span:
        after = rest[span.end():]
    elif "`" in rest:
        return None
    else:
        word = re.match(r"\S+", rest)
        after = rest[word.end():] if word else rest
    note = VALUE_NOTE_RE.match(after)
    if note:
        after = after[note.end():]
    return head.group(1), LEAD_PUNCT_RE.sub("", after)


def _promotion_bullet(marker: str, prose: str) -> Optional[str]:
    """The `- Promotion targets: …` bullet that holds PROSE, which starts with
    "Promotion targets" and its lead-in (`Promotion targets at triage:`); None when
    nothing follows the lead-in."""
    lead = PROMOTION_LEAD_RE.match(prose)
    body = prose[lead.end():] if lead else prose[len(PROMOTION_KEY):].lstrip(" \t")
    if not LEAD_PUNCT_RE.sub("", body).strip():
        return None
    return marker + PROMOTION_KEY + ":" + ("" if body[:1] in ("\r", "\n") else " ") + body


def _settings_bullet_change(source: Source, section: str, bullet: str
                            ) -> Tuple[str, Any]:
    """What happens to a bullet that a settings file holds: ("cut", blocks) when it
    holds only its value; ("replace", {first line: (last line, text)}) for a Ledger
    bullet whose prose starts with the promotion targets; ("prose", None) when it holds
    other prose or nested bullets, which stay; ("locate", None) when it cannot be
    changed safely."""
    bi = _the_bullet(source, section, bullet)
    if bi is None:
        return "locate", None
    block = source.blocks[bi]
    block_text = "".join(source.raw[block.start:block.end + 1])
    split = _after_value(block_text, bullet)
    if split is None:
        return "prose", None
    marker, prose = split
    if not prose.strip():
        cut = _bullet_cut(source, section, bullet)
        return ("cut", cut) if cut is not None else ("locate", None)
    if bullet.lower() != LEDGER or not prose.lower().startswith(PROMOTION_KEY.lower()):
        return "prose", None
    text = _promotion_bullet(marker, prose)
    if text is None:
        return "prose", None
    trial = "".join(source.raw[:block.start]) + text + "".join(source.raw[block.end + 1:])
    if not _reads_as(source.text, trial, section, bullet, PROMOTION_KEY):
        return "prose", None
    return "replace", {block.start: (block.end, text)}


def _db_difference(where: str, value: str, data: Optional[Dict[str, Any]],
                   schema: Dict[str, Any]) -> Optional[str]:
    """The note on how a `Database` bullet's VALUE differs from `db` in the project
    settings file's DATA (or its default); None when they agree."""
    if data is None:
        return "{}: the project has no settings file, so it has no journal; the bullet " \
               "goes".format(where)
    current = data["db"] if "db" in data else schema["properties"]["db"]["default"]
    if current is None:
        return "{} differs from db null in the project settings file: the project has no " \
               "journal; the bullet goes".format(where)
    if isinstance(current, str) and _strip_path(value) == _strip_path(current):
        return None
    return "{} differs from db {} in the project settings file; the settings file wins, and " \
           "the bullet goes".format(where, _shown(current))


def _text_diff(header: Tuple[str, bool], old: Optional[str], new: str) -> str:
    """A unified diff of OLD (None for a file that does not exist) to NEW. HEADER is
    `_header_path`'s: a path below the root gets the `a/` and `b/` prefixes."""
    name, below = _printable(header[0]), header[1]
    before = [] if old is None else [line.rstrip("\r\n") for line in split_lines(old)]
    after = [line.rstrip("\r\n") for line in split_lines(new)]
    if old is not None and before == after:
        return ""
    lines = difflib.unified_diff(
        before, after,
        fromfile="/dev/null" if old is None else ("a/" + name if below else name),
        tofile="b/" + name if below else name, lineterm="")
    return "\n".join(lines) + "\n"


def _value_of(settings: Dict[str, Any], key: str, data: Optional[Dict[str, Any]]) -> Any:
    """A resolved value for the parity check. With no project settings file the project
    has no journal, so `db` is null there, as a new file with `"db": null` says."""
    if key == "db" and data is None:
        return None
    setting = settings.get(key)
    return None if setting is None else setting.value


SCAN_DEPTH = 6
SCAN_DIRS = 2000
# Directories the scan for configs never enters: dependencies and build output.
SCAN_SKIP = frozenset({"node_modules", "build", "dist", "target", "vendor",
                       "venv", "__pycache__"})
REASON_BELOW = "a config below the root at {} sets it differently"
_PRD_KEY = "artifact_homes.prd"
REASON_DIFFERS_FILE = ("differs from the settings file ({}): the skills read the bullet until "
                       "the grace date, the hooks read the file; set the one you want and "
                       "delete the other")
REASON_HOME_ELSEWHERE = ("a home or the ledger outside the project config stays: set it in "
                         ".claude/shipgate.json by hand, or delete the line")
REASON_HOME_HELD = ("removing it would change {0} for {1}: keep it, or set {0} in "
                    ".claude/shipgate.json")


def _config_dirs(root: Path, notes: List[str]) -> List[Path]:
    """Each directory below ROOT that holds `.claude/shipgate.md`, breadth first and
    sorted. Dot-directories, `node_modules`, build and vendor output (SCAN_SKIP) and
    symlinked directories are left out, and so is a directory with its own
    `.claude/shipgate.json` (a project of its own), with all below it. A `.claude` or a
    `.claude/shipgate.md` that is a link, or that resolves outside ROOT, is not read,
    with a note. The scan goes at
    most SCAN_DEPTH levels down, silently (an ordinary source tree is deeper), and
    examines at most SCAN_DIRS directories; a note says when that bound stops it."""
    found: List[Path] = []
    root_real = os.path.realpath(str(root))
    queue = collections.deque([(root, 0)])
    examined = 0
    while queue:
        directory, depth = queue.popleft()
        if examined >= SCAN_DIRS:
            notes.append("the scan for configs below the root stopped after {} directories; "
                         "a config past them is not checked".format(SCAN_DIRS))
            break
        examined += 1
        if directory != root:
            if os.path.isfile(str(directory / _config.SETTINGS_RELPATH)):
                continue
            config = directory / _config.CONFIG_RELPATH
            linked = next((path for path in (directory / ".claude", config)
                           if os.path.lexists(str(path))
                           and (os.path.islink(str(path)) or not _inside(path, root_real))),
                          None)
            if linked is not None:
                notes.append("{} is a link or leaves the root; the scan does not read "
                             "it".format(_echo(_header_path(linked, root)[0])))
            elif os.path.isfile(str(config)):
                found.append(directory)
        if depth >= SCAN_DEPTH:
            continue
        try:
            with os.scandir(str(directory)) as entries:
                names = sorted(entry.name for entry in entries
                               if entry.is_dir(follow_symlinks=False)
                               and not entry.name.startswith(".")
                               and entry.name not in SCAN_SKIP)
        except OSError:
            continue
        queue.extend((directory / name, depth + 1) for name in names)
    return found


def plan_move(root: Path) -> MovePlan:
    """The move of every legacy line of the project at ROOT, its nested repos and the user
    config into the settings files, with the parity check (PRD SC-005) done: per key, the
    value from the root, from each nested repo and from each other directory below the
    root with a config is the same after the move as before. A key whose value would
    change from such another directory keeps every line. Nothing is written. MoveError on
    a refusal."""
    try:
        schema = _config.load_schema()
    except OSError as exc:
        raise MoveError(str(exc), EXIT_INFRA) from None
    newest = schema.get("x-version", 2)
    project_file = root / _config.SETTINGS_RELPATH
    user_file = _config.user_settings_path()
    user_config = _config.user_config_path()
    root_real = os.path.realpath(str(root))
    for path in (root / ".claude", project_file, root / _config.CONFIG_RELPATH):
        _refuse_link(path, root_real)
    for path in (user_file, user_config):
        if path is not None and _real(path) == _real(project_file):
            raise MoveError("{} is the user file {}; --move-settings writes nothing through "
                            "it".format(project_file, path), EXIT_INFRA)
    if not os.path.lexists(str(project_file)):
        above = _ancestor_project(root)
        if above is not None:
            raise MoveError("{} lies below the project root {}, which holds "
                            "{}; run it from the project root {}".format(
                                root, above, _config.SETTINGS_RELPATH, above), EXIT_USAGE)
    project, project_text = _read_settings(project_file, newest)
    user, user_text = _read_settings(user_file, newest)
    can_project = (root / ".claude").is_dir()
    base_notes: List[str] = []
    base_kept: List[Kept] = []
    sources, nested = _sources(root, user_config, base_notes)
    texts = {_real(s.path): s.text for s in sources}
    starts = [root] + nested
    below = [d for d in _config_dirs(root, base_notes) if d not in set(nested)]

    def resolve(start: Path, planned: Dict[str, str], project_data: Any,
                user_data: Any) -> Dict[str, Any]:
        def read(path: Path) -> Optional[str]:
            key = _real(path)
            return planned[key] if key in planned else _disk_text(path)

        files = _config.read_layers(_candidates(root, start), user_config, read=read)
        return _config.resolve_settings(project_file, files, user_file, schema,
                                        project_data=project_data,
                                        user_data=user_data).settings

    before = {start: resolve(start, texts, project, user) for start in starts + below}
    root_before = before[root]

    lines: List[Line] = []
    for source in sources:
        where = str(source.path)
        config = _config.ConfigFile(source.path, source.kind, source.text)
        present = {line.key: line for line in _config.legacy_lines([config], schema)}
        for key, _node, section, bullet in _config.legacy_keys(schema):
            if key in _config.HOME_KEYS:
                # Never moved into a settings file: the hooks would act on it. The project
                # config's bullets follow SETTINGS_BULLETS below.
                if source.kind != KIND_PROJECT and key in present:
                    base_kept.append(Kept(where, section, bullet, present[key].value,
                                          REASON_HOME_ELSEWHERE))
                continue
            entries = [value for name, value in _config.section_bullets(
                source.text, section.lower(), keep_case=True) if name.lower() == bullet.lower()]
            if not entries:
                continue
            if len(entries) > 1:
                base_kept.extend(Kept(where, section, bullet, value.strip(), REASON_DUPLICATE)
                                 for value in entries)
                continue
            legacy = present.get(key)
            value = None if legacy is None else _config.legacy_value(key, legacy.value, schema)
            if legacy is None or value is None:
                base_kept.append(Kept(where, section, bullet, entries[0].strip(),
                                      REASON_NO_PARSE))
                continue
            cut = _bullet_cut(source, section, bullet)
            if cut is None:
                base_kept.append(Kept(where, section, bullet, legacy.value, REASON_NOT_LOCATED))
                continue
            lines.append(Line(source, key, section, bullet, legacy.value, value, cut))

    props = schema["properties"]

    def attempt(held: Dict[str, Tuple[str, str]]
                ) -> Tuple[MovePlan, List[str], Dict[str, Tuple[Tuple[str, str], str]]]:
        """One plan that keeps every line of each HELD key (key → (kept reason, where)):
        (the plan, the changes the parity check refuses, and per key to hold next: (its
        (kept reason, where), the change)). A key is held when its value would change
        from a directory below the root, or, for a home or the ledger, from anywhere."""
        notes = list(base_notes)
        kept = list(base_kept)
        moved: List[Moved] = []
        project_writes: Dict[str, Any] = {}
        user_writes: Dict[str, Any] = {}
        cuts: Dict[str, Set[int]] = {}
        cut_keys: Dict[str, Set[str]] = {}
        replaced: Dict[str, Dict[int, Tuple[int, str]]] = {}
        conflicts: Set[str] = set(held)

        def move(line: Line, to: Path) -> None:
            real = _real(line.source.path)
            cuts.setdefault(real, set()).update(line.cut)
            cut_keys.setdefault(real, set()).add(line.key)
            moved.append(Moved(line.key, str(line.source.path), line.section, line.bullet,
                               line.raw, str(to)))

        def keep(line: Line, reason: str) -> None:
            kept.append(Kept(str(line.source.path), line.section, line.bullet, line.raw,
                             reason))

        def wins(key: str, path: Optional[Path], current: Any, line: Line) -> str:
            return "{}: {} sets {}, which wins over {} in {} ## {}; the line goes".format(
                key, path, _shown(current), _echo(line.raw), line.source.path, line.section)

        for key in _leaf_keys(schema):
            group = [line for line in lines if line.key == key]
            if not group:
                continue
            if key in held:
                reason, where = held[key]
                for line in group:
                    keep(line, reason)
                notes.append("{}: every line for it stays, because the move would change its "
                             "value for {}".format(key, where))
                continue
            scope = props[key.split(".", 1)[0]].get("x-scope", _config.SCOPE_ANY)
            project_side = [line for line in group if line.source.kind != KIND_USER]
            user_line = next((line for line in group if line.source.kind == KIND_USER), None)
            resolved = root_before[key].value
            if not _sets(project, key) and any(
                    not _same(line.value, resolved) for line in project_side
                    if line.source.kind == KIND_NESTED):
                conflicts.add(key)
                for line in group:
                    keep(line, REASON_CONFLICT)
                values = ["{} has {}".format(line.source.path, _shown(line.value))
                          for line in project_side]
                if not any(line.source.kind == KIND_PROJECT for line in project_side):
                    values.append("the project root resolves {}".format(_shown(resolved)))
                notes.append("conflict: {} differs between the project's configs ({}); every "
                             "line for it stays. Set it once in the project settings file, "
                             "then run this again".format(key, "; ".join(values)))
                continue
            if project_side:
                if _sets(project, key):
                    current = _setting(project, key)
                    for line in project_side:
                        move(line, project_file)
                        if not _same(line.value, current):
                            notes.append(wins(key, project_file, current, line))
                elif not can_project:
                    for line in project_side:
                        keep(line, REASON_NO_PROJECT_DIR)
                else:
                    project_writes[key] = next(
                        (line.value for line in project_side
                         if line.source.kind == KIND_PROJECT), project_side[0].value)
                    for line in project_side:
                        move(line, project_file)
                        if line.source.kind == KIND_NESTED:
                            notes.append("{} = {} from {} now applies to every repo of the "
                                         "project".format(key, _shown(line.value),
                                                          line.source.path))
            if user_line is None:
                continue
            if scope != _config.SCOPE_PROJECT:
                if user_file is None or not user_file.parent.is_dir():
                    keep(user_line, REASON_NO_USER_DIR)
                elif _sets(user, key):
                    current = _setting(user, key)
                    move(user_line, user_file)
                    if not _same(user_line.value, current):
                        notes.append(wins(key, user_file, current, user_line))
                else:
                    user_writes[key] = user_line.value
                    move(user_line, user_file)
                    notes.append("a project whose own ## {} section hid this user line will "
                                 "take the user's {} ({}) after the move".format(
                                     user_line.section, key, _shown(user_line.value)))
                continue
            decided = root_before[key]
            if (decided.source == _config.SOURCE_LEGACY and decided.path == str(user_config)
                    and not _sets(project, key) and key not in project_writes
                    and can_project):
                project_writes[key] = user_line.value
                moved.append(Moved(key, str(user_line.source.path), user_line.section,
                                   user_line.bullet, user_line.raw, str(project_file)))
                notes.append("{} = {}: copied from the user config {} into the project "
                             "settings file; the user config keeps the line, because other "
                             "projects still read it until the grace date".format(
                                 key, _shown(user_line.value), user_line.source.path))
            else:
                keep(user_line, REASON_PROJECT_KEY)

        project_source = next((s for s in sources if s.kind == KIND_PROJECT), None)
        if project_source is not None:
            source = project_source
            where = str(source.path)
            # The values the resolver reads from this file's bullets, the worklog beside
            # the PRD included.
            given = _config.legacy_values(source.text, schema)
            for section, bullet, setting in SETTINGS_BULLETS:
                entries = [value for name, value in _config.section_bullets(
                    source.text, section.lower(), keep_case=True)
                    if name.lower() == bullet.lower()]
                if not any(_config.bullet_value(value) is not None for value in entries):
                    continue
                if len(entries) > 1:
                    kept.extend(Kept(where, section, bullet, value.strip(), REASON_DUPLICATE)
                                for value in entries)
                    continue
                written = entries[0].strip()
                if setting in held:
                    kept.append(Kept(where, section, bullet, written, held[setting][0]))
                    continue
                change, payload = _settings_bullet_change(source, section, bullet)
                if change == "locate":
                    kept.append(Kept(where, section, bullet, written, REASON_NOT_LOCATED))
                    continue
                if setting == "db":
                    if change == "prose":
                        kept.append(Kept(where, section, bullet, written, REASON_PROSE))
                        continue
                    difference = _db_difference(
                        "{} ## {} — {}: {}".format(where, section, bullet, _echo(written)),
                        _config.bullet_value(entries[0]) or "", project, schema)
                    if difference:
                        notes.append(difference)
                else:
                    # A home or the ledger goes only when the key resolves to the same
                    # value without it: it never goes into a settings file, because the
                    # hooks would act on it (the user's decision, 2026-11-24).
                    named = given.get(setting)
                    if named is None:
                        kept.append(Kept(where, section, bullet, written,
                                         REASON_NO_REPO_PATH.format(setting)))
                        continue
                    if named is _config.BESIDE_PRD:
                        named = _config.beside_prd(root_before[_PRD_KEY].value)
                    if _sets(project, setting):
                        current = _setting(project, setting)
                        if not _same(named, current):
                            kept.append(Kept(where, section, bullet, written,
                                             REASON_DIFFERS_FILE.format(_shown(current))))
                            continue
                    else:
                        default = (_config.setting_node(setting, schema) or {}).get("default")
                        if not _same(named, default):
                            kept.append(Kept(where, section, bullet, written,
                                             REASON_NOT_SET.format(setting, _echo(named))))
                            continue
                    if change == "prose":
                        payload = _bullet_cut(source, section, bullet)
                        if payload is None:
                            kept.append(Kept(where, section, bullet, written,
                                             REASON_NOT_LOCATED))
                            continue
                        change = "cut"
                        notes.append("{} ## {} — {}: its words go with it; keep them in a "
                                     "prose line of the section if they matter".format(
                                         where, section, bullet))
                if change == "cut":
                    cuts.setdefault(_real(source.path), set()).update(payload)
                else:
                    replaced.setdefault(_real(source.path), {}).update(payload)
                    notes.append("{} ## {} — {}: the promotion targets it holds stay, as a "
                                 "`- {}:` bullet".format(where, section, bullet,
                                                         PROMOTION_KEY))
                cut_keys.setdefault(_real(source.path), set()).add(setting)
                moved.append(Moved(setting, where, section, bullet, written,
                                   str(project_file)))

        planned: Dict[str, str] = {}
        for source in sources:
            real = _real(source.path)
            blocks = set(cuts.get(real, ()))
            swaps = replaced.get(real, {})
            if not blocks and not swaps:
                planned[real] = source.text
                continue
            for head, end in _section_spans(source.blocks):
                content = [x for x in range(head + 1, end) if source.blocks[x].kind != "blank"]
                if content and all(x in blocks for x in content):
                    blocks.add(head)
            removed = {i for x in blocks
                       for i in range(source.blocks[x].start, source.blocks[x].end + 1)}
            planned[real] = _without(source.raw, source.lines, source.blocks, removed,
                                     swaps)[0]
            config = _config.ConfigFile(source.path, source.kind, source.text)
            want = [(line.key, line.value) for line in _config.legacy_lines([config], schema)
                    if line.key not in cut_keys.get(real, ())]
            got = [(line.key, line.value) for line in _config.legacy_lines(
                [config._replace(text=planned[real])], schema)]
            if got != want:
                raise MoveError("the plan for {} would change lines it does not move; edit "
                                "it by hand".format(source.path), EXIT_INFRA)

        def settings_files() -> Tuple[Any, Any]:
            return (_merged(project, project_writes, schema, True) if project_writes
                    else project,
                    _merged(user, user_writes, schema, False) if user_writes else user)

        planned_project, planned_user = settings_files()
        after_root = resolve(root, planned, planned_project, planned_user)
        pins: List[str] = []
        for key in root_before:
            if key == "version" or key in _config.HOME_KEYS:
                continue
            old = _value_of(root_before, key, project)
            if _same(old, _value_of(after_root, key, planned_project)):
                continue
            if (key in conflicts or _sets(project, key) or key in project_writes
                    or not can_project or not _config.valid_setting(key, old, schema)):
                continue  # the check below names it
            project_writes[key] = old
            pins.append(key)
        if pins:
            planned_project, planned_user = settings_files()
            for key in pins:
                legacy = (_config.setting_node(key, schema) or {}).get("x-legacy") or {}
                notes.append("pinned {} = {}: the project's {} section hid the user file's "
                             "line before; delete the pin to take the user value".format(
                                 key, _shown(project_writes[key]),
                                 legacy.get("section", "config")))

        changes: List[str] = []
        below_changes: Dict[str, Tuple[Tuple[str, str], str]] = {}
        for start in starts + below:
            after = resolve(start, planned, planned_project, planned_user)
            for key in dict.fromkeys(list(before[start]) + list(after)):
                if key == "version":
                    continue
                old = _value_of(before[start], key, project)
                new = _value_of(after, key, planned_project)
                if _same(old, new):
                    continue
                change = "{}: {} would change from {} to {}".format(
                    start, key, _shown(old), _shown(new))
                if key in _config.HOME_KEYS:
                    below_changes.setdefault(
                        key, ((REASON_HOME_HELD.format(key, start), str(start)), change))
                    continue
                if start in below:
                    config = str(start / _config.CONFIG_RELPATH)
                    below_changes.setdefault(key, ((REASON_BELOW.format(config), config),
                                                   change))
                    continue
                setting = after.get(key)
                if (start != root and setting is not None
                        and setting.source == _config.SOURCE_PROJECT
                        and _same(new, _value_of(root_before, key, project))):
                    notes.append("{}: {} becomes {} (was {}): the project settings file sets "
                                 "it for every repo".format(start, key, _shown(new),
                                                            _shown(old)))
                    continue
                changes.append(change)

        files: List[Dict[str, Any]] = []
        writes: List[Tuple[str, str, bool, bool]] = []
        config_writes: List[Tuple[str, str, bool, bool]] = []
        for source in sources:
            new_text = planned[_real(source.path)]
            changed = new_text != source.text
            files.append({"path": str(source.path), "changed": changed, "created": False,
                          "diff": _text_diff(_header_path(source.path, root), source.text,
                                             new_text) if changed else ""})
            if changed:
                config_writes.append((str(source.path), new_text, False,
                                      source.kind == KIND_USER))
        for path, data, text, new_data, trusted in (
                (project_file, project, project_text, planned_project, False),
                (user_file, user, user_text, planned_user, True)):
            if path is None or new_data is None:
                continue
            if new_data is data:
                files.append({"path": str(path), "changed": False, "created": False,
                              "diff": ""})
                continue
            content = json.dumps(new_data, indent=2, ensure_ascii=False) + "\n"
            created = data is None
            changed = created or content != text
            files.append({"path": str(path), "changed": changed, "created": created,
                          "diff": _text_diff(_header_path(path, root), text, content)
                          if changed else ""})
            if changed:
                writes.append((str(path), content, created, trusted))
            if created and not trusted:
                notes.append('creates {} with "db": null: this project has no journal; the '
                             'hooks stay inert, as before'.format(_config.SETTINGS_RELPATH))
        return (MovePlan(files, moved, kept, notes, writes + config_writes), changes,
                below_changes)

    held: Dict[str, Tuple[str, str]] = {}
    while True:
        result, changes, below_changes = attempt(held)
        fresh = {key: hold for key, (hold, _change) in below_changes.items()
                 if key not in held}
        if not fresh:
            break
        held.update(fresh)
    changes += [change for _where, change in below_changes.values()]
    if changes:
        raise MoveError(
            "the move would change a setting, so nothing is written:\n"
            + "".join("  {}\n".format(change) for change in changes)
            + "move those lines by hand, or set the value in a settings file, then run this "
              "again", EXIT_INFRA)
    return result


def create_atomic(path: str, content: str) -> None:
    """Create PATH with CONTENT through a temporary file in its directory, with the mode a
    plain create gives (0666 less the umask). A PATH that appears meanwhile is refused,
    not replaced."""
    fd, tmp = tempfile.mkstemp(prefix=".lean_config-", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise
        except OSError:
            # A file system with no hard links: check, then rename.
            if os.path.lexists(path):
                raise FileExistsError(errno.EEXIST, "file exists", path) from None
            os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def move_summary(result: MovePlan) -> str:
    return "lean_config: {} line(s) to move, {} kept, {} file(s) to change".format(
        len(result.moved), len(result.kept), sum(1 for f in result.files if f["changed"]))


def move_settings(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.is_dir():
        print("error: no such directory: {}".format(args.path), file=sys.stderr)
        return EXIT_USAGE
    try:
        result = plan_move(root)
    except MoveError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return exc.code
    if args.apply:
        for path, content, created, trusted in result.writes:
            try:
                if created:
                    create_atomic(path, content)
                else:
                    write_atomic(path, content, follow_links=trusted)
            except OSError as exc:
                print("error: {}".format(exc), file=sys.stderr)
                return EXIT_INFRA
    if args.json:
        print(json.dumps({
            "files": result.files,
            "moved": [m._asdict() for m in result.moved],
            "kept": [k._asdict() for k in result.kept],
            "notes": result.notes,
            "changed": any(f["changed"] for f in result.files),
        }, sort_keys=True, indent=2))
        return EXIT_OK
    print(move_summary(result))
    for note in result.notes:
        print(_printable("note: " + note))
    for k in result.kept:
        print(_printable("kept: {} ## {} — {}: {} ({})".format(
            k.path, k.section, k.bullet, _echo(k.value), k.reason)))
    if not args.apply:
        for entry in result.files:
            sys.stdout.write(entry["diff"])
    return EXIT_OK


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
                    "a unified diff; writes only with --apply. With --move-settings, move "
                    "the settings that the configs of a project, of its nested repos and "
                    "of the user still hold as legacy lines into the settings files "
                    "(ADR 0028). Prints a summary, the notes, the lines that stay and a "
                    "diff per file; writes only with --apply.",
        epilog="exit codes: 0 ok (whether or not anything changes), 1 a file cannot be "
               "read or written, a settings file is no JSON object, a project file is a "
               "symlink, a move would change a setting, or the install is incomplete, "
               "2 usage error, a root below a project root, or a settings file declares "
               "a version this shipgate does not write",
    )
    parser.add_argument("path", help="the config file, e.g. .claude/shipgate.md; with "
                                     "--move-settings, the project root (the directory "
                                     "that holds .claude/)")
    parser.add_argument("--move-settings", action="store_true",
                        help="move legacy lines into the settings files: from the project "
                             "and nested configs into .claude/shipgate.json, from the user "
                             "config into the user settings file")
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


def write_atomic(path: str, content: str, follow_links: bool = True) -> None:
    """Replace PATH's content through a temporary file in its directory. A file without
    write permission is refused, not replaced. The new file keeps the old file's mode, but
    it belongs to the current user, and a hard link to the old file is split. With
    FOLLOW_LINKS false, a PATH that is a symlink is refused, not written through."""
    if not follow_links and os.path.islink(path):
        raise OSError(errno.ELOOP, "is a symlink; not written through", path)
    target = os.path.realpath(path) if follow_links else os.path.abspath(path)
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
    if args.move_settings:
        if args.user or args.drop_equal or args.only_equal or args.umbrella:
            parser.error("--move-settings cannot combine with --user, --drop-equal, "
                         "--only-equal or --umbrella")
        return move_settings(args)
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
