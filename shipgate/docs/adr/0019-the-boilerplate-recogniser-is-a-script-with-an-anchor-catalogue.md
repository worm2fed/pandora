---
type: adr
title: "0019. The boilerplate recogniser is a script with an anchor catalogue"
created: 2026-11-08
updated: 2026-11-08
tags:
  - adr
  - shipgate
  - config
  - setup
status: accepted
date: 2026-11-08
issue: "#17"
related:
  - "0018-config-layers-resolve-per-section-nearest-first.md"
  - "../prd/shipgate-0.25.0.md"
---

# 0019. The boilerplate recogniser is a script with an anchor catalogue

> `setup`'s update mode strips the text that explains the plugin from an existing config
> through `scripts/lean_config.py`: a stdlib script that matches whole blocks against a
> catalogue of anchors, prints a unified diff, and writes only with `--apply`. A block that
> matches no anchor stays. Decided in executive mode; the user can veto.

## Context

A config written from the template, or by `setup` before 0.25.0, carries the template's
header paragraphs, one `<!-- Default when absent … -->` comment per section, the Journal
section's prose, the Orchestration, Code signals and Worker guardrails explanations, the MR
watcher's explanation bullets and the `Executive contract` bullet. Over 8 configs that is
about a third of the lines, and it goes stale with each release. `setup` must recognise it
in update mode and offer to remove it. The brief sets the bar: a false removal is worse than
a missed one, and hand-written content stays untouched, always.

The forms vary. The history of the template holds earlier wordings of the Journal and MR
watcher blocks. `setup` wrote its own header paragraph that is in no template. Configs
paraphrase the Code signals comment with a version tag, and the `Executive contract` bullet
exists in at least four wordings. A recogniser must match those and must not match a
project's own rationale comment under a bullet.

## Decision

1. **A script, not an instruction.** `scripts/lean_config.py <path>` parses the file into
   blocks: a heading, an HTML comment (one or many lines, at any indent), a bullet with its
   continuation lines, a paragraph, a fenced code block, blank lines. It classifies each
   block against the catalogue and prints the removals as a unified diff. `--apply` writes
   the file. `--json` prints the removals with line ranges and the anchor each matched.
   Exit 0 whether or not there is anything to remove; 1 when `--apply` cannot write (a
   read-only file or directory); 2 on a usage error. `--only-equal` (with `--user`) marks
   nothing but the sections equal to the user file's, so `setup` can offer that removal on
   its own diff, apart from the boilerplate strip.
