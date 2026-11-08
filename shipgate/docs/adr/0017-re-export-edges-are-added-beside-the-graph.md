---
type: adr
title: "0017. Re-export edges are added beside the graph, in signals.py"
created: 2026-11-07
updated: 2026-11-07
tags:
  - adr
  - shipgate
  - code-graph
status: accepted
date: 2026-11-07
issue: "#7"
related:
  - "0007-codegraph-as-detected-structure-provider.md"
  - "../prd/shipgate-0.24.0.md"
---

# 0017. Re-export edges are added beside the graph, in signals.py

> On the graph arm, `signals.py` scans every indexed TypeScript and JavaScript file once
> and adds two kinds of edge the codegraph index lacks: a barrel's `export … from` edges,
> and an importer's edge to a workspace package's entry file for a bare package import.
> The pass lives in `signals.py` beside the regex scanner, reuses its resolver, and leaves
> `_codegraph.py` and the regex arm as they are. Decided in executive mode; the user can
> veto.

## Context

codegraph 1.6.2 records no edge for `export * from "<spec>"`. In the index of eval case 72,
12 files hold such a line and none has a cross-file out edge; a barrel file holds one `file`
node and nothing else. A three-file repro (worklog, **Upstream**) shows the same: `b.ts`
imports from `index.ts`, `index.ts` re-exports `a.ts`, and the index holds `b -> a` and
`b -> index` but nothing from `index`. codegraph resolves a named import through the barrel
to the symbol's own file, which is why one barrel costs nothing.

A second gap shows on a bare workspace-package import. `scanRebateSet.ts` imports a name
from `@app/notify`; codegraph resolves it to the symbol's file and records no edge to the
package's entry `packages/notify/src/index.ts`. That entry re-exports a file that imports
the hub. So re-export edges alone reach 58 of 59 true files on case 72. The file the brief
names, the one behind the second barrel, needs the edge to the entry too.

The regex scanner is frozen (ADR 0007 §1). Its arm is the eval's control; a resolver change
there would move the regex arm's numbers and blur the ablation.

## Decision

1. **A pass in `signals.py`, after the index read.** `graph_structure` calls
   `_codegraph.read_file_graph` as before, then `reexport_edges(root, files, tracked)` over
   the TypeScript and JavaScript files the graph kept, and merges the edges into the
   `FileGraph`'s `out` and `inn`. `_codegraph.py` is unchanged: it holds codegraph calls
   only.
2. **Two kinds of edge.** For each file: every `export * from`, `export * as x from`,
   `export { … } from`, `export type { … } from`, `export type * from` and
   `export type * as x from` whose specifier resolves to a file in the graph gives
   `file -> target`. The brace list is read up to the next brace, so a brace inside an
   inline comment within the list ends the match; a line that starts with a comment
   marker is dropped first. Every `import … from "<name>"` or `require("<name>")`
   whose `<name>` is the bare name of a workspace package gives `file -> entry`. A subpath
   import adds nothing: codegraph resolves it. Relative specifiers resolve through
   `_resolve_ts` with the regex scanner's `GraphContext` rules. The workspace map comes from
   the root `package.json` `workspaces` globs (`dir/*` and literal directories), each
   package's `name`, and its entry: `exports["."]` as a string, or its `import` or `default`
   member, else `main`, else the package directory's `index` file, probed with the regex
   scanner's extension rules.
3. **Bounds.** Each file is read once with `_read_text`: no symlink, no special file, no
   file over `MAX_SCAN_BYTES` (1 MiB), nothing outside the repository. A file that cannot
   be read adds no edge. The set of files is the graph's own, already capped by
   `MAX_FILES`.
4. **The JSON.** `structure.source` stays `graph`. The `structure.graph` block gains one
   additive integer, `reexport_edges`: the number of edges the pass added. No note is
   printed. `files_scanned`, `status` and `unresolved` are unchanged.
5. **The regex arm is unchanged.** The pass runs only when the index answered.

## Alternatives considered

- **A callback into `read_file_graph`.** The brief's first reading. It keeps the merge in
  one place but makes `_codegraph.py` call a resolver it does not own, and the shim tests
  of the reader would then need a resolver. Rejected: the reader stays a reader.
- **Teach `_resolve_ts` workspace names and let the regex scanner find the re-exports.**
  The regex arm would then reach most of case 72 and the ablation would lose its control.
  ADR 0007 froze the scanner for that reason. Rejected until the eval retires it.
- **Wait for an upstream fix.** The repro goes to the maintainer either way; the eval runs
  now. Rejected as the only step.

## Consequences

- A graph call now reads every TypeScript and JavaScript file of the graph once (1 MiB
  cap each). The regex scanner does the same read on its arm, so the cost is the one
  already measured there, and SC-004 of the code-graph PRD (5 s) holds on the sizes the
  eval uses.
- A barrel is an importer of what it re-exports, so a change to a re-exported file lists
  the barrel in `blast.files`. That is the file-level truth the eval fixtures record.
- A bare import of a workspace package makes the importer depend on the whole entry file,
  not on the one symbol it uses. That over-approximates at the symbol level and matches the
  file-level truth.
- codegraph's own edge export, when it arrives, retires the pass without other change.
