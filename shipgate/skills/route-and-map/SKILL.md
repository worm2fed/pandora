---
name: route-and-map
description: First step of any feature or bug — decide WHERE the change belongs and map its blast radius before exploring or designing. Reads the repo's CLAUDE.md files (root + each touched module/service) as the routing source of truth, recalls prior knowledge, and emits an impact map. Use at the start of feature work, when unsure which module to edit, or when a change may span modules/services.
---

# Route & Map

Before exploring code or designing anything, answer: **where does this change belong, and
what does it touch?** The cost of getting this wrong is high — new logic in the wrong place,
a forked write path, a forgotten follow-up obligation. This step is cheap insurance, and in a
small single-module repo it collapses to a few lines.

> **Project config:** `.claude/shipgate.md` (project root — and umbrella root in an umbrella
> checkout) overrides the defaults below; read it first if present.

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

3. **Classify the change** using the rules `CLAUDE.md` actually defines — these are typical
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

4. **Emit the impact map.** Produce this and confirm it with the user before exploring
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

### Cross-cutting risks
- <forked write paths, event coupling, anything to cut over deliberately>

### Open routing questions
- <anything the CLAUDE.md files don't resolve — escalate, don't guess>
```

## Guardrails

- **Don't guess routing.** If the CLAUDE.md files genuinely don't resolve where something
  belongs, surface it as an open question for the user rather than picking silently — the
  whole point of this step is to not get this wrong.
- **Name the split for cross-cutting features.** When a change spans modules/services
  (cross-cutting changes often do), state the split explicitly in the impact map instead of
  quietly choosing one home.
- **This step is read-and-plan only.** No code changes here. Hand the impact map to
  exploration and design.
