---
type: worklog
title: "Worklog: HUD and shipgate version skew"
created: 2026-10-20
updated: 2026-10-20
tags:
  - worklog
  - shipgate-hud
status: reviewed
prd: ""
related:
  - "./session-stream-attribution.worklog.md"
  - "../adr/0001-sibling-plugin-fed-by-the-journal-cli.md"
  - "../adr/0005-the-publish-gate-checks-the-published-branch.md"
---

# Worklog: HUD and shipgate version skew

> A follow-up to shipgate-hud 0.6.0. No PRD: the user approved the two changes below.

# Design

## Problem

shipgate-hud 0.6.0 reads its facts from shipgate 0.18.0: the new `status --json` keys and
`journal.py position`. A project can run an older shipgate beside the new HUD. A
project-level install can lag, and so can a `journalScript` option that points at an old
checkout. Today that skew shows the pane message "needs shipgate 0.18.0". The publish gate
reads the failure as Unreadable and holds every push until shipgate catches up.

## Decisions (the user's, after the folding question)

The HUD stays a separate plugin, as ADR 0001 decided.

1. **Declare the dependency.** `shipgate-hud/.claude-plugin/plugin.json` gains
   `"dependencies": [{ "name": "shipgate", "version": ">=0.18.0" }]`.
   - **What Claude Code does with it:**
     - Installing or updating the HUD installs or updates shipgate.
     - shipgate is referenced by a relative path, so the range resolves against
       `shipgate--v<version>` tags on the marketplace repository.
     - With no matching tag, Claude Code uses the marketplace's current copy, and it checks
       the range when the plugin loads. A shipgate outside the range keeps the HUD disabled,
       and `claude plugin list` names the requirement.
   - **The tag:** the marketplace repository gets the tag `shipgate--v0.18.0` at the commit
     that released shipgate 0.18.0.
2. **Fail soft when shipgate is too old.** The HUD treats "journal.py is older than 0.18.0"
   as a known state, not as a read failure.
   - **The pane** says that shipgate is older than 0.18.0 and the publish gate is off, and
     how to update.
   - **The band** draws one short notice line, so the person sees that the gate is off.
   - **The gate** passes, as it does when `journal.py` is not found. It is a net for a
     forgetful model, not a boundary, and holding every push during a known mismatch only
     trains people to press "Let it through once".
   - **A transient failure still holds:** a locked database, a crash, a cut.

## How "older than 0.18.0" is detected

journal.py has no version command. Two signs are certain:
- **`position` is unknown.** A `position` run exits 2 with argparse's usage text, which
  names `invalid choice: 'position'` or an unrecognized argument. That is today's
  `RunFailure.Unsupported`.
- **The 0.18 marker is missing.** `status --json` has no top-level `nested_matches` key.
  From 0.18.0 on, `status` always prints that key (ruling R3).

Any other shape error stays `BadShape`, which is a failure that holds.

---

# Build Plan

- [x] T001 — types first: an `Outdated` state through the refresh result, the stored view
  and the gate inputs, and a pass reason. The detection of the 0.18 marker lives in
  `journal.ts`, and `Unsupported` maps to Outdated — file(s): `types/index.d.ts`,
  `hooks/journal.ts`, `hooks/register.tsx`, `hooks/publish.ts`, `hooks/views.tsx` — done
  when: `tsc` passes and the declarations are reviewed.
- [x] T002 — bodies and tests:
  - each of these, on an older shipgate, gives Outdated: a status without `nested_matches`,
    and a `position` that argparse refuses;
  - the pane and the band draw the notice;
  - the gate passes with the reason named;
  - a BadShape or an Exited run still holds.

  File(s): the same, plus `tests/*` — done when: the failing-first tests pass, the suite is
  green, and `validate` passes.
- [x] T003 — the dependency in `plugin.json`, the `shipgate--v0.18.0` tag, README "What it
  needs", the CHANGELOG entry 0.6.1, and `marketplace.json` — done when: `validate` passes
  with the dependency, and the versions are in lockstep.

---

# Review

The orchestrator gated this change directly, with no reviewer fan.
- **Size and shape.** The diff touches one plugin. It mirrors the existing
  `NoJournalScript` pass, which lets a publish through when `journal.py` is not found.
- **Types first.** The declarations were reviewed before any body was written.
- **Security.** A project cannot fake the `Outdated` state.
  - The HUD never takes `journal.py`'s path from the project, only from the plugin
    folders or the user's `journalScript` option.
  - journal.py 0.18.0 always prints `nested_matches`, whatever the project's journal holds.
  - Any other failed read still holds the gate.

**Verdict: Ready.**
- **HUD tests:** `claude plugin test shipgate-hud` gives 814 pass and 0 fail.
- **Type-check:** `tsc` exits 0, with the tests included.
- **Validation:** `validate` passes with the declared dependency.
- **Failing first:** 703 pass and 111 fail with the bodies stubbed. With the lookup reset
  removed, the update test fails.