2. **Anchors, whole blocks.** A block is removed only when its whitespace-normalised text
   starts with a catalogued anchor, or when it is a bullet whose value is an angle-bracket
   placeholder (by `_config.is_placeholder_value`, the one rule both scripts use; a bullet
   with a nested bullet that holds a real value stays), or a bullet whose key is `Executive
   contract`. The catalogue, by kind:
   - Comment-only anchors: `Default when absent`, `Only needed for umbrella`, `Usually
     personal: belongs in the user file`, and the three `Read by …signals.py` forms. These
     are short, so they never match a paragraph.
   - Paragraph-or-comment anchors: the template's header paragraphs in both generations
     (`Copy this file into your project as`, `Every section is **optional**`, `Division of
     labor with `CLAUDE.md``, `Subagents don't read this file themselves`, `Subagents
     don't read these files themselves`, `**How the config files layer.**`, the numbered
     layer list, `The config is resolved per section.`, `A nested config can take nothing
     from the umbrella.`, `The user file uses the same section vocabulary`, `` `setup`
     writes a lean file``) and the setup-written header (`Project configuration for the
     `shipgate` plugin.`); the Journal prose leads (`When this section is present the
     project is **journaled**`, `**The journal does not replace the ledger.**`, `**Event
     names and payload shapes are a fixed vocabulary.**`, `**Event names are a fixed
     vocabulary.**`, `**One stream per issue, named for its branch**`, `Dial enforcement
     down by setting`); `The one section a script reads rather than the model`; `Hard
     rules for anyone editing this repo`; `` `workflow` runs that phase's fan-out`` and
     `Degradation is automatic and never blocks`.
   - Bullet anchors: the Journal's three bullets in both wordings (`**Position is recorded,
     not guessed.**`, `**Recording is enforced by the plugin's hooks**`, `**Capture is
     enforced by the plugin's hooks**`, `**The database is local, disposable state.**`)
     and the MR watcher bullets `If declared, two skills honor it`, `The watcher is strictly
     read-only` and `Optional, when a **Journal** is configured`.

   A partial or edited match is a keep. A `- Key: value` bullet with a real value is never
   removed, whatever its key. Fenced code is never removed; a fence closes only on a bare
   marker. A comment with text after its `-->` stays. A line that reads `Inherit: …` always
   starts its own block, so it never joins a header paragraph.

   **Every sentence must be boilerplate.** An anchor selects a block, and a block is every
   consecutive non-blank line up to a line that starts a block of its own (a bullet, a
   comment, a fence, a heading, a rule, an `Inherit:` line). The block is removed only when
   every sentence in it is catalogued boilerplate: the script holds the sentences of every
   prose block of the template in each of its versions, of the header `setup` wrote before
   0.25.0, and of the `Executive contract` bullet in its known wordings. A sentence with a
   variable part (a date, a version tag, an example issue number or branch name) is a
   pattern, so no example id from the template's history is copied into the catalogue.
   A placeholder contract value is removed as a placeholder, not kept as mixed. A block with any other sentence stays whole and is listed as
   `mixed`, with a hint: move the project sentences to their own paragraph, or move the
   extra escalation cases to the `Extra escalations` line and delete the contract bullet by
   hand. So a sentence a user appended to a boilerplate paragraph, a hand-written line
   directly under an anchored line, and a contract bullet whose escalation list names
   project cases all stay (review round 1, F2 and F9, first rejected as a limit, then
   overruled: on seven real configs the anchor-prefix rule removed project content in two).
   Anchors stay as the selector, because the blocks exist in several wordings; the
   sentence catalogue is what makes a match exact. The gate stays too: the script prints
   the diff and writes nothing without `--apply`, and `setup` asks first.
3. **Residue.** The `---` rule that follows the header goes only when every block between the
   title and it was removed. A `##` heading whose section is left with no content, after at
   least one removal inside it, goes too. Only the blank-line runs that touch a removed
   range collapse (to one line, or to none at the start or end of the file); kept text is
   never reflowed. The title line stays. Each kept line keeps its own line ending, and
   `--apply` writes through a temporary file in the same directory and `os.replace`.
4. **Sections equal to the user file's.** With `--user <path>`, the script reports each `##`
   section whose body, comments removed and whitespace collapsed, equals the user file's
   section. `--drop-equal` adds those sections to the removal. Without the flag they are
   reported only. With `--umbrella <path>` (repeatable), a section an umbrella config also
   holds present is reported as shadowed and never dropped: dropping it would hand the
   section to the umbrella's file, not to the user's (ADR 0018 order).
5. **Idempotent.** A second run on the output finds nothing to remove.

## Alternatives considered

- **A skill instruction with a catalogue in a reference file.** The model reads the config
  and the catalogue, and edits by hand. Cheaper to write, but every run is a fresh judgment
  on prose, and the failure the brief names most (a false removal) has no test. Rejected.
- **Strip every HTML comment.** Comments are inert to the script readers, so a broad rule is
  safe for `signals.py`. But a comment under a bullet often carries the project's rationale,
  which the model reads. Rejected: comments go by anchor, like every other block.
- **A whitelist of what to keep.** The inverse rule, `- Key: value` bullets and headings
  only, would also strip hand-written paragraphs and sections the template does not know.
  Rejected: the brief says those stay, always.

## Consequences

- The catalogue is a list of strings in one script. A new boilerplate form in a later
  template is one more anchor and one more test case.
- Each removal is visible before it happens: `setup` shows the diff and asks. The script
  never writes without `--apply`.
- The fixtures for the tests are the current template filled in, this repository's own
  config as it stood before this change, and a hand-written config that must come back
  unchanged.
- The script is one more file `claude plugin validate` and the Python 3.9 syntax check
  cover.
