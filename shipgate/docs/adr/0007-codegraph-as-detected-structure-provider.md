---
type: adr
title: "0007. codegraph as a detected structure provider behind signals.py"
created: 2026-10-19
updated: 2026-10-19
tags:
  - adr
status: accepted
date: 2026-10-19
issue: "none / ad-hoc"
related:
  - ../prd/code-graph.md
  - ../research/2026-10-19-codegraph-vs-signals.md
  - ./0004-code-signals-on-demand-stdlib-script.md
---

# 0007. codegraph as a detected structure provider behind signals.py

> `signals.py` stays the one command the phases call. When the `codegraph` binary is on
> `PATH`, the structural half (file edges, blast, tests reached, symbols) comes from its
> index: file edges by a read-only SQLite read, tests and symbols by its CLI with `--json`.
> When it is absent, the regex scanner runs as today. Detection, index build, freshness,
> telemetry and fallback live in one place, and nothing is configured by default. This
> amends ADR 0004 decisions 1 and 5. Decided in executive mode from three architect
> blueprints; the user can veto.

## Context

The PRD (`docs/prd/code-graph.md`) asks for symbol-level structure with no configuration,
one tool per axis, and today's behaviour when codegraph is absent. Three forks remained:

1. **Where the adapter lives.** Inside `signals.py`, in a sibling script, or in skill prose.
2. **Where file-level edges come from.** codegraph's CLI has no command that returns the
   dependents of a file set in one call. `affected -f '*'` returns only the seeds.
   `node <file> --symbols-only` returns direct dependents in 0.22 s. A BFS over it for a
   6-file diff in a 1,469-file repository took 28 calls and 8.1 s. The same edges read
   from `.codegraph/codegraph.db` took 28 ms, and the transitive blast matched the regex
   scanner file for file. SC-004 allows 5 s.
3. **Where "advised once" is remembered.** The journal exists only on journaled projects.
   `.claude/` may be tracked. `.git/` is a write into the repository even when codegraph
   is absent.

Measured facts that bound the design: the database is WAL mode with a `schema_versions`
table (max version 11 at codegraph 1.6.2); a `mode=ro` open fails when no `-shm` file
exists and `immutable=1` opens it; `init` takes about 5 ms per file (1,469 files in 7 s,
36,232 in 231 s); CLI commands start no watcher, the MCP server does.

## Decision

1. **Adapter inside `signals.py`, codegraph knowledge in one private module.**
   `scripts/_codegraph.py` holds every codegraph call: detection, `init`, `sync`, the
   daemon check, the database read, the CLI queries, the environment. `signals.py` loads
   it by path (the `_load_hooks_common` precedent) and swaps the provider at the one place
   `analyse` builds the `Graph`. Consumers of `Graph` (`build_rows`, `blast_radius`,
   `rank_suspects`, `aggregate_dirs`) and the review workflow's `fileRisk` do not change.
   The regex scanner stays where it is, frozen; its deletion after the eval is one region.
2. **File edges from a read-only SQLite read; tests and symbols from the CLI.** The reader
   opens `file:<db>?mode=ro`, then `?immutable=1` on failure, never read-write. It probes
   `schema_versions` and the columns it needs before any query; a mismatch is the reason
   `graph-schema` and the regex scanner runs. Cross-file edges of every kind become the
   file graph. `affected -j` adds the tests a seed set reaches. `impact`, `callers`,
   `callees`, `query` run with `-j`; `node` and `explore` pass text through.
3. **One `graph` passthrough subcommand** gives the phases symbol queries through the
   same preflight: `signals.py graph [--repo R] [--json] <impact|callers|callees|affected|
   query|node|explore> ARGS…`. Skill prose never calls `codegraph` directly.
4. **Detection, trust and build, no config.** Each call takes these steps in order:
   1. **Binary.** `codegraph` is on `PATH`. A `PATH` entry inside the repository is
      skipped. An entry inside an umbrella root is skipped when the umbrella tracks the `codegraph` file in it, or holds it in its `.git`. An
      empty, `.` or relative entry is skipped. Such a binary ships with the code under
      analysis. The search continues along `PATH` to the next acceptable install.
   2. **Version.** `--version` ≥ 1.6.0. Steps 1 and 2 define "present".
   3. **Trust.** The index must not come from the repository itself. `.codegraph`,
      `.codegraph/codegraph.db` and `.codegraph/.gitignore` are not symlinks, and git does
      not track them as symlinks. `.codegraph` resolves inside the root. git tracks no file under it except codegraph's own
      `.codegraph/.gitignore`. No directory spelled like `.codegraph` in another case
      exists, tracked or not. A failure is the reason `graph-index-untrusted`, and the regex
      scanner runs.
   4. **Index.** The file `<repo>/.codegraph/codegraph.db` decides whether the repository
      has an index; `status` does not. The reason: codegraph's `status <path>` walks up to
      an indexed ancestor, so under an umbrella with a root index it answers for the root,
      not for the unindexed child (worklog, T13 live finding).
   5. **Build or sync.** No index and at most 10,000 tracked files: append `/.codegraph/` to
      `git rev-parse --git-path info/exclude` first, then `init -y` under a lock in the git
      common dir, then report `built` once. `status --json` runs only after shipgate's own
      build, to check that its `projectPath` is the repository. Over 10,000 files: no
      build, one advisory line naming the command. With an index: a live daemon means
      query now; otherwise `sync` first. "Daemon alive" means a live pid in `daemon.pid`
      AND a socket at its `socketPath`, or at `.codegraph/daemon.sock` when `socketPath` is
      absent. codegraph puts the socket in the temp directory when the project path is long.

   Every call carries `CODEGRAPH_TELEMETRY=0` and `CODEGRAPH_NO_DAEMON=1`.
