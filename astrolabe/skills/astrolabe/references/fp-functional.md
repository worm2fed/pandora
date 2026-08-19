# fp-ts & functional TypeScript style

## Essence

Write control flow as `pipe`/`flow` chains over `Either`/`Option`/`ReadonlyArray`, almost
never `if`/`for`, and *never* `try/catch` in domain code. Absence is `Option`, synchronous
failure is `Either`, effects are `ReaderTaskEither`; a raw `number`/`string`/`null` only
survives at the very edge of the system. Everything is `readonly`, aggregation is a monoid
fold rather than a mutating `reduce`, and closed unions are dispatched with `ts-pattern`'s
`match().exhaustive()` so a new variant fails to compile until handled. Point-free is the
default when a function adds no logic of its own, but currying is applied only where
partial application is actually used downstream — uncurry a value object once call sites
show the extra currying isn't earning its keep.

**Scope: anywhere fp-ts is a dependency — not just the modern trees.** A new pure `.ts`
module sitting beside legacy code still uses `E.Either<Error, T>` for failure-as-value;
never hand-roll a `Result`/`ok:` discriminated union because "fp-ts isn't used in this
tree yet". Full chains (`pipe`/`fold`) are optional at a legacy boundary; the *type* is
not.

## Imports & module hygiene

**Namespace-import every fp-ts module under its canonical single-letter (or short)
alias.** `Either` → `E`, `Option` → `O`, `ReadonlyArray` → `RA`, `Array` → `A`,
`NonEmptyArray` → `NEA`, `Record`, `ReadonlyMap` → `RM`, `boolean` → `B`, plus
`Eq`/`Ord`/`Monoid`. Never default-import individual combinators into the module scope.

```ts
import * as A from "fp-ts/Array";
import * as NEA from "fp-ts/NonEmptyArray";
import * as O from "fp-ts/Option";
import * as RTE from "fp-ts/ReaderTaskEither";
import { sequenceS } from "fp-ts/Apply";
import { constVoid, pipe } from "fp-ts/function";
```

**Import from the canonical module path (`fp-ts/function`), never `fp-ts/lib/*`.** The
`fp-ts/lib/*` paths are internal and deprecated; treat any survivor as debt, not a pattern
to copy.

**Use `flatMap`, never the deprecated `chain`.** All new sequencing goes through
`E.flatMap`/`O.flatMap`/`RTE.flatMap`.

**Use `constVoid` over `() => undefined` and `constant(x)` over `() => x`.** Both come
from `fp-ts/function`; reach for them in `O.match`/`E.match` default branches and
`RTE.map(constVoid)` tails.

```ts
.with({ scope: "line" }, O.some).with({ scope: "order" }, constant(O.none)).exhaustive(),
```

## Composition & point-free

**Compose with `pipe` (data first) and `flow` (point-free); prefer `flow` over an arrow
wrapping `pipe`.** When a value threads straight through a sequence of transforms, use
`flow` and give the binding an explicit standalone type annotation rather than inferring
from the body.

```ts
export const createMoney: (n: Decimal | number) => Money = flow(
  coerceToDecimal,
  isoMoney.wrap,
);
export const unwrapMoney: (money: Money) => Decimal = isoMoney.unwrap;
export const getMoney: (money: Money) => number = flow(unwrapMoney, m =>
  m.toNumber(),
);
```

**Pass functions point-free to combinators — don't wrap them in a redundant lambda.**
`A.traverse(RTE.ApplicativeSeq)(createAuditLog)` not `...(x => createAuditLog(x))`;
`.map(getMinutes)` not `.map(m => getMinutes(m))`.

**Curry data-last (config first, subject last) — but only when partial application is
actually used.** Data-last currying is what makes a function droppable into a `pipe`;
apply it to constructors and pipeline transformers that get partially applied downstream.

