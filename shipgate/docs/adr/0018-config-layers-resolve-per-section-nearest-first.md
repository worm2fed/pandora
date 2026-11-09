---
type: adr
title: "0018. Config layers resolve per section, nearest first, with a user file under the project files"
created: 2026-11-08
updated: 2026-11-08
tags:
  - adr
  - shipgate
  - config
status: accepted
date: 2026-11-08
issue: "#15, #18"
related:
  - "0004-code-signals-on-demand-stdlib-script.md"
  - "../prd/shipgate-0.25.0.md"
---

# 0018. Config layers resolve per section, nearest first, with a user file under the project files

> A shipgate config is a stack of files: the repo's `.claude/shipgate.md`, the umbrella's,
> the user's `$CLAUDE_CONFIG_DIR/shipgate.md` (else `~/.claude/shipgate.md`), then the
> built-in defaults. Each `##` section is taken whole from the nearest file that holds it
> with a real value. `Inherit: none` under a nested config's title drops the umbrella's
> files from the stack. One private module, `scripts/_config.py`, holds the reader for
> `signals.py` and `journal.py`. Decided in executive mode; the user can veto.

## Context

Before this release the plugin had two readers of the config and no shared rule. The skills
read the prose and said only "overrides the defaults below", with no word on an umbrella's
file. `signals.py` read the repo's file and then the umbrella's, and merged them per key: a
repo `## Code signals` that set only `Window` still took `Fix pattern` from the umbrella.
Nested configs worked around the gap with prose: "overrides the umbrella" in every section
and "do not read an omission here as fall back to the umbrella".

Personal preferences had no home. Over 8 project configs, 7 set the same writing style and 5
the same library-docs line (#15). A user file needs a place in the order, and the order
needs one definition the skills can cite and the script can run.

Three choices were open: per key or per section; where the user file sits; and where the
code lives, given that `journal.py` must not import `signals.py` (it loads codegraph at
import) and the repository's rule is that scripts stay standalone.

## Decision

1. **Per section, nearest first.** The layers are, nearest first: the files from the start
   directory up to the repo root, then the umbrella's (the sidecar-marked root and the
   parent's git toplevel, as `signals.py` already finds them), then the user file. For each
   `##` section the nearest file that holds the section with at least one value that is not
   an angle-bracket placeholder supplies the whole section. Sections never merge line by
   line. A section with placeholders only, or no bullets, is absent, and the next layer
   shows through. For `## Code signals`, the one section only the script reads, present
   means one usable backticked value: a bare value is not usable there, so it does not
   hide a farther file's section (review round 1, F11). The rule is stated in the config
   template's header and the README's Configuration section; every skill cites it and
   does not restate it. A placeholder is one balanced `<…>` group, or several joined by
   whitespace with an optional separator or `Label:`; a value whose groups are joined with
   no whitespace (`<type>/<slug>`), an autolink (`<https://…>`) or a mention (`<@alice>`)
   is a real value. `_config.is_placeholder_value` is the one definition, and
   `lean_config.py` uses it too (F5).
2. **The user file is the last file.** `$CLAUDE_CONFIG_DIR/shipgate.md` when that variable is
   set and not empty, else `~/.claude/shipgate.md`. There is no fallback from a set variable
   to the home directory: the variable replaces the directory, as it does for the harness.
   The user file uses the project file's section vocabulary.
3. **`Inherit: none`.** A line `Inherit: none` before the first `##` heading of the nearest
   project-side file that exists (bare or as a bullet, backticks optional, any case) drops
   every umbrella file from the stack. The user file and the defaults still apply. The
   first word of the value decides, so `none — see the umbrella` is `none`. Any other
   value, or no line, is `umbrella`.
4. **One reader, loaded by path.** `scripts/_config.py` holds the section walker
   (`section_bullets`, moved from `signals.py`), the placeholder test, the title-level walker
   for `Inherit`, the user-file path, the layer reader (read each candidate, drop the
   umbrella's under `Inherit: none`, dedupe by resolved path, first occurrence wins) and
   the per-section resolver. `signals.py` and `journal.py` load it by path, as they load
   `hooks/_common.py` and as `signals.py` loads `_codegraph.py`. `signals.py` keeps
   `section_bullets`, `parse_code_signals`, `parse_code_graph` and `load_config` as module
   attributes. `hooks/` does not change.
5. **What the JSON says.** `signals.py --json`'s `config.source` labels a value from the user
   file `user shipgate.md`. A value from a project or umbrella file keeps `shipgate.md`.
   `config` gains `files`, the config files read in precedence order, each with `path` and
   `role` (`project`, `umbrella` or `user`), and `inherit` (`umbrella` or `none`).

## Alternatives considered

- **Per key, as `signals.py` did.** Finer, but it has no prose form a skill can follow: a
  section is the unit a reader lifts into a brief, and a section half from one file and half
  from another is what #18 reports as confusion. Rejected.
- **A placeholder-only section counts as present.** Simpler to state, but a template copy in
  a repo would then blank an umbrella's section, and the skills already read a placeholder
  as absent. Rejected.
- **The user file above the umbrella's.** A user's defaults would then beat a team's shared
  config, and a nested repo could not rely on its umbrella. Rejected: the user file is the
  floor above the defaults.
- **Duplicate the walker into `journal.py`.** The repository's "scripts stay standalone" rule
  was written when one script read the config. Two copies of a parser that defines "present"
  would drift, and the per-section rule is exactly the kind of definition that must not.
  Rejected in favour of the `_codegraph.py` precedent.
- **Put the reader in `hooks/_common.py`.** Both scripts load it already, but the hooks' fast
  path must stay cheap and the hooks never read the config. Rejected.

## Consequences

- `signals.py` reads a file outside the repository on every run. The project config in this
  repository lists reads outside the plugin directory as security-sensitive; the brief names
  the location, and the read is of one fixed path, with no write.
- Tests must isolate the user file. The test environment sets `CLAUDE_CONFIG_DIR` to a path
  that holds no `shipgate.md`, so the maintainer's real file never reaches a test.
- Three existing tests that pinned per-key mixing between a repo and its umbrella change to
  the per-section outcome.
- When `$HOME` is itself a git work tree, `~/.claude/shipgate.md` is already an umbrella
  candidate. The dedupe keeps the first occurrence, so the file reads as an umbrella file
  there, and `Inherit: none` drops it. That is the current behaviour on such a machine and
  stays rare.
- `journal.py doctor` can now read the config (ADR 0019's sibling change in #17), so the
  config-against-sidecar comparison is one more consumer of the same reader.
