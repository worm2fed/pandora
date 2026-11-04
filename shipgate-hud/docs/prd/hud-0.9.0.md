---
type: prd
title: "PRD: HUD 0.9.0 and shipgate 0.22.0 — finding text without a board, labels, case-folded paths, release files out of the ranking, a checked sidecar version"
created: 2026-11-04
updated: 2026-11-04
tags:
  - prd
  - shipgate-hud
  - shipgate
status: clarified
issue: "#12, #13"
worklog: "./hud-0.9.0.worklog.md"
related:
  - ../adr/0008-the-review-tab-reads-folded-dispositions.md
  - ../adr/0009-the-verdict-only-round-reads-the-worklog.md
  - ../../../shipgate/docs/adr/0009-the-journal-computes-the-hud-position.md
  - ../../../shipgate/docs/adr/0013-signals-emits-the-ranking-the-journal-carries.md
  - ../../../shipgate/docs/adr/0014-a-finding-disposition-is-recorded-when-it-is-decided.md
---

# PRD: HUD 0.9.0 and shipgate 0.22.0

> The verdict-only review round shows one line of finding text per key, read from the
> worklog. A disposition can carry a short label. A finding path that differs only by case
> is one finding. Release files leave the risk ranking. Every sidecar reader checks the
> sidecar's `version`.

## Problem

