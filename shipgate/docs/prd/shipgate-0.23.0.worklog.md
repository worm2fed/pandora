---
type: worklog
title: "Worklog: shipgate 0.23.0 and shipgate-hud 0.10.0"
created: 2026-11-06
updated: 2026-11-06
tags:
  - worklog
  - shipgate
  - shipgate-hud
status: reviewed
prd: "./shipgate-0.23.0.md"
issue: "#1, #6, review findings stuck at fixing"
related:
  - ../adr/0014-a-finding-disposition-is-recorded-when-it-is-decided.md
  - ../adr/0015-the-user-approves-a-publish-outside-the-model-tools.md
  - ../adr/0016-the-signal-grader-runs-outside-the-harness.md
  - ../../../shipgate-hud/docs/adr/0008-the-review-tab-reads-folded-dispositions.md
  - ../../../shipgate-hud/docs/adr/0010-the-publish-dialog-records-the-approval.md
---

# Worklog: shipgate 0.23.0 and shipgate-hud 0.10.0

# Design

## Approach

Minimal change. The lead decided the shape of #1 (a hook and a dialog marker); ADR 0015
records the details and HUD ADR 0010 the dialog. The publish rule stays in one helper,
`publish_authorization`, and the HUD reads its result, so one change covers the gate, the
status brief and the HUD. The two closure refusals live in `append`, where the payload is
checked (ADR 0014, amended). The HUD's stale `fixing` is display only (HUD ADR 0008,
amended). The signal grader is a script outside the harness (ADR 0016).

## shipgate 0.23.0

- **Marker and rule (ADR 0015).** `gate-decision` gains `enums.source: [dialog, shell]`.
  `_authorizes_publish` also needs a `source` in that enum, and `publish_authorization`
  needs the event's actor role to be `user`. `_validate_mr_opened`'s message names the
  dialog and `!` and drops "take the publish decision with the user" as a thing to record.
- **Location keys (ADR 0014, amended).** One helper, `is_location_key(key)`, mirrors the
  HUD's `parseLocation`: split at the last `:`, path non-empty after `./` is dropped, line
  digits or `?`. `normalize_payload` refuses another key in `review-disposition`'s
  `dispositions` and `labels` and in `review-verdict.dispositions`, with a hint to put the
  name in `labels`. A new shape rule kind is not needed: the check runs after the shape.
- **The ready refusal.** `_validate_review_verdict` folds the stream's dispositions as
  `position` does, applies the verdict's own map, and refuses `ready` when a `fixing` key
  stays. The message lists up to 10 keys (and the count of the rest) and prints the
  closing row:
  `journal.py append --stream <s> --type review-disposition --data '{"round": N,
  "dispositions": {"<key>": "fixed", ...}}'`. `append_event` refuses `--force` without
  `--force-reason` on that verdict, as the payload cap does.
- **The hook (ADR 0015).** `hooks/pre_tool_use.py` and a `PreToolUse` entry in
  `hooks/core.json`, matcher `Bash`, timeout 10. Its own lexer; no import from journal.py,
  so the fast path stays small.
- **Golden contract.** Golden rows with free-label keys become locations. A marked user
  publish decision joins a stream so the regenerated `fixtures.journal.ts` carries it.
- **Skills.** `review`: the fix round closes every `fixing` key before the verdict; the
  ledger line moves into "Keep the keys compact". `feature` and any other text that told
  the model to record the user's publish decision now sends it to the user.
- **Evals (ADR 0016).** `evals/signal_grader.py`; `expected.json` for case 13;
  `run-case.sh` runs the grader; `evals/README.md` documents it.

## shipgate-hud 0.10.0

- **The dialog (HUD ADR 0010).** `askToPass` returns one of three answers. On
  `Approve publishing` the gate appends one marked decision per distinct `Unreviewed`
  stream through `$.process.run`, then passes. A failed append still passes.
- **Stale `fixing` (HUD ADR 0008, amended).** One pure predicate, `isStaleFixing(entry,
  verdict)`: state `fixing`, the last verdict `ready`, the entry's seq below it.
  `liveFixing`, `isOpenState` and the two draws (card state, verdict-only round) use it. A
  stale entry draws dim `fixing?`.
- **README and release.** The boundary paragraph, the dialog's third answer, the HUD now
  writes one event per approval, the double reload. `plugin.json` 0.10.0 with shipgate
  `>=0.23.0`; the read floor stays 0.21.0.

## CLAUDE.md / impact-map compliance

- Public repo: generic paths only (`src/widget/...`); the diff is grepped before review.
- `hooks/` is security-sensitive: the full `/security-review` runs on the hooks diff.
- Python 3.9: no `match`, no runtime `X | Y`.
- Two version bumps in lockstep with `marketplace.json`; release notes only in the
  changelogs.

# Build Plan

## shipgate 0.23.0

- [x] T001 — journal.py: `source` marker, the publish rule with marker and actor, the
  `mr-opened` message, location keys in three maps, the `ready` refusal over open `fixing`
  with `--force-reason`; journal tests; golden rows to locations plus a marked decision;
  `fixtures.journal.ts` regenerated. — files: `shipgate/scripts/journal.py`,
  `shipgate/tests/test_journal.py`, `shipgate/tests/test_hud_contract.py`,
  `shipgate-hud/tests/fixtures.journal.ts`