**Don't over-curry.** Value-object constructors that are never partially applied are
plain uncurried functions (`addMoney(a, b)`, `deductFactor(a, b)`) — deliberately remove
currying where call sites don't use it.

**In a plain uncurried helper, the context/subject argument leads and the data follows.**
Same principle as data-last currying, seen from the other side — the parameter that names
what's being resolved reads first, so the call reads as a sentence instead of a positional
guessing game.

**Smart constructors for value objects are positional with fully explicit arguments — no
params objects, no optional-with-default parameters in production code.** Hidden defaults
are a correctness hazard in calculation code: a constructor that compiles with a silent
domain default means a mapper that forgets to thread a stored column still typechecks —
and computes wrong. Explicit positional args turn the omission into a compile error.
Domain/product defaults belong in persistence (DB column defaults) and product config, not
in the type layer — a constructor default is a second source of truth that drifts.

Where absence is real, make the parameter an explicit `Option` the caller must pass
(callers write `O.none`); where a degenerate case is common, add a named convenience
constructor instead of an optional param — the name documents intent better than an
omitted field.

```ts
// bad — params object, optional fields, silent domain defaults
createSettlement({ distribution?: DistributionMethod; allocation?: AllocationPolicy } = {})
createRateBook({ default: config })            // byGroup silently defaults to empty

// good — positional, explicit; named helper for the degenerate case
createSettlement(distribution, allocation)     // both required — defaults live in persistence
createRateBook(defaultConfig, byGroup)
singleRateBook(config)                         // named convenience over optional param
```

Exception: test factories may take optional/defaulted params for ergonomics, as long as
they call the explicit production constructors underneath.

**When applying a curried function to a value produced by another call, compose with
`pipe` — don't nest the applications.** Nesting reads inside-out; `pipe` reads
left-to-right as the value flows through the pipeline, which is the whole reason pipeline
transformers are curried data-last in the first place.

```ts
// bad — nested application, reads inside-out
config: resolveGroupConfig(order.rateBook)(primaryVendorId(lines)),

// good — pipe, reads left-to-right
config: pipe(lines, primaryVendorId, resolveGroupConfig(order.rateBook)),
```

This applies to test code equally — nested curried applications sneak into test files on
days the production code is already clean. One nesting level with a single argument
(`getId(vendorId)`) is fine when there's no pipeline to join — the rule bites once two or
more transformations chain, or a curried application wraps another call.

**Watch out:** `pipe` infers left-to-right, so it loses back-propagated type context for a
generic constructor. `createId(x)` infers the specific `VendorId` when applied directly in
nested position, but degrades to the generic `Id<symbol>` once it's a pipe stage —
producing a `TS2345` at the *next* step, not at `createId` itself. Fix with a tiny typed
anchor before the value enters the pipe:

```ts
const vendorId = (id: number): VendorId => createId(id);
pipe(vendorId(v), O.some, resolveGroupConfig(order.rateBook));
```

## Abstraction — extract the skeleton, keep the holes

Abstract where it helps, in the functional spirit: the unit of reuse is a **higher-order
function generic over the part that varies**, never a class hierarchy, an inheritance tree,
or a config-object mega-function. A good abstraction makes call sites *more* declarative —
they shrink to exactly the part that differs.

**Before writing plumbing, climb the reuse ladder.** The extraction rules below are the
*repair* path; the cheaper move is not writing the duplicate in the first place. Before
hand-rolling any integration plumbing (timing, retries, batching, settle-on-both-branches,
cleanup), check in order:

1. **The dependency's own API.** A library usually ships the combinator for its own
   domain — a metrics client's `startTimer()` stop-closure replaces hand-rolled
   high-resolution-time arithmetic plus a manual `observe()`; an HTTP client's interceptor
   lifecycle replaces hand-wired handlers. Read the dependency's types before writing
   arithmetic around it: **if your code computes what the library already measures, you
   are re-implementing your dependency.**
