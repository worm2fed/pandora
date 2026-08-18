# astrolabe

A code-style skill for typed functional codebases: **types first, immutability, smart
constructors, illegal states unrepresentable, pure functions with side effects at the top
of the stack, DDD-shaped boundaries.** Like the instrument it's named after, it's the
fixed reference you navigate code by.

Examples are TypeScript (fp-ts, ts-pattern, newtype-ts, fast-check); the principles are
language-portable.

## What's inside

One skill (`/astrolabe`) with a short always-on core (the non-negotiables) and three
references, loaded by what you're writing:

| Reference | Covers |
|---|---|
| `domain-modeling.md` | Types before behavior, branded newtypes, the uniform value-object template, smart-constructor split (validate/Either vs create/Option), discriminated unions & error modeling, entity lifecycle in types, naming, type ownership across contexts, curated barrels |
| `fp-functional.md` | pipe/flow composition, currying discipline, Option end-to-end with one unwrap boundary, Either/TaskEither/RTE (no try/catch), ts-pattern branching, immutability & Monoid aggregation |
| `architecture-and-testing.md` | The DDD onion with effects at the edges, validation at exactly two boundaries, repositories/mappers/DTOs, error unions → transport, DI through the environment; and the testing canon — fixture factories, property-based law tests, assertion strategy, mock-the-boundary |

## Install

```
/plugin install astrolabe@pandora
```

## Layering project specifics on top

astrolabe is the general canon. A project keeps its own local style skill for what's
genuinely local — framework rules, house helper names, legacy-tree exceptions, CI quirks —
and that skill's first instruction is "invoke `astrolabe` first". Local rules win where
they explicitly conflict (a legacy tree's conventions are a deliberate exception, not a
violation).

With the [shipgate](../shipgate) plugin, declare both in the project config's **Style**
section so every phase (and every worker brief) picks them up:

```markdown
## Style
- Style skill(s): invoke `astrolabe` (general canon), then `<project skill>` (local
  specifics) before writing, refactoring, or reviewing code — and include that
  instruction in every worker brief.
```

## Status

v0.1.0 — initial extraction of the general, project-agnostic canon from a working
per-project style skill.