- [x] T002 — hooks: `pre_tool_use.py`, the `PreToolUse` entry; hook tests. — files:
  `shipgate/hooks/pre_tool_use.py`, `shipgate/hooks/core.json`,
  `shipgate/tests/test_hooks.py`
- [x] T003 — skills: `review` (close every `fixing`, the promoted ledger line), `feature`
  and other publish texts; the ledger line removed. — files: `shipgate/skills/**`,
  `docs/ledger.md`
- [x] T004 — evals: `signal_grader.py`, `expected.json` for case 13, `run-case.sh`, the
  evals README; the offline proof. — files: `shipgate/evals/signal_grader.py`,
  `shipgate/evals/13-blast-radius-explicit/expected.json`,
  `.claude/skills/run-evals/scripts/run-case.sh`, `shipgate/evals/README.md`
- [x] T005 — README boundary paragraph, CHANGELOG 0.23.0, `plugin.json` and
  `marketplace.json` 0.23.0. — files: `shipgate/README.md`, `shipgate/CHANGELOG.md`,
  `shipgate/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

## shipgate-hud 0.10.0

- [x] T006 — the dialog's approve answer and its record; the deny text; register tests. —
  files: `shipgate-hud/hooks/register.tsx`, `shipgate-hud/hooks/publish.ts`,
  `shipgate-hud/tests/register.test.ts`, `shipgate-hud/tests/publish.test.ts`
- [x] T007 — stale `fixing`: the predicate, the band, the open count, the two draws; view
  tests. — files: `shipgate-hud/hooks/views.tsx`, `shipgate-hud/tests/views.test.tsx`
- [x] T008 — README (boundary, dialog, reload note), CHANGELOG 0.10.0, `plugin.json` 0.10.0
  with `shipgate >=0.23.0`, `marketplace.json`. — files: `shipgate-hud/README.md`,
  `shipgate-hud/CHANGELOG.md`, `shipgate-hud/.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`

# Review

## Review round 1

Review Workflow run `wf_e2742733-bde`: three lenses (correctness, conventions+design,
simplicity+security), Opus finders, `verify: high-only`. Counts: 21 found, 20 after dedupe,
4 candidates over the floor of 60, 0 refuters (no BLOCKER or HIGH), 4 survivors, 0 killed,
16 below the floor. The orchestrator reproduced each hook survivor by running the hook on the
command: each one printed nothing, so the forged append passed. Verdict: not ready.

- F1 MEDIUM `shipgate/hooks/pre_tool_use.py:838` — an unquoted variable used as an option value can split into a later `--type gate-decision`, and the hook passes the append.
- F2 MEDIUM `shipgate/hooks/pre_tool_use.py:684` — a wrapper with arguments before `sh -c` or `bash -c` (`timeout 5`, `nice -n 5`) hides the payload from the hook.
- F3 MEDIUM `shipgate/hooks/pre_tool_use.py:797` — a variable in the subcommand position (`journal.py $SUB`) is never read as an append.
- F4 LOW `shipgate/README.md:177` — one line of the rewritten paragraph runs to 123 columns.

### Rejected findings

- `shipgate/skills/review/SKILL.md:571` (LOW 55): the skill loader replaces `${CLAUDE_PLUGIN_ROOT}` with the installed path when it renders the skill, so the user sees a real path.
- `shipgate-hud/hooks/register.tsx:1425` (LOW 55): deferred; a refresh that resets the script lookup during the dialog loses the record, the line still passes and the next publish asks again.
- `shipgate/hooks/pre_tool_use.py:933` (LOW 55): `jour''nal.py` is deliberate obfuscation, out of scope by ADR 0015.
- `shipgate/hooks/pre_tool_use.py:924` (LOW 55): the hook keeps its own stdin read on purpose, so the fast path imports nothing from `_common`.
- `shipgate-hud/hooks/register.tsx:1413` (LOW 50): `recordApproval` needs the exit code and no JSON decode, which `runJournal` does not give.
- `shipgate/hooks/pre_tool_use.py:79` (LOW 50): `env -S` is covered by the F2 fix, which lexes every literal word that holds `journal.py` and `append`.
- `shipgate-hud/hooks/register.tsx:1403` (LOW 45): naming only; `askToPass` still asks whether to pass.
- `shipgate/docs/adr/0015-the-user-approves-a-publish-outside-the-model-tools.md:52` (LOW 45): taken with the F2 fix; §5 is rewritten to match the hook.
- `shipgate/hooks/pre_tool_use.py:850` (LOW 40): a refusal of a non-write command with `journal.py`, `append` and a variable is the fail-closed rule working as designed.
- `shipgate/hooks/pre_tool_use.py:171` (LOW 40): the HUD's lexer is TypeScript and finds publish commands; the hook runs in Python with no HUD installed.
- `shipgate/README.md:217` (LOW 35): the sentence on older journals is a fact a user needs today, not a release note.
- `shipgate/scripts/journal.py:1201` (LOW 30): a blank `--force-reason` passes the payload cap's check too; the closure check follows that pattern.
- `shipgate/scripts/journal.py:1139` (LOW 30): no `KeyError` can occur; a verdict's map takes only closed states, so every open key comes from the fold.
- `shipgate-hud/docs/adr/0010-the-publish-dialog-records-the-approval.md:52` (LOW 30): the ADR's Context names the README rule it replaces.
- `shipgate/skills/review/SKILL.md:572` (LOW 25): the brief states that a `!` command does not reach PreToolUse; the README names it.
- `shipgate-hud/hooks/publish.ts:1282` (LOW 25): a stream named with a leading `-` is not a branch git accepts.

## Review round 2

One reviewer with all lenses on the fix diff (the hook, its tests, ADR 0015 §5–6, the
CHANGELOG hook bullets). F1, F3 and F4 are confirmed fixed on evidence; F2 is fixed for the
`-c` form. The reviewer ran `test_hooks.py` (108 tests, OK) and fuzzed the lexer with 80,000
random lines (0 crashes, 0 hangs). Verdict: not ready. This is the second round, so the open
list goes to the lead.

- F5 HIGH `shipgate/hooks/pre_tool_use.py:745` — a wrapper before a shell that reads its script on stdin (`timeout 60 bash <<'EOF'`, `echo … | timeout 60 bash`, `sudo -u bob bash <<EOF`) still hides the append.
- F6 MEDIUM `shipgate/hooks/pre_tool_use.py:836` — `--db="$DB"` before `append` is read as a subcommand from a variable, so a user's clarify decision is refused.
- F7 MEDIUM `shipgate/hooks/pre_tool_use.py:110` — the unreadable-payload message asks for a literal payload, but an unquoted `--stream $S` or `journal.py $SUB` is the cause, so the hint does not help.
- F8 MEDIUM `shipgate/hooks/pre_tool_use.py:968` — the text-only exemption reads the command name, so `timeout 30 git commit -m '…journal.py append…$S'` is refused, and `command_name` skips no option value (`sudo -u bob` gives `bob`).
- F9 LOW `shipgate/hooks/pre_tool_use.py:85` — `sed -i` or `claude -p` with a text that names an append and a `$` is refused.
- F10 LOW `shipgate/hooks/pre_tool_use.py:85` — `git -c alias.x='!sh -c …'` and `git rebase -x` pass through the text-only exemption; deliberate, out of scope by ADR 0015.
- F11 LOW `shipgate/hooks/pre_tool_use.py:748` — `{ echo …; } | sh` and `(echo …) | sh` pass, since the shell's script is unreadable and the rule fails closed only for payloads.
- F12 LOW `shipgate/hooks/pre_tool_use.py:359` — an unquoted glob character in an append's words is refused as unreadable.
- F13 LOW `shipgate/hooks/pre_tool_use.py:32` — one docstring line runs to about 118 columns.

## Review round 3

The lead allowed a third round past the two-round cap: fix F5–F8, F11 and F13, and write
F9, F10 and F12 into ADR 0015 as known limits. One reviewer with all lenses re-read the fix
diff. It confirmed F5, F6, F7, F8, F11 and F13 fixed on evidence, ran `test_hooks.py`
(110 tests, OK) and fuzzed the lexer with 56,000 inputs (0 crashes). Its one new MEDIUM came
from round 2's `wrapped()`. That fix is one condition: a word is lexed again only when it
holds a word break. The orchestrator checked it by running the hook on the reviewer's
commands, so no fourth reviewer ran. The ADR text came from the orchestrator.

- F14 MEDIUM `shipgate/hooks/pre_tool_use.py:1095` — a single word that holds `journal.py` and `append` (a pytest node id) was lexed again until the depth limit and refused; fixed with the word-break condition.
- F15 MEDIUM `shipgate/docs/adr/0015-the-user-approves-a-publish-outside-the-model-tools.md:50` — §5 and §6 no longer matched the code and the CHANGELOG; rewritten.
- F16 LOW `shipgate/hooks/pre_tool_use.py:650` — `sudo -Hu bob` names the wrong program; a known limit in ADR 0015.
- F17 LOW `shipgate/hooks/pre_tool_use.py:347` — `bash <(…)` and `tee >(bash)` are not lexed; a known limit in ADR 0015.
- F18 LOW `shipgate/hooks/pre_tool_use.py:1056` — the stdin fallback refuses `python3 - <<'EOF'` that holds a forged append, and an unknown wrapper before a stdin script with a variable payload passes; both are known limits in ADR 0015.

### Rejected findings

- `shipgate/hooks/pre_tool_use.py:154` (LOW 70): the split message also shows for a quoted `"$SUB"`; its second half, "write the subcommand literally", applies there.
- `shipgate/hooks/pre_tool_use.py:1137` (LOW 40): a subcommand from a variable with no literal `append` on the line passes the fast path; Bash calls keep no variables between calls, and ADR 0015 lists it.