2. **Siblings in the same module.** An adjacent function integrating the same dependency
   is the template — match its approach (or improve both), never diverge silently. A new
   function that hand-rolls what its neighbor gets from the library is non-negotiable #8's
   "second pattern" in miniature, inside one file.
3. **The codebase's shared helpers** — grep before writing.
4. Only then write it new — and the moment a second copy appears, extract per the rules
   below.

**When to extract — the duplication is structural.** Two call sites hand-rolling the same
*skeleton* — the same control flow, plumbing, guards, and error handling — differing only
in a hole, already qualify when the plumbing is subtle. The canonical shape: two HTTP
interceptors each hand-rolled per-call start state in a `WeakMap` keyed by the request
config, a response handler settling on both branches, the error-type guard, and the
untouched rethrow — and both re-explained the config-identity trick in a prose comment.
Extract that skeleton into one function generic over the threaded start state
(`attachObserver<StartState>(onStart, onSettle)`); the two call sites now express only
what differs (a timer vs. a structured log line).

Signals the extraction is due:

- **The same explanatory comment appears at two sites.** If you explain the same trick
  twice in prose, the code should encode it once, in a named function whose doc comment is
  the single home of that explanation.
- **The diff of the two sites is smaller than either site.** The shared part dominates;
  the holes are small and nameable.
- **The plumbing carries a correctness subtlety** (identity-keyed state, both-branches
  settling, error rethrow discipline) — subtle plumbing duplicated is subtle plumbing that
  will drift.

**How to extract:**

