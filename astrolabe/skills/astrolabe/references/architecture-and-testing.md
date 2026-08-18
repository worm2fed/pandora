# Architecture & testing

Two halves: how a codebase is layered so side effects stay at the top of the stack, and
how it is tested so every claim about behavior is backed by a test that proves it.

# Architecture — effects at the edges, domain pure

Write server logic as a strict DDD onion: `api → application → domain`, with
`infrastructure` reachable only from `application`/`api`, never `domain`. One use case per
file, each a plain function named for its intent. Validate at exactly two boundaries
(schema at the transport edge, smart constructors in the domain) and nowhere else. Errors
are a per-context discriminated union mapped to the transport by an exhaustive match — no
handler ever builds a status code. Everything is injected through the environment; nothing
is a module singleton.

## Layering & boundaries

**Imports point strictly inward: `api → application → domain`. `infrastructure` is
reached only from `application` or `api`, never from `domain`. Domain is pure — no I/O, no
`ReaderTaskEither`, no imports from legacy trees.** Enforce with a lint boundary rule; if
lint complains about an import, fix the direction — don't disable the rule.

**Never reach into another context's `application/`, `domain/`, or `infrastructure/`
directly. Cross-context imports go through the target context's `index.ts`.** If
`index.ts` doesn't expose what you need, that's a signal of bad boundaries or a missing
upstream API — widen the surface deliberately, don't lint-disable.

**When you must import from a not-yet-migrated legacy tree, scope a single
lint-disable at the exact import line — never disable the rule for the file.** Keeps the
debt visible and greppable.

**Don't create a new bounded context per page/feature, and don't pre-split into
sub-contexts.** Group within a context until it grows; add `services/`, `readModels/`
folders only when a concrete file lands.

## Use cases: one per file, named by intent

**Put each use case in its own file under `application/commands/*.ts` (state-changing) or
`application/queries/*.ts` (read-only), exporting a plain function named after the use
case (`mergeOrders`, `bulkAssign`, `listOrders`) — a single command/query object in, the
context's app type out.** The `Command`/`Query` suffix goes on the *type* only, never the
function. File name == primary export.

```ts
export interface MergeOrders {
  readonly sourceOrderId: Reference<Order>;
  readonly targetOrderId: Reference<Order>;
  readonly tenantId: TenantId;
  readonly userId: UserId;
  readonly note: Option<string>;
}

export const mergeOrders = (command: MergeOrders): OrderApp<void> =>
  pipe(RTE.Do /* ... */);
```

**Compose use cases with `pipe` + `RTE.Do`/`RTE.bind`/`RTE.flatMap`. No `async/await` or
raw `Promise` inside `application/` or `domain/`. Domain functions that can fail return a
sync `Either` — if you need I/O, the call belongs in `application`/`infrastructure`.**
Side effects live at the top of the stack; purity increases as you go inward.

## Validation at exactly two boundaries

**Validate/coerce the transport payload with a schema (e.g. zod) in `api/*.ts`, and
enforce business invariants with domain smart constructors returning `Either`. Nothing
between those two layers re-validates.** The use case receives already-typed input;
passing validated values inward is the whole point.

**Schema validation is a boundary-only tool. Never use it to validate already-typed
internal data.** Coerce branded ids at this boundary (a typed `idSchema<T>()`-style
helper) — never let a raw `string`/`number` travel where a branded id exists. Absence at
the boundary lands directly on `Option` (an `optionFromNullable`-style codec), not on
`null` carried inward.

**One handler per file under `api/`, built with the codebase's single handler-factory
(route, request-mapper, use case, success status).** Handlers translate; they never
contain business logic.

## Repositories & effect boundaries

**A repository module declares its functions as private top-level declarations, then
exports exactly one plain object `<thing>Repository` at the bottom of the file. Never a
class, never one function per export, never a default export.** Name read-only data access
`<thing>Query`; reserve `Repository` for write-capable access.

**Wrap every effect call site (queries, external clients) in the codebase's single named
effect-boundary helper** — it folds promise-lifting + error classification + logging into
one call, so no call site ever writes a bespoke try/catch.

**Build queries with the codebase's query builder, not raw SQL. Filter soft-deleted rows
in the query. When raw SQL is unavoidable, quarantine it in a named tagged constant with a
comment explaining *why* it's raw — never inline it into a chain.**

**Express feature-flag-gated query variants as a ternary on the injected flag client
producing a different query object — not as branching business logic.** Compute
flag-dependent values by passing the guard as a parameter, not by making every caller gate
it.

**Wrap multi-step writes in a transaction; persist through mappers, not inline field
assignment.**

### Persistence rules

- **Type a `NOT NULL` column as non-optional in schema interfaces**; required/audit
  columns cannot be null — NULL silently breaks `= false` filters and boolean coercion.
- **Declare boolean/flag columns `NOT NULL` with a default, using the schema builder's
  boolean type** — a bare integer flag returns a number and breaks strict boolean checks;
  a NULL flag is silently excluded by `flag = false` filters.
- **Helpers require non-nullable arguments and let callers guard** — a helper throws on
  unmet preconditions, never returns `null`/empty on missing required input.
