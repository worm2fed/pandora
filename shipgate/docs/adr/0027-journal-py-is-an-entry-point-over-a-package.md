---
type: adr
title: "0027. journal.py is an entry point over a package of modules"
created: 2026-11-23
updated: 2026-11-23
tags:
  - adr
  - shipgate
  - journal
status: accepted
date: 2026-11-23
issue: "#61 (shipgate), refers to #48; wave 2 of #37"
related:
  - "0001-sqlite-flow-journal.md"
  - "0009-the-journal-computes-the-hud-position.md"
  - "0023-the-users-go-is-recorded-where-the-user-answers.md"
  - "../prd/journal-package.worklog.md"
---

# 0027. journal.py is an entry point over a package of modules

> `scripts/journal.py` keeps its path, its commands and every output byte. Its code moves,
> unedited, into 22 modules under `scripts/_journal/`, one per concern, in a fixed layer
> order with no import cycle. The entry point loads the package by path, fresh for each
> load, and copies every top-level name into its own namespace.

Decided in executive mode by the design session of #61, and accepted by the user through
the lead with no veto (2026-11-23).

## Context

`journal.py` has 7,826 lines: 476 top-level statements that define 489 names. Issue #61
names four costs of the one file: a session that reads it spends tens of thousands of
tokens, every branch rebases over it, a reviewer cannot scope a change to one concern, and
Python compiles all of it at every start, because it never caches the bytecode of a script
it runs as `__main__` (#48).

These facts constrain the split:

- **Callers start a script.** The hooks run `python3 <plugin>/scripts/journal.py --db …`
  through `hooks/_common.py` `run_journal`. The skills print the same command, and
  shipgate-hud runs the CLI. None of them imports the file.
- **Tests load the file by path.** Seven test modules load `journal.py` with
  `importlib.util.spec_from_file_location` under their own module names, and reach 74
  names through the loaded module. No test assigns, deletes or patches an attribute of
  that module (an AST pass over the suite, 2026-11-23).
- **One test loads two copies in one process.** `test_hooks.py`
  `TestPrintedGoRequestsRunAsPrinted` copies `hooks/` and `scripts/` to a path with spaces.
  It loads the copy's `journal.py` in the process that already loaded the original, and
  expects the printed commands to name the copy's path.
- **The sections call each other in every direction.** A split along the file's 16 banner
  sections has one import cycle through 12 of them. About 70 small shared statements close
  the cycle: text helpers (`_one_line`, `_clip`), session attribution (`event_session`,
  `_actor_role`), the printers of journal commands (`_suggest`, `_journal_prefix`), and
  constants that sit in the section of their first reader.
- **Four lines read `__file__`** to find a plugin file: `hooks/_common.py`, `_config.py`,
  `.claude-plugin/plugin.json`, and the path of `journal.py` that printed commands name.

## Decision

**1. A private package.** The code moves to `shipgate/scripts/_journal/`. The underscore
marks it as private to the scripts, as `_config.py` and `_codegraph.py` are. A directory
named `journal/` would shadow `journal.py` for any importer that has `scripts/` on
`sys.path`, because a package wins over a module of the same name.

**2. Twenty-two modules in a layer order.** Each module imports only from modules above it
in this table. Lines are the prototype's file lengths, headers included.

| # | Module | Owns | Lines |
|---|---|---|---|
| 1 | `vocab` | exit codes and their errors, phases, the event vocabulary, payload shapes and limits | 574 |
| 2 | `plugin` | the plugin's own files (`hooks/_common.py`, `_config.py`, `plugin.json`) and the journal commands the output prints | 142 |
| 3 | `text` | pure helpers over strings and payload values | 64 |
| 4 | `project` | which project and journal a directory belongs to: sidecar, db path, config files | 240 |
| 5 | `store` | SQLite: connection, schema and migrations, meta, events, timestamps | 227 |
| 6 | `sessions` | who wrote a row: actor labels, the appending session, which session a row binds | 187 |
| 7 | `approval` | the user's go: commit and publish authorization read from rows | 158 |
| 8 | `fold` | a stream folded into its state: lifecycle, phase, marks, dispositions, branch binding | 461 |
| 9 | `artifacts` | authorship claims, classification by home, build-plan parsing, worklog binding | 506 |
| 10 | `shapes` | payload shape validation, size cap, location keys, vocabulary checks | 346 |
| 11 | `gates` | each event type's precondition on the journal (rules v1) | 421 |
| 12 | `append` | duplicate detection, implied phases, automatic deviations, the insert | 299 |
| 13 | `status` | the status brief: bound streams and the count line (ADR 0024) | 318 |
| 14 | `reply` | the recorder's reply plan and the command gate's `authorize` (ADR 0023) | 401 |
| 15 | `check` | the Stop gate (ADR 0020) | 320 |
| 16 | `position` | every fact the HUD draws for one stream (ADR 0009) | 427 |
| 17 | `handoff` | the handoff brief (ADR 0021) and the context nudge | 385 |
| 18 | `closeout` | close-out and sweep from observed evidence (ADR 0025, ADR 0026) | 901 |
| 19 | `stats` | counts over the journal | 360 |
| 20 | `doctor` | the health and config report | 282 |
| 21 | `transfer` | `export` and `import` | 113 |
| 22 | `cli` | the parser, one function per subcommand, `main` | 978 |

The exact assignment of every statement is the table "Assignment" in the worklog. Most
modules are one banner section of the old file, or one block of it: the gate section
splits into `approval`, `shapes` and `gates`, the reply section into `status` and `reply`,
the check section into `artifacts` and `check`. The shared statements that closed the cycle
move down to the lowest module that all their readers can import. Each keeps its text.

**3. Import rules.** Modules import each other relatively (`from .store import
read_events`), never as `_journal`. No module has `if __name__ == "__main__"`, and the
package has no `__main__.py`. So `journal.py` stays the only way to run the journal.

**4. The entry point.** `scripts/journal.py` keeps its shebang and its docstring and holds
50 lines:

- `_load_package()` loads `_journal/__init__.py` by path with
  `spec_from_file_location(name, …, submodule_search_locations=[directory])`. The name is
  the first free `_shipgate_journal_<n>` in `sys.modules`. It registers the package there,
  because relative imports need the parent, and executes it. `__init__.py` imports the 22
  modules in layer order.
- `_package = _load_package()`, then `globals().update(_package.names())`: every top-level
  name of every module, dunder names excluded. Every attribute the old module had is an
  attribute of the new one, the 74 that tests reach among them.
- `if __name__ == "__main__": sys.exit(main())`, as before.
- A failed load exits 1 with the message form of the hooks loader:
  `error: cannot load <dir> (shipgate install incomplete): <exc>`.

Loading by path, under a name of its own, gives three properties:

- It needs no `sys.path` entry, so it works under `-P`, `PYTHONSAFEPATH` and `-I`, where
  Python does not put the script's directory first.
- Each load of `journal.py` builds its own module state, as each load of the one file did:
  `_hooks_common`, `_config` and the sidecar-warning flag. Two copies of the plugin in one
  process each print their own path, so the copy test above passes unchanged.
- The modules load through Python's standard source loader and get cached bytecode.

**5. The only edited lines.** The four `__file__` readers move to `plugin.py`. Three of
them gain one `.parent`. `_journal_prefix` names `Path(__file__).resolve().parent.parent /
"journal.py"`, which is the same path the old `Path(__file__).resolve()` gave, because the
plugin never ships `journal.py` as a symbolic link.

**6. A test that patches.** A moved function reads its globals from its own module, so a
patch on the loaded `journal` module does not reach it. No test patches today. A future
test patches the owning module: `J._package.store.utc_now`, never `J.utc_now`.

## Alternatives considered

- **A normal import through `sys.path`** (`sys.path.insert(0, scripts)`, then `from
  _journal.cli import main`). It is the usual form. It fails the copy test: the first copy
  that a process imports stays in `sys.modules`, so the second copy prints the first one's
  path. It also puts every script of `scripts/` on the path of an importer.
- **Slices executed into one namespace.** `journal.py` would execute the cached code of
  each slice in order into its own globals. No line would change, and a patch on `journal`
  would still reach every function. But the slices are not modules: they import nothing,
  an editor or pyright flags every name in them, and no import shows what a slice depends
  on. The next change could not see its blast radius from the imports.
- **Seven coarse modules** along the issue's example (store, vocabulary and shapes, gates,
  fold with status and position, check, approval, handoff with close-out). The shared
  statements still need a home below all of them, and most files would hold 1,000 to 1,800
  lines, so a reviewer would still read a large file to scope one change. The finer
  layout keeps most of the file's own sections whole.
