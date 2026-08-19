---
name: astrolabe
description: >-
  Typed functional code style — use BEFORE writing, refactoring, or reviewing
  code in a typed-FP codebase: new domain types, value objects, entities, error
  unions, commands/queries, endpoints, mappers, pure modules, and their tests.
  Also use when asked "how would we write this" or to judge whether code follows
  functional/DDD discipline. Types first — examples are TypeScript (fp-ts,
  ts-pattern, newtype-ts, fast-check), but the principles are
  language-portable. Projects layer their own specifics on top via a local
  style skill.
---

# Astrolabe — typed functional code style

The style in one sentence: **design the types first, make illegal states
unrepresentable, keep functions pure with side effects pushed to the top of the
stack, and treat absence and failure as typed values — never as exceptions,
sentinels, or comments.**

This skill is the general canon. A project may carry its own style skill with
local conventions (framework rules, house helpers, legacy-tree exceptions) that
*layer on top of* — and, where they explicitly say so, override — these rules.
When both exist, read this one first, then the project's.

## How to use this skill

1. Identify the kind of code you're about to write and read the matching
   reference(s) from the routing table.
2. For trivial mechanical edits (typo, rename, one-line fix), the
   non-negotiables below are enough — skip the reference read.
3. If the project has its own style skill, read it after this one; local rules
   win where they conflict (a legacy tree's conventions are a deliberate
   exception, not a violation).

## Routing table

| You are writing…                                                                    | Read                                       |
| ------------------------------------------------------------------------------------ | ------------------------------------------ |
| New types: entities, value objects, branded ids, error unions, enums-vs-unions      | `references/domain-modeling.md`            |
| FP plumbing: pipelines, Option/Either/RTE, ts-pattern, immutability, aggregation, when/how to abstract | `references/fp-functional.md`   |
| Backend structure (layers, use cases, validation, mappers, DTOs, errors, DI) or tests | `references/architecture-and-testing.md` |

Multiple match → read all that match. A new command usually needs
architecture + fp-functional; a new value object needs domain-modeling; its
test needs the testing half of architecture-and-testing.

## Non-negotiables (always apply, no reference read needed)

1. **No `as` casts** (including `as unknown as`), no `any`, no non-null `!`.
   Brand, narrow, or guard instead. Casts are allowed ONLY at declared type
   boundaries (where raw external data enters a typed model), one per boundary,
   each with a cause-naming comment — never mid-pipeline.
2. **Absence is a typed value** — `Option` in fp-ts code, a required `| null`
   field at the edge. Never an empty-string/empty-array sentinel for
   "not there".
3. **Expected failure is a typed value** (`Either`, a tagged error union) —
   never `throw` for business errors in domain/application code. Small helpers
   may throw on unmet *preconditions* — callers guard; a helper never silently
   returns `null`/empty when a required input is missing.
4. **Closed unions dispatch via `match().exhaustive()`** (ts-pattern) — never
   `switch`, never `.otherwise()` as a catch-all. `.otherwise()` only in
   permissive parsers returning `Option`.
5. **`readonly` everywhere; immutable updates by spread**; no let-then-mutate,
   no mutating accumulator in `reduce`; aggregate with a Monoid fold.
6. **Name by intent, not implementation.** No `Command`/`Query`/`Dto` suffix on
   functions (types only); booleans start `is`/`has`/`are`; no `I`- or
   `T`-prefix on interfaces/types (even beside legacy declarations that carry
   them — new declarations drop the prefix); string-literal unions over TS
   `enum` for closed string sets. **Structures are declared as `interface`,
   not `type`** — reserve `type` for unions, intersections, and derived/mapped
   shapes that `interface` can't express.
7. **Every new code path gets a test in the same commit**, named `*.test.ts`,
   colocated next to the subject. New tests follow the current convention even
   beside legacy `.spec.ts`/`.js` neighbors — naming/extension rules beat
   rule #8's match-the-neighbor.
8. **Don't introduce a second pattern where one exists** — extend the shape
   already in the file. (Does not override #7's naming rule or explicit
   new-code conventions.)
9. **Explicit type annotations on exported point-free functions**
   (`export const fn: (a: A) => B = flow(...)`) so the contract reads without
   the implementation.
10. **Doc comments on functions/types/consts are JSDoc (`/** … */`), never `//`
    line comments** — they attach to the symbol and surface in editor hover.
    `//` is for inline constraint notes inside a body, not for documenting a
    declaration.