- **Don't couple services through a shared DB schema** — read/write through the owning
  service's boundary.

## Mappers & DTOs

**Type every domain↔persistence conversion through a shared `Mapper` family** — single
row, joined result, one-to-many, read-only, write-only variants, each exposing
`toSchema`/`toDomain`. Pair each `<X>Schema` (row shape) with an `<x>Mapper`; domain code
never imports the schema type directly for business logic, only through the mapper. During
a migration, mark superseded shapes `/** @deprecated */` rather than deleting them.

**Model PATCH semantics explicitly:** `undefined` = don't touch the field, `null` = clear
it, `Some(v)` = set it — one shared `nullableFieldMapper`-style helper, not per-field
ad-hoc logic.

**Give each read-model DTO its own file, paired with a pure `to<X>Dto` function that only
reshapes/renames — no logic.** Keep a DTO local to the command/query that uses it; move it
to a shared `dtos/` only when actually reused. Never a generic `Dto`/`Enriched` prefix on
request inputs — name commands/queries by intent.

## Errors → transport

**Declare one discriminated union `<Context>Error` per context. Construct cases with
`createError('Tag')({ ...payload })` (data-carrying) or `constError('Tag')()` (tag-only).
Never `throw` for business errors.** Tags are PascalCase situation names
(`OrderNotFound`), not HTTP statuses.

**For compound errors, expose a `reason` sub-union on a single tag rather than one tag per
reason:**

```ts
interface OrderMergeNotAllowed extends BaseError<"OrderMergeNotAllowed"> {
  readonly reason:
    | "SourceNotExternal"
    | "TargetNotOpen"
    | "AlreadyMerged"
    | "TargetIsClosed";
}
```

**Map the error union to the transport error in a single `appErrorToApiError` that is
always `match(error)….exhaustive()` — never `.otherwise()` here.** Adding a union case
without a `.with()` is then a compile error. **Handlers never construct a status code** —
the failure flow is mechanical: domain/application returns `<Context>Error` → the mapper
produces the transport error → generic handler machinery emits the response.

## Context public surface & DI

**Expose a context only through its `index.ts`** — the error mapper, the handler map, the
router hook; nothing else leaks. Define the surface only when a real cross-context need
exists; don't speculatively expose internals.

**Flow everything through the environment (Reader-style `Dependencies`) — no module-level
singletons. Nothing logs outside DI:** even the logger is a factory injected via the
environment, not a top-level import. **Read feature flags through a typed client — one
`is<Flag>Enabled(): boolean` method per flag; callers never see a raw enum or string
key.** Prune a flag end-to-end once it ships — no dead dual paths.

## Presentation boundary

- **Business/domain logic lives in pure, framework-free modules; UI components assemble
  and render only.** Components call the pure module from derived state and render the
  result — never re-implement a calculation in a component.
- **Bridge legacy shapes to a new package with an anti-corruption layer** — one
  clearly-scoped pure function per file, a why-comment on every non-obvious mapping
  decision. **Mark a temporary bridge `TEMPORARY` with an explicit deletion condition** in
  the comment. Derive bridge types structurally from the runtime signature
  (`Parameters<typeof x.calculate>[0]`) rather than hand-duplicating an interface, so the
  mapper can't silently drift.
- **Isolate a legacy quirk in a single-purpose function with a why-comment**, not an
  inline workaround at the call site.
- **Send dates to a backend as ISO with timezone — never a custom-formatted string.**
  Display formatting is UI-only and owned by the shared date utility.
- **Collapse near-duplicate fetchers/helpers when you touch them** — parameterize one
  function rather than keeping two copies; move duplicated utilities to a shared module
  instead of redefining per consumer.

# Testing — every claim backed by a test

Tests ship in the same commit as the code. Every new code path gets a test; test bodies
stay declarative because unwrapping, comparison, and FP plumbing are pushed into named
helpers. Property-based tests prove the laws of pure functions; integration scenarios
(one file per business scenario) prove the whole pipeline; brittle unit tests of
intermediate stages are deliberately avoided.

## Coverage discipline

- **Every new code path gets a test** — new commands, new utilities, new behavior alike.
- **Tests land in the same commit as the code they cover, and each commit must compile
  and pass on its own.**
- **Question low-value tests that only assert mocked implementation details.** A test
  that re-asserts what a mock was told to return proves nothing.

## File naming & placement

- **Name new test files `*.test.ts`, never `*.spec.ts`** — and a new test file is
  `.test.ts` even when its own directory is full of legacy `.test.js`/`.spec.ts`
  siblings: the naming rule beats "match the neighbor". (A project skill may declare a
  repo-local exception; absent one, `.test.ts`.)
- **Colocate unit tests next to their subject** — `factor.ts` + `factor.test.ts`. Never a
  separate parallel test tree.
- **Scenario / end-to-end tests go in `__tests__/integration/`, one file per business
  scenario** — each file a distinct, nameable scenario, not a grab-bag.
- **Put shared test helpers under a `__tests__/` directory**, not loose next to source:
  fixture factories, arbitraries, assertion helpers.