5. **The advisories are remembered in the git common dir.** The install advisory is
   remembered as `<git-common-dir>/shipgate/codegraph-advised` of the outermost git tree
   (the umbrella's own `.git` when it is a repository, else the child's). The too-large
   advisory is remembered per repository, as `<git-common-dir>/shipgate/codegraph-too-large`
   of that repository, because the 10,000-file guard is a property of one repository. The
   build lock, `codegraph.lock`, sits in the repository's `<git-common-dir>/shipgate/` too.
   Those paths never appear in `git status`, are scoped to the project, and share the git
   directory with the exclude line, so there is one write target instead of two. A write
   failure there is not an error. The user chose this over a machine-global state file
   (2026-10-19).
6. **Config stays one optional bullet**, `Code graph: auto | off | root` under
   `## Code tooling`, plus a `--graph` flag that overrides it (ADR 0004 §2). `root` uses the
   nearest umbrella root's index when it exists and never builds it.
7. **Amendments to ADR 0004.** §1: the structural adapter table gains a provider above the
   language adapters. §5 "writes nothing": with codegraph present the script causes three
   kinds of write, all outside tracked files: `.codegraph/` (by codegraph, on shipgate's
   own build), one line in `.git/info/exclude`, and three files under
   `<git-common-dir>/shipgate/`. Those three are the build lock `codegraph.lock`, the
   install marker `codegraph-advised` (one per outermost git tree) and the too-large marker
   `codegraph-too-large` (one per repository). With codegraph absent only
   `codegraph-advised` is written, once.

## Alternatives considered

- **CLI only, no database read** (the pragmatic-balance blueprint). Honest about the
  private schema, but it leaves `fan_in`, `fan_out`, suspect proximity and file blast on
  the regex scanner, which is the duplication the user asked to remove, and the CLI BFS
  misses SC-004 by 3 s on a mid-size repository. Rejected on the measurement; it remains
  the fallback shape if the schema probe ever fails.
- **Three modules and a 440-line move of the regex scanner** (the clean-architecture
  blueprint). Correct boundaries, but the move is churn on frozen code that the eval may
  delete, and golden tests to prove a byte-identical move cost more than they protect.
  Its provider seam, test shim and state-dir advisory are adopted.
- **A sibling `graph.py` script.** Two commands for one axis; repo resolution, config and
  the envelope would be duplicated. Rejected.
- **Skill prose calling `codegraph` directly.** Telemetry, `-p`, freshness and fallback
  repeated in seven skills and untestable. Rejected.
- **A hunk-to-symbol mapper for Route & Map.** `nodes.start_line/end_line` make it
  possible, but the model can name the changed functions from `git diff -U0`. Deferred
  until the eval shows misses.
- **Advisory in `${XDG_STATE_HOME:-~/.local/state}/shipgate/`.** Touches the repository
  not at all, but it is a machine-global file keyed by path: stale when a repository
  moves, invisible to the user, and "once per project" becomes "once per path". The
  orchestrator proposed it; the user rejected it for the git common dir.

## Consequences

- Phases keep one command and one output shape. `structure.source` says `graph` or
  `regex`; `blast.tests` and `structure.graph` are new, additive keys. `OUTPUT_VERSION`
  stays 1.
- The reader couples to codegraph's schema. The probe, a recorded `schema.sql` fixture, a
  live opt-in test on each codegraph upgrade, and the regex fallback bound the risk. An
  upstream request for a file-edge export would retire the reader without other change.
- `signals.py` now writes, in three bounded places, none of them tracked. The
  `test_writes_nothing` test splits into "absent: only the marker under `.git/shipgate/`,
  once" and "present: the index, the exclude line and the marker".
- Hooks are untouched. A test fails if any file under `hooks/` names codegraph.
- The first call on an unindexed repository pays the build (7 s per 1,500 files). SC-004
  holds from the second call; the build is reported so the pause is explained.
