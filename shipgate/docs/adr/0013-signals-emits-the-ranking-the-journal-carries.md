---
type: adr
title: "0013. signals.py emits the ranking the journal carries"
created: 2026-11-02
updated: 2026-11-04
tags:
  - adr
  - shipgate
status: accepted (amended 2026-11-04, shipgate 0.22.0)
date: 2026-11-02
issue: "#10"
related: ["0004-code-signals-on-demand-stdlib-script.md", "0007-codegraph-as-detected-structure-provider.md"]
---

# 0013. signals.py emits the ranking the journal carries

> `signals.py hotspots --json` adds a top-level `ranking` object. The `design` and
> `review` skills copy it into `design-committed` and `review-verdict` as it is.

> **Amended 2026-11-04 (shipgate 0.22.0):** `ranking` leaves out release files before it
> takes its 5 rows: `**/CHANGELOG.md`, `**/.claude-plugin/plugin.json` and
> `.claude-plugin/marketplace.json`. Every release churns them, so they ranked `top` and
> pushed product code out of READ FIRST. The patterns are read as `Exclude` globs are, with
> a leading `**/` optional. The config's `Ranking exclude:` bullet replaces them, and an
> empty backticked value turns them off. The hotspots table and `files` keep every file;
> `config.ranking_exclude` names the patterns in force.

## Context

Issue #10: `design-committed` and `review-verdict` must carry the risk ranking each phase
used, the top files with their `fix`, `churn` and `fan_in` labels, under the 1 KB cap. The
hotspots JSON holds every label, but the row form is large and the label names differ from
the issue's words (`fix_rate`, `commits`). A ranking that each orchestrator assembles by
hand will differ in shape from stream to stream, and `stats` cannot read it.

## Decision

`signals.py hotspots --json` gains `ranking`:
`{"source": <structure.source or "none">, "files": [{"path", "fix", "churn", "fan_in"}]}`.
`files` takes the first 5 rows of the JSON's own order (risk, then fixes, then commits).
It is a list, not an object keyed by path, because both `signals.py` and the journal
print JSON with sorted keys, and an object would lose the order.
Each path is cut to its last 3 segments, the form the review dispositions already use. A
label is `low`, `mid`, `high`, `top` or null. When the signals are unavailable, `ranking` is
`{"source": "none", "unavailable": <reason>}`. The journal validates the same shape on both
events. The output stays at `OUTPUT_VERSION` 1, because the key is new.

## Alternatives considered

- **The orchestrator builds the payload from the rows.** It needs no script change, but
  it leaves the shape to each run. That is how 3 of 6 signal payloads came to name no
  source.
- **A new `ranking` subcommand.** It is explicit, but it runs a second git pass for data
  that the phase's own hotspots call already computed.

## Consequences

- One copy step per phase, and `stats` reads one shape.
- The ranking is a summary. The full table stays in the reviewer brief and the conversation.
- The 5-file cap and the 3-segment paths keep the object near 400 bytes. A
  `review-verdict` with many dispositions may still need the ranking trimmed to 3 files.
