---
type: adr
title: "0006. The HUD's type model follows astrolabe, adapted to a mod"
created: 2026-10-20
updated: 2026-10-20
tags:
  - adr
  - shipgate-hud
status: accepted
date: 2026-10-20
issue: none / ad-hoc
related:
  - "../research/2026-10-20-hud-type-model-audit.md"
  - "../../../astrolabe/skills/astrolabe/SKILL.md"
---

# 0006. The HUD's type model follows astrolabe, adapted to a mod

> New and changed HUD code is types-first under astrolabe's rules, with fixed local
> substitutes for the libraries a mod cannot import.

## Context

An audit found that the HUD was built behaviour-first. No type describes journal.py's
JSON, absence is spelled `''`, `'?'` or `0`, and several unions collapse to `string`. Five
of the resulting gaps let the publish gate pass commands it should hold. astrolabe is this
marketplace's typed-functional canon. But a mod imports only `claude-code`, so fp-ts,
ts-pattern, newtype-ts and fast-check are not available. `$.state` must hold JSON.

## Decision

| astrolabe | in the HUD |
|---|---|
| `Option` | a required `T \| null`; never `?:` |
| `Either` | `Result<E, A>` in `json.ts` |
| `match().exhaustive()` | a total `Readonly<Record<Union, X>>` table first; else `switch` with `default: return absurd(x)` |
| newtype | `Brand<T, 'Name'>` with a string key, declared in `types/index.d.ts` (the contract may hold no value, so `claude plugin validate` refuses a `unique symbol`); one smart constructor per brand, holding the one commented cast |
| fast-check | `tests/arbitrary.ts`: a seeded generator and `forAll` |
| casts | only at declared boundaries: process stdout, `$.state` reads, `ui.resolve`, test-kit events |
| `try`/`catch` | only in `json.ts`'s `parseJson` (`JSON.parse` throws), which returns a `Result`, and in `register.tsx`'s run and rejection helpers |
| structures | `interface`, except `$.state` shapes, which stay `type` because the engine's `JsonValue` needs an index signature |
| stored values | tagged unions, read through one decoder, versioned with the atom's `shape` tag |

Changes land types-first. A declarations task comes before its bodies, and the
declarations are reviewed on their own.

## Alternatives considered

- **Bundle fp-ts and ts-pattern into the mod.** The mods runtime loads one module with no
  package resolution. Vendoring the libraries would add weight and a second style to keep.
- **Keep the behaviour-first style.** The audit's fail-open defects came from exactly that.

## Consequences

- Hand-rolled `Result`, `parseJson` and `absurd` live in `json.ts`, and `Brand` lives in the
  contract, so there is one copy of each.
- Exhaustiveness relies on total tables and `absurd`, which TypeScript checks.
- Existing stored values are dropped on upgrade by a shape-tag bump. They are re-derived on
  the next refresh.