- Parameterize with a **type variable over the threaded state** and function-valued holes —
  the abstraction owns the skeleton, callers own the holes. Give the exported HOF an
  explicit type annotation (non-negotiable #9).
- The abstraction gets its **own module, named for what it does**, with its **own colocated
  test** — the extraction must be behavior-preserving, and the test proves the skeleton's
  subtleties (both branches settle, errors rethrow untouched, identity holds) once, for
  every caller.
- Type-class instances **are** this pattern at the type level: `Eq`/`Ord`/`Monoid` capture
  an algebra once so `sort`/`uniq`/`fold` never re-implement comparison or aggregation
  (see Immutability & aggregation below).

**When NOT to abstract:**

- **One call site.** A hypothetical second caller is not a caller. Wait for the real one —
  premature abstraction guesses the axis of variation and usually guesses wrong.
- **Accidentally-similar code.** Two sites that look alike today but change for different
  reasons should stay separate — duplication is cheaper than the wrong abstraction, and
  un-inlining a bad one costs more than re-extracting a good one later.
- **The helper's name would be vaguer than the code it wraps** (`processData`, `handleX`).
  If you can't name the skeleton crisply, you haven't found a real one.
- **The abstraction needs flags/modes to serve its callers** — a boolean or mode parameter
  switching behavior inside means you've unified two skeletons, not extracted one. Split
  it, or accept the duplication.

## Absence: Option end-to-end, null only at the unwrap boundary

**Model absence with `Option` in every domain/application signature, schema, and DTO —
`null`/`undefined` live only at boundaries (DB rows, external clients, the presentation
layer).** Keep model and application layers `Option`/`Either`; convert to primitives
(prefer `null`) only in the presentation layer / non-fp-ts consumers.

**Never unwrap an `Option` just to revert to `null`/`undefined` mid-pipeline** — keep it
an `Option` and `O.toNullable` in one dedicated unwrap layer at the edge. The whole job of
an `unwrap.ts` module is `Option<T>` → `T | null` for consumers that can't speak fp-ts:

```ts
export const toBreakdownUnwrapped = (
  breakdown: Breakdown,
): BreakdownUnwrapped => ({
  exceededAt: O.toNullable(breakdown.exceededAt),
  allowedTime: pipe(breakdown.allowedTime, O.map(getMinutes), O.toNullable),
  contextTime: pipe(
    breakdown.contextTime,
    O.map(Record.map(getMinutes)),
    O.toNullable,
  ),
});
```

**Return `Option` (or `null` at the edge) for absence — never an empty-string /
empty-array sentinel.** A `''` or `[]` standing in for "not there" hides the difference
between absent and empty.

**Filter nullish with `.filter(Boolean)` or a shared `filterMap(O.fromNullable)`, not a
hand-written `x != null` predicate.**

## Failure: Either sync, TaskEither/RTE for effects — no try/catch

**Represent expected failures as values (`Either` / a typed result), never thrown
exceptions.** Domain code contains no `try/catch`. Smart constructors for constrained
types return `Either<InvalidX, X>` (see the `createFactor` example in
`domain-modeling.md`).

**When you must lift a throwing/promise-based call into fp-ts, use `E.tryCatch` (sync) or
the codebase's single named effect-boundary helper — never a bespoke manual `try/catch` at
a call site.** Every codebase should have exactly one helper that folds
promise-lifting + error classification + logging into one call, so no call site ever
writes its own try/catch. The one `try/catch`-shaped thing that is fine is a `ts-pattern`
match that *classifies the shape* of an already-caught error, not catches it:

```ts
export const externalError = (error: unknown): ExternalError =>
  pipe(
    match(error)
      .with({ code: P.string, message: P.optional(P.string) }, err => ({
        /* ... */
      }))
      .with(P.instanceOf(Error), error => ({
        message: error.message,
        code: O.none,
      }))
      .otherwise(() => ({ message: JSON.stringify(error), code: O.none })),
    createError("ExternalError"),
  );
```

**Effects stay `Task`/`TaskEither`/`RTE` — don't unwrap to a `Promise` and re-wrap.**
Convert a non-failing `Task` to `TaskEither` and handle errors functionally; avoid a
mutable `let` while doing so.

## Structuring effectful pipelines (RTE)

**Use `RTE.Do`/`E.Do` + `bind`/`apS` when steps need named intermediate results.**
Compound value objects compose their narrower validators this way:

```ts
pipe(
  E.Do,
  E.apS("premiumTier", validatePremiumTier(tier)),
  E.map(({ premiumTier }) => ({ type: "premium" /* ... */ })),
);
```

**Use `sequenceS(RTE.ApplyPar)` for independent parallel fetches, and
`A.traverse(RTE.ApplicativeSeq)` when side effects must run in order:**

```ts
sequenceS(RTE.ApplyPar)({
  previousAssignees: repository.fetchAssignees(command.ids, command.tenantId),
  assigneeName: pipe(userRepository.fetchUser(command.assigneeId), RTE.map(O.map(fullName))),
}),
// ...
A.traverse(RTE.ApplicativeSeq)(({ id, assignee }) => createAuditLog({ /* ... */ })),
```

For a pure `Either` pipeline the same idea is `RA.traverse(E.Applicative)`.

## Branching: B.match / O.match / E.match / ts-pattern

**Use `B.match`/`O.match`/`E.match` instead of `if`/`else` for anything domain-meaningful;
small obviously-safe ternaries are fine.** Branch on a boolean with `B.match`, not an
`if`:

```ts
pipe(
  isPoolable,
  B.match(
    () => foldMapBreakdown(breakdowns, identity),
    () => {
      /* poolable: share allowed time across standalone items */
    },
  ),
);
```

**Dispatch closed unions with `ts-pattern` `match().exhaustive()` — never `switch`, never
`.otherwise()` as a lazy catch-all.** `.exhaustive()` turns a new union member into a
compile error until it's handled; a stray `.otherwise()` silently swallows it. No `switch`
statement, anywhere.

**`.otherwise()` is reserved for permissive parsers that return `Option`, where "not one
of these" is a legitimate `None`.** This is the one sanctioned use — a best-effort parse
of arbitrary input, not a domain dispatch. The strict sibling `validate*` returns `Either`
instead — the paired `create*` (Option, permissive) vs `validate*` (Either, strict)
constructors from `domain-modeling.md`.

**Use `ts-pattern`'s `P` combinators for structural/type guards on `unknown`** —
`P.string`, `P.optional(...)`, `P.instanceOf(Error)` — rather than hand-written `typeof`
chains. Spread a `const [...] as const` list straight into `.with(...arr, cb)` to match
"one of these known literals" without repeating each. Prefer `.returnType<T>()` on a match
over casting each branch's return.

## Immutability & aggregation

**Mark every interface/type field and array type `readonly`.** `readonly OrderLine[]`,
`readonly Money[]`. Use `as const satisfies readonly T[]` for readonly literal arrays.

**Aggregate with a `Monoid`/`Semigroup` + `RA.foldMap` / `Monoid.concatAll`, not a
`reduce` that mutates an accumulator.** Define the algebra once, fold with it everywhere:

```ts
export const moneySemigroup: Semigroup<Money> = { concat: addMoney };
export const moneyMonoid: Monoid.Monoid<Money> = {
  ...moneySemigroup,
  empty: createMoney(0),
};
export const sumMoney: (money: readonly Money[]) => Money =
  Monoid.concatAll(moneyMonoid);
```

When a plain `reduce` is genuinely needed, keep it pure (build a new value) — never a
mutative `forEach` into an external accumulator.

This generalizes past `reduce`: don't declare a `Map`/array up front and mutate it inside
a `forEach` — build the whole structure in one declarative expression instead
(`Array.from`/`.map` into a `Map`/array constructor; `reduce` only where a seed is
genuinely needed).

```ts
// bad — declared, then mutated
const byGroup = new Map<GroupId, Config>();
groups.forEach(([id, rows]) => byGroup.set(id, toConfig(rows)));

// good — built in one expression
const byGroup = new Map(
  Array.from(groups, ([id, rows]) => [id, toConfig(rows)] as const),
);
```

**Update objects by spread, never in-place mutation.** `{ ...ctx, lines }`,
`{ ...item.breakdown, distributionGroup }`.

**Sort/dedup/group through fp-ts combinators with an explicit `Eq`/`Ord` — never bare
`Array.prototype.sort` or reference equality.** `RA.sort(ord)` / `NEA.sortBy`,
`RA.uniq(eq)`, `NEA.groupBy`, with the instance passed in so equality/ordering semantics
are chosen deliberately (`Eq.contramap(unwrapMoney)(decimalEq)`,
`Ord.contramap(...)`).

**Imperative loops and `let` are allowed only as isolated, commented exceptions for
genuinely stateful algorithms.** A surviving manual sweep carries a comment marking it a
deliberate exception — it is not a habit. Everywhere else, avoid mutable `let`.

## Quick reference

- Namespaces: `E O RA A NEA RM B Eq Ord Monoid`; `pipe`/`flow`/`constVoid`/`constant`/`identity` from `fp-ts/function`.
- Absence → `Option`; sync failure → `Either`; effect → `TaskEither`/`ReaderTaskEither`. `null` only at the edge, via `O.toNullable` in a dedicated unwrap layer.
- `flatMap` not `chain`; `fp-ts/function` not `fp-ts/lib/function`; point-free, no redundant lambdas.
- Closed union → `match().exhaustive()`; permissive parse → `match().otherwise()` returning `Option`. No `switch`, no `if/else` for domain branches.
- `readonly` everywhere; aggregate via `Monoid` + `RA.foldMap`; spread updates; explicit `Eq`/`Ord` for sort/uniq/group.
- Curry data-last only where partial application is used; otherwise plain uncurried functions.
- Abstract by extracting the shared *skeleton* into a HOF generic over the hole — two hand-rolled copies of subtle plumbing qualify; one call site, accidental similarity, or a mode flag inside disqualify.
- Before writing plumbing, climb the reuse ladder: the dependency's own API → siblings in the same module → shared helpers → only then new code. Never re-implement what your library already ships.