- **Lazy imports per subcommand.** A small command such as `vocab` would load fewer
  modules. That edits `cli.py` and `main`, so it is no pure move. It is left for a later
  issue, with measurements.
- **Bytecode shipped in the plugin.** A `.pyc` file is tied to one Python version and
  grows the repository. Python writes the cache on the first run anyway.

## Consequences

- One concern is one module. A session reads the module it changes and the ones it
  imports, and a branch that changes one concern rebases over one file.
- **The start.** With a bytecode cache, one journal run starts about 34 ms faster
  (`journal.py vocab`, median of 20 on the built tree: 107.1 → 72.7 ms). The recorder with
  an open request runs the journal twice and drops from 268.1 to 195.4 ms, under its
  200 ms budget by less than 5 ms (the prototype measured 204.9 ms). The command gate
  drops from 173.5 to 137.9 ms. The worklog holds the tables.
- **Without a bytecode cache** (a read-only install, or `PYTHONDONTWRITEBYTECODE=1`),
  Python compiles 23 files at each run, and a journal run costs about 5 ms more than
  today (108.1 → 113.1 ms; the prototype measured 7 ms). `PYTHONPYCACHEPREFIX` moves the
  cache to a writable directory and restores the gain. The plugin cache that Claude Code
  writes is user-owned and writable, and so is a checkout used as a `directory`
  marketplace.
- Hooks, skills and shipgate-hud change nothing: no file under `hooks/` changes, and the
  hook contract is the same.
- **The pre-mortem.** An installed copy without `_journal/` would fail every journal run
  with exit 1: the recorder would record no go, and the command gate would hold every
  commit. The entry point names the missing directory in its error. After the tag, the
  release check runs `journal.py vocab` from the updated install, and the release counts
  as done only when it exits 0.
- The forgery net in `hooks/pre_tool_use.py` matches commands that name `journal.py`. The
  package adds no entry point, so a model reaches the modules only through `python3 -c` or
  a script of its own, which the net already scopes out ("This is a net, not a boundary").
- A new top-level name goes to the module of its concern, and the layer order holds. A
  test of the import direction guards this (worklog T018).
- Two comments in `signals.py` name `journal.py` as the home of code that moved
  (`_load_hooks_common`, `_matches_glob`); they name the new module instead.
