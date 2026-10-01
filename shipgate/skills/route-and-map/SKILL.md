---
name: route-and-map
description: Impact analysis for a change — where it belongs and what it touches. Computes the blast radius from the import graph (direct and transitive importers of the changed files) and per-file risk signals from git history, reads the repo's CLAUDE.md files (root + each touched module/service) as the routing source of truth, recalls prior knowledge, and emits an impact map. Use whenever the user asks what a change, commit or diff could affect or break, which files depend on the ones changed, what to check before opening a PR, where new logic belongs, or whether a change spans modules/services — and as the first step of any non-trivial feature or bug, before exploring or designing. Not for a trivial one-line edit (a typo, a comment, a config value) — just make it.
---

# Route & Map

Before exploring code or designing anything, answer: **where does this change belong, and
what does it touch?** The cost of getting this wrong is high — new logic in the wrong place,
a forked write path, a forgotten follow-up obligation. This step is cheap insurance, and in a
small single-module repo it collapses to a few lines.

**Standalone asks** — "what could the change at HEAD affect?", "which files depend on this?",
"what should I check before I open the PR?": the impact map *is* the answer. Run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" blast --diff <base> --json` (`HEAD~1` for
the commit at HEAD; `blast <paths>` for named files) and report its `by_dir` grouping — the
`files` list is the full transitive set, so mark the direct importers by grepping for imports
of the changed files, and name any `unknown_seeds` as unmapped. The answer is the affected
set and nothing else: do not name files you ruled out, and add routing notes (CLAUDE.md rules,
cross-cutting risks) only when the user asked for them. Do not branch or explore afterwards
unless asked, and record nothing — a blast-radius answer starts no flow. The routing ask for
*new* work — "where does this go and what does it touch?" — is the opposite case: it is the
first phase of a flow, and step 5 records it.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

> **Journaled project — name the stream before you start.** A session brief headed "shipgate
> flow journal", a **Journal** section in the config or a `.claude/shipgate.json` sidecar means
> this map is owed to a stream, and the stream is the branch the work will take: the checked-out
> branch when it is a work branch, otherwise the name the config's **Branching** pattern gives
> it (`feat/<issue-id>-<slug>`; `feat/<slug>` with no issue — `workspace` reuses the name when
> it creates the branch). The integration branch (`main`, `master`, `develop`) is never a
> stream. No stream of that name in the brief? Open it with `flow-started {request, branch}` in
> the same append as the map's `phase-entered` — routing on `main` before any branch exists is
> the normal case, not a reason to skip. The event owed here is `phase-entered {phase:
> route-and-map}`, appended as the map is emitted (step 5), in that turn, not after the user
> confirms it. The Stop hook does not check it, so step 5 is the only thing that writes it.

The rules that decide routing are **not** hardcoded here — they live in the repo's
`CLAUDE.md` files and drift over time. Your job is to *consult* them, not memorize them.

## Steps

1. **Read the routing rules from CLAUDE.md.** Read the root `CLAUDE.md` (it should already be
   in context) AND the `CLAUDE.md` of every module/service you suspect the change touches.
   Don't skip the nested ones because the change "looks small" — each carries conventions the
   top-level file doesn't repeat. These files are the source of truth; if they and your
   assumption disagree, the file wins.

2. **Recall prior knowledge** (`knowledge-base`): pull domain/product context and prior
   decisions from the configured knowledge base — default: the repo's `docs/adr/` and
   CLAUDE.md files. Cite hits as "[kb] …" or "[repo] …" so it's clear what's recalled, not
   re-derived.