- **Never commit test reports** (`junit.xml` and friends are gitignored).

## Fixture factories & assert helpers

- **Fixtures are `createTest<Entity>(params: Partial<T> = {})` functions with sane
  defaults plus an overrides bag** — not object literals, not class builders. A sequence
  generator (`nextId()`) hands out ids so fixtures don't collide.

  ```ts
  let _idSeq = 1000;
  const nextId = () => _idSeq++;

  export const createTestOrder = (params: Partial<Order> = {}): Order => ({
    id: createId(nextId()),
    discountRate: O.none,
    allowedTime: zeroMinutes,
    roundingMode: "exact" as const,
    isPoolable: true,
    lines: [],
    ...params,
  });
  ```

- **A fixture may throw on an invalid construction — that's a fixture bug, not a domain
  state.** The one `throw` in factories is scoped and intentional
  (`E.getOrElseW(() => { throw new Error("Quantity is invalid"); })`).
- **Assert helpers encapsulate unwrap + compare so test bodies stay declarative** — an
  `assertAmountValue(actual, 1234)` hides the unwrap and compares plain numbers so the
  runner shows a useful diff.
- **Integration tests own their fixtures inline** via small builders over the effect
  boundary, composed with `RTE.flatMap` — not a shared cross-file fixture library. Each
  file builds exactly the data it needs.
- **Type fixtures via an explicit type annotation, never `as` casts** (including
  `as unknown as`). Build a properly typed fixture, or use a typed id-constructing anchor
  (`const orderId = (id: number): OrderId => createId(id)`) over an inline `as OrderId`.

## Property-based tests (fast-check)

- **Pure-function laws get property tests via fast-check.** Arbitraries live alongside
  factories and accumulate in one shared `__tests__/arbitraries.ts` per level — append the
  new VO's arbitrary there rather than declaring it per test file.
- **A dedicated `describe('type class laws')` runs generic law checks** against the
  instances — `eq`/`ord` always, `semigroup`/`monoid` for summable VOs. Test every
  instance the VO declares.

  ```ts
  describe("factor", () => {
    describe("type class laws", () => {
      it("eq", () => eq(factorEq, factorArb));
      it("ord", () => ord(factorOrd, factorArb));
    });
    describe("property tests", () => {
      test.prop([factorNumberArb])("createFactor returns Right in [0, 1]", value => {
        pipe(createFactor(value), assertRight(identity));
      });
      test.prop([invalidFactorNumberArb])("createFactor returns Left outside [0, 1]", value => {
        pipe(createFactor(value), assertLeft());
      });
    });
  });
  ```

- **Pure calculation modules get a `describe('properties', ...)` block asserting
  algebraic relationships** (e.g. two calculation methods agree on the final result),
  alongside example-based tests.
- **A prism-based value object (construction can fail) must be verified with property
  tests.**

## describe / it phrasing & table-driven cases

- **`describe` names the subject or scenario group; `it`/`test` reads as a plain-English
  behavior assertion** ("Will successfully bulk assign multiple orders to a user").
  Nested `describe` splits by scenario shape.
- **Use `test.each` / `it.each` with a templated title for repetitive/table-driven cases**
  instead of duplicating blocks.
- **Regression tests carry the issue number + a short repro summary comment** directly
  above the `it`/`describe`.

## Assertion strategy

- **Negative paths assert the exact typed error tag/payload, never just "throws" or a
  snapshot** — `assertLeft(err => expect(err).toEqual({ type: 'MimeTypeNotFound' }))`. A
  snapshot or a bare `.toThrow()` hides which failure fired.
- **Assert the presence/shape of returned lists, not exact enumerated values,** so a test
  doesn't break every time the underlying reference list grows.
- **Reference shared constants in expectations instead of duplicating magic literals.**

## Mocking — mock the boundary, not the module tree

- **Mock only the boundary** — the adjacent package, the adjacent mapper — so the test
  exercises the function's own branching, not a mocked-out world.
- **Use shared mock helpers for cross-cutting concerns** (e.g. one shared feature-flag
  mock helper, not ad-hoc `isEnabled` stubs), and **write tests with a new feature flag
  always enabled**.
- **Put mocks common to all code in the global test setup; keep feature-specific mocks in
  their own test file.** Delete redundant manual mocks when a global mock already exists.
- **Do cleanup/teardown in `after` hooks so it runs even when the test body fails.**
  Remove leftover `console.log` from tests.

## UI selectors

- **Select by stable `data-testid`, never fragile hashed CSS classes** — put a
  `data-testid` on every interactive element you add; keep values concise and free of
  redundant noise. Use a shared `getByTestId(wrapper, id)` helper over ad-hoc finds. Gate
  each new UI branch with its own nested `describe` named after the feature.

## Pipeline behavior & type-level surface

- **Assert whole-flow/pipeline behavior only through integration scenarios, not brittle
  unit tests of intermediate stages.**
- **A `typecheck.test-d.ts` forces the type-level surface into the test run** — "types
  are behavior too":

  ```ts
  test("dummy test to trigger typecheck", () => {
    expectTypeOf(identity).toBeFunction();
  });
  ```