1. **The verdict-only round has no text (#12).** The journal holds keys and states only.
   The round draws `<key>  <state>` and nothing else, so the reader cannot tell what a
   finding was. The text lives in the worklog's review section.
2. **Keys drift from the skill's format (#12).** An orchestrator wrote free labels
   (`flush-older-sync`) as keys. A free label never matches a card or a worklog location.
3. **A board looked lost after a reload (#12).** The issue reports the board gone after a
   plugin reload. The board is held in a `$.state` atom (`shipgate-hud.review-v2`) since
   0.6.0, and the engine keeps `$.state` across `/reload-plugins`. Nothing pins that.
4. **One finding, two cards (#13).** The review Workflow dedupes by path and line, but folds
   only a leading `./`. Two lenses that spell the path in another case give two cards. The
   HUD's key match has no case-folded tier, so a disposition reaches one card.
5. **Release files crowd READ FIRST.** Every release churns `CHANGELOG.md`, `plugin.json`
   and `marketplace.json`, so they rank `top` and push product code out of the five ranked
   files.
6. **The sidecar version is never read.** `.claude/shipgate.json` carries `"version": 1`.
   No reader checks it, so a newer sidecar would be read silently.
7. **An open session lags a release.** A session opened before a shipgate release keeps the
   old shipgate. The HUD's dependency range then refuses to load the HUD, and an
   organization-managed PreModelSwitch check can block `/model` until `/reload-plugins`.
   The README does not say so.

## Goals & non-goals

**Goals**
- The verdict-only round shows what each finding was.
- A disposition key is a location; a human name travels beside it.
- One finding is one card, whatever the case of its path.
- The ranking names product code first.
- A newer sidecar is visible, never a failed read.

**Non-goals**
- No finding text in the journal: the 1 KB cap and the "pointer, not prose" rule stay.
- No board kept across sessions (`/clear`, `--resume`, a new process).
- No change to the hotspots table: only `ranking` leaves release files out.
- No change to what `package.json` churn means.

## Functional requirements

**shipgate 0.22.0**
- **FR-001** — `review-disposition` accepts an optional `labels`: a JSON object from a
  finding key to a non-empty string. A new shape rule kind, `string_maps`, checks it.
  `vocab --shape review-disposition` prints it.
- **FR-002** — `position --json`'s `dispositions` entries gain `label`: the newest label a
  `review-disposition` gave that key (after `./` is dropped), or null. A later event
  without a label keeps the earlier one. No existing key is renamed or removed.
- **FR-003** — The `review` skill says a disposition key is the finding's
  `<path>:<line|?>`, never an invented label, and shows `labels` for a human name.
- **FR-004** — `review-workflow.js` folds path case in the dedupe key and in the `fileRisk`
  lookup. A merged card keeps the first finder's spelling of the path.
- **FR-005** — `signals.py`'s `ranking` leaves out files that match a release pattern. The
  built-in patterns are `**/CHANGELOG.md`, `**/.claude-plugin/plugin.json` and
  `.claude-plugin/marketplace.json`. The hotspots table and `files` keep every file.
- **FR-006** — The config's `## Code signals` section takes a `Ranking exclude:` bullet with
  backticked globs. It replaces the built-in patterns. An empty backticked value disables
  them. `config.ranking_exclude` in the JSON shows the patterns in force. The config
  template and the README document the bullet.
- **FR-007** — `hooks/_common.py` and `journal.py` warn on a sidecar whose `version` is an
  integer higher than the one they know (1), and keep working with the keys they know. The
  SessionStart hook carries the warning once per session. `journal.py` prints it once per
  run on stderr. `doctor` reports the sidecar's version and its stray keys.
- **FR-008** — `setup`'s update mode rewrites a sidecar that holds keys the template does
  not name, and says which keys it dropped.

**shipgate-hud 0.9.0**
- **FR-009** — The HUD parses the worklog's review section: every list item under a
  `Review round …` or `Rejected findings` heading. Each item gives its first backticked
  `<path>:<line|?>` location (or none) and the first sentence after it.
- **FR-010** — The verdict-only round prints one dim line under each key: the first
  sentence of the item that matches it. A key with no match stays bare.
- **FR-011** — The match order is: the exact key; a path tail on the same line, case
  folded; then the label (the key's `label`, or the key itself when it is no location) as
  a whole word in the item's text. The first item in worklog order wins in each tier.
- **FR-012** — The verdict-only round prints a key's label beside the key when it has one.
- **FR-013** — A board captured in a session is drawn again after `/reload-plugins`: the
  `$.state` atom keeps it, and a test pins it.
- **FR-014** — `dispositionsFor` gains a case-folded tier after the exact and short-location
  tiers. A key labels every card at the same folded location (path and line). The path-tail
  tiers compare folded paths too. The one-card-per-key rule stays for pass 2 only.
- **FR-015** — A sidecar whose `version` is an integer higher than 1 draws one warning line
  in the pane. The refresh still runs with the keys the HUD knows.
- **FR-016** — The README's "What it needs" has one paragraph on a session opened before a
  shipgate release.
- **FR-017** — The dependency is shipgate `>=0.22.0`. The read floor stays 0.21.0.

## Success criteria

- **SC-001** — A stream with a verdict, dispositions and a worklog review section shows each
  key with one line of text in the verdict-only round (a view test).
- **SC-002** — A board captured in a session is still drawn after a reload in that session:
  `$.state` kept and `session.start` run again (a register test). The test kit cannot reload
  the module, so the test leaves module state as it is; the board reads nothing from module
  state, so the claim holds without it.
- **SC-003** — `review-disposition` accepts `labels` and refuses a non-object map and a
  non-string or empty label; `position --json` prints the newest label per key; the skill
  text names the key format and the label.
- **SC-004** — The review Workflow merges `src/widget/widget.test.ts:?` and
  `src/widget/Widget.test.ts:?` into one card with the first spelling, and a `fileRisk` key
  in another case labels the finding (a workflow test).
- **SC-005** — A key labels both cards at one case-folded location; the pass-2 tail fallback
  still reaches one card (review tests).
- **SC-006** — The ranking skips a churned `CHANGELOG.md`, `plugin.json` and
  `marketplace.json`; the table keeps them; `Ranking exclude:` replaces and an empty value
  disables the built-in (signals tests).
- **SC-007** — A sidecar with `version` 2 makes the hooks, `journal.py` and the HUD warn
  once and keep working; `doctor` reports stray keys (tests on both sides).
- **SC-008** — Every check is green: shipgate's unit tests, `claude plugin validate` for
  both plugins, `claude plugin test shipgate-hud`, `tsc`.

## Constraints & assumptions

- Public repo: nothing employer- or customer-specific (root `CLAUDE.md`).
- shipgate's scripts stay Python 3.9 compatible.
- `hooks/` is a security-sensitive area: a hook change must keep the no-op path for a
  project with no sidecar.
- Payload shapes change additively only.

## Assumptions (executive)

- Worklog read in the HUD or in `position --json`? → the HUD — finding text is display, as
  the Design sections are; `position` stays the place for rules (shipgate ADR 0009). HUD
  ADR 0009 records it.
- Board persistence → keep the `$.state` atom — the engine keeps `$.state` across
  `/reload-plugins`, and the stored board's decoder is unchanged since 0.6.0. A task-output
  re-read needs the path, which is module state a reload loses; `$.store` would write a file
  across sessions, and the HUD writes nothing. HUD ADR 0009 records it.
- The review section's grammar → list items under a heading whose text starts with
  `Review round` or is `Rejected findings`, at any level, up to the next heading at the same
  or a higher level — that is what the review skill writes.
- Labels in the journal → a short name only, never the finding's text; the 1 KB cap holds.
- Read floor → 0.21.0 — a 0.21.0 `journal.py` prints no `label`; the entry reads with a null
  label. The dependency `>=0.22.0` installs the version that prints it.
- Case fold in the tail tiers → yes — a workflow reports absolute paths, so the exact tier
  rarely sees the issue's case pair.
- `Ranking exclude` matching → read as an `Exclude` glob is read, a leading `**/` optional.
- Unknown sidecar version → an integer higher than 1; an absent or lower value is version 1.
- `signals.py` → no check — it reads no sidecar key; it only tests that the file exists.

## Open questions

None.