3. **Pull the risk signals** for the paths you expect to touch, once per touched repo (in an
   umbrella checkout, one call per repo with `--repo`):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/signals.py" hotspots --repo <repo> <paths> --by-dir 2 --blast --json
   ```

   Per touched module, keep its labels (churn from `commits`, fix-rate, fan-in) and `risk`,
   plus the `blast.size` of the touched set — labels are relative to this repo, so `top` means
   top *here*. Signals inform routing; they never override a routing rule a CLAUDE.md states.
   Unavailable at the top level (`no-git`, `shallow`, `empty-history`; `no-adapter` only
   when neither half could be computed) → the map carries the one-line note below instead of
   the block. A structure-only or trajectory-only result shows in `trajectory.reason` /
   `structure.reason` (`no-adapter` usually arrives there) → keep whichever half is
   available. No error, nothing to install.

4. **Classify the change** using the rules `CLAUDE.md` actually defines — these are typical
   multi-service patterns to look for, not universal rules, and not rules to import from
   elsewhere:
   - New business logic / new endpoints → the module/service CLAUDE.md designates for it
     (often a designated new backend).
   - Read paths → can often move without touching a legacy backend.
   - Write paths → frequently still touch legacy code (models, events, sockets); plan the
     cut-over, don't fork state.
   - Schema changes → whichever service owns migrations (the migration source of truth);
     then any downstream refresh the repo declares (e.g. regenerating dependent schema dumps).
   - Feature flags → if the project uses flags, add the flag to each reading service's registry.
   - Frontend → the frontend app, in the right bounded context.

5. **Emit the impact map — and, journaled, append its `phase-entered` in the same turn** (the
   form is under **Record the map**; the append is part of emitting the map, not a follow-up
   once the user has confirmed it). Produce this and confirm it with the user before exploring
   (drop sections that don't apply):

```
## Impact map: <feature/bug>

### Primary home
<module/service> — because <rule from CLAUDE.md, quoted/paraphrased>

### Modules/services touched
- <module> — read | write | schema | UI — what changes

### Write path → read path
<where state is written, where it's read>

### Schema / data
- Migration needed? <yes/no — where>
- Dump refresh needed afterward? <which services — n/a if the repo has no such obligation>

### Feature flag (only if the project uses flags)
- Flag id: <per the repo's naming convention>
- Enum(s)/registry to add it to: <service → file, per CLAUDE.md — n/a if the repo has no flag system>

### Risk signals
- <module> — churn <label> · fix-rate <label> · fan-in <label> → risk <label>
- Blast radius of the touched set: <size> files (<top importing dirs>)
  (unavailable → replace this block with one line: `Risk signals: unavailable (<reason>)`)

### Cross-cutting risks
- <forked write paths, event coupling, anything to cut over deliberately>

### Open routing questions
- <anything the CLAUDE.md files don't resolve — escalate, don't guess>
```

## Record the map (journaled projects)

Step 5's append: the phase entry, carrying the map's essentials in `data` — enough for a later
session to route from:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append \
  --stream <branch> --type phase-entered \
  --data '{"phase":"route-and-map","primary_home":"api",
           "touched":["api","web"],"schema":false,"flag":"export-filters",
           "signals":{"modules":{"api":{"churn":"top","fix":"high","fan_in":"mid"}},"blast":37},
           "skipped":["workspace"]}'
```

`skipped` names the phases this stream never entered: `append` refuses a forward jump over a
phase it was not told about, and a stream that `workspace` did not open — the standalone routing
ask, a branch made by hand, a stream opened here — has skipped exactly that one. Keep it unless
the brief shows the stream already at `workspace` (a superfluous entry is tolerated; a missing
one is a refusal). When the stream does not exist yet, opening it and recording the map is one
`--batch` (JSONL on stdin — stdin form: see `verify`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal.py" append --stream feat/<slug> --batch <<'EOF'
{"type":"flow-started","data":{"request":"<the ask, one line>","branch":"feat/<slug>"}}
{"type":"phase-entered","data":{"phase":"route-and-map","primary_home":"<module>","touched":["<module>"],"skipped":["workspace"]}}
EOF
```

`signals` carries labels and sizes only, never the table — or `{"unavailable":"shallow"}` when
the signals could not be computed — so the entry stays well under the 1 KB cap.

Essentials only — the map itself stays in the conversation and in the artifacts that follow it;
the journal points at position, it doesn't copy documents. A missing or unreadable database is an
infrastructure failure, not a reason to skip the append: surface it loudly and continue in legacy
mode only with the user's acknowledgement.

## Guardrails

- **Don't guess routing.** If the CLAUDE.md files genuinely don't resolve where something
  belongs, surface it as an open question for the user rather than picking silently — the
  whole point of this step is to not get this wrong.
- **Name the split for cross-cutting features.** When a change spans modules/services
  (cross-cutting changes often do), state the split explicitly in the impact map instead of
  quietly choosing one home.
- **This step is read-and-plan only.** No code changes here. Hand the impact map to
  exploration and design.
