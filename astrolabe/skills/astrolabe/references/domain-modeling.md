# Domain modeling with types

Design the domain shape before any behavior: entities, value objects, and branded ids
land first, in their own files, and the calculation/command logic is written against them
afterwards. Every meaning-bearing primitive is wrapped in a branded type with a smart
constructor, so a raw `number`/`string` never appears in a signature past the boundary.
"Kinds" are discriminated unions; absence is `Option`; failure is a typed `Either`.
Invariants live in smart constructors and type structure, not scattered runtime asserts.
The vocabulary (`create`/`unwrap`/`get`, `<x>Eq`/`<x>Ord`/`<x>Monoid`) is identical across
every value object, so a new VO reads as a copy of the last one.

## Types first, before behavior

**Design `entities/`, `valueObjects/`, and branded ids before you write a single line of
logic.** The founding commit of a domain package lays down the entity and value-object
modules, the branded ids, and the FP toolchain (fp-ts, newtype-ts, ts-pattern) — before
any calculation exists. The domain vocabulary and the toolchain arrive together, first.

**Put each concept in its own file, named for the concept.** Value objects go in
`valueObjects/` (things defined by their value: `Money`, `Factor`, rate configs); entities
go in `entities/` (things with identity: `Order`, `Shipment`, `Event`). String-literal
value-object types belong under `valueObjects/`, not `entities/`. Model a field as its own
value object in its own file the moment it carries rules of its own.

**An entity module holds the package's public surface only; internal derived types
(pipeline inputs, intermediate shapes) get their own module, even when they're
`Omit`/`Pick`-derived from the public type.** If the calculation seam consumes
`Omit<Order, 'priceBook' | 'settlementPolicy'>`, that type lives in its own module (e.g.
`entities/partition.ts`), not in `entities/order.ts`. Mixing it in blurs the boundary the
types exist to draw: the public type is what callers construct; the derived type is what
the internal seam consumes.

**Keep smart constructors and domain helpers next to the type they construct/operate on —
never in the command or service layer, and never stranded in a barrel.** The value-object
module is the canonical shape: type + `create*`/`to*` constructor + projections in one
file. A constructor that has drifted into a context's `index.ts` gets moved back beside
its type.

**A function's home is decided by the type of its parameter, not by who calls it.**
`primaryVendorId(lines: readonly OrderLine[])` belongs in `entities/orderLine.ts` even if
only one other module calls it — the parameter type owns the placement decision, not the
call site. Corollary: put a function directly beside the invariant-producer it depends on,
and name the invariant in its doc comment ("valid on any group produced by `groupByVendor`
— all lines in a group share one vendor").

## Branded newtypes for every meaning-bearing primitive

**Never pass a raw `number`/`string` where a domain meaning exists — wrap it in a
newtype.** `Money`, `Minutes`, `Factor`, `Quantity` are `Newtype<{...}, Decimal>` branded
with a `unique symbol`; entity ids are `Id<EntityName extends symbol>` branded by a unique
symbol so two id types can never be mixed at compile time:

```ts
export interface Id<EntityName extends symbol> extends Newtype<
  { readonly Id: unique symbol; readonly entityName: EntityName },
  number
> {}
export const createId = <EntityName extends symbol>(
  id: number,
): Id<EntityName> => isoId<EntityName>().wrap(id);
export const getId = <EntityName extends symbol>(id: Id<EntityName>): number =>
  isoId<EntityName>().unwrap(id);
```

This is the single most-repeated modeling rule in review practice: reuse the existing
branded id type instead of a plain number; use a shared `Email`-style value object instead
of a raw string; strong ids prevent silently mixing ids in complex joins.

**Only entities carry the branded symbol; value objects don't.** Prefer a context-local id
type where the schema belongs to that context; export the owning context's id type (or
define a thin entity) rather than passing a bare number across a boundary.

**Use a `prism` (not an `iso`) for a value object whose construction can fail, restricting
to the valid range.** A `Factor` restricted to `[0,1]` via a prism means an in-scope
`Factor` is provably valid — no use-site check:

```ts
export type Factor = Newtype<{ readonly Factor: unique symbol }, Decimal>;
const isFactor = (n: Decimal) => n.gte(0) && n.lte(1);
const prismFactor = prism<Factor>(isFactor);

export const createFactor = (
  n: Decimal | number,
): Either<InvalidFactor, Factor> =>
  pipe(coerceToDecimal(n), value =>
    pipe(
      prismFactor.getOption(value),
      E.fromOption(() =>
        pipe({ value: value.toNumber() }, createError("InvalidFactor")),
      ),
    ),
  );
```

Verify prism-based VOs with property tests (see the testing reference).

**`iso` and `prism` coexist on the same newtype**: the `prism` is for fallible
construction from arbitrary input; a separate `iso<X>()` builds literals that are valid by
construction (e.g. a Monoid's `empty`, a `Bounded` instance's `bottom`). Direction
matters: `prism.getOption` goes base→newtype (may fail); `iso.wrap` goes base→newtype
(always); `reverseGet`/`unwrap` go newtype→base.

**Reuse the codebase's shared kernel primitives — never hand-roll them per context**: a
`BaseError<'Tag'>`-style tagged-error interface, `createError('Tag')`/`constError('Tag')`
constructors, shared result shapes. If the codebase wraps a decimal library, import the
local re-export, not the npm package directly.

## The uniform value-object template

**Every value object exposes the same triad — `create<X>` / `unwrap<X>` (internal repr) /
`get<X>` (plain primitive) — plus type-class instances chosen by the VO's algebra, in the
same order, with the same section banners.** `<x>Eq`/`<x>Ord` always; then pick:
summable quantities (`Money`, `Minutes`) get `<x>Semigroup`/`<x>Monoid` + a `sum<X>` fold;
clamped ratios (`Factor`, `[0,1]`) get `Bounded` (`bottom`/`top`) instead — a clamped
value isn't meaningfully summable. **Before writing a new VO, read both archetypes**
(the summable one and the bounded one) and decide which algebra the domain intends; don't
blindly add a Monoid. `unwrap` returns the internal representation; `get` returns a plain
primitive:

```ts
export const createMoney: (n: Decimal | number) => Money = flow(
  coerceToDecimal,
  isoMoney.wrap,
);
export const unwrapMoney: (money: Money) => Decimal = isoMoney.unwrap;
export const getMoney: (money: Money) => number = flow(unwrapMoney, m =>
  m.toNumber(),
);
// -- Type class instances --
export const moneyEq: Eq.Eq<Money> = Eq.contramap(unwrapMoney)(decimalEq);
export const moneyOrd: Ord.Ord<Money> = Ord.contramap(unwrapMoney)(decimalOrd);
export const moneyMonoid: Monoid.Monoid<Money> = {
  ...moneySemigroup,
  empty: createMoney(0),
};
```

**Name instances in full — `<thing>Eq`, `<thing>Ord`, `<thing>Semigroup`,
`<thing>Monoid`.** Never abbreviate. Aggregation then becomes a fold
(`sumMoney = Monoid.concatAll(moneyMonoid)`), never a hand-rolled `reduce`.

**Reuse one validation function across the constructor and its predicate.** Don't
duplicate the range/shape check between `create*` and `is*`. Keep the same
VO/smart-constructor approach consistent across every VO in the codebase.

**Hide the FP machinery inside the VO module so calling code reads like a domain DSL** —
callers see `createMoney`/`addMoney`, not `iso`/`prism`.

## Smart-constructor split: `validate*` (Either) vs `create*` (Option)

**`validate<X>` returns `Either<Error, X>` for a strict domain rule; `create<X>` returns
`Option<X>` for permissive parsing of arbitrary input.** The same VO file carries both —
the `Either` form is used inside domain composition; the `Option` form parses external
strings:

```ts
export const validatePremiumTier = (
  tier: CustomerTier,
): Either<OrderError, PremiumTier> =>
  pipe(
    tier,
    E.fromPredicate(
      (t): t is PremiumTier => premiumTiers.includes(t),
      constError("InvalidPremiumTier"),
    ),
  );

export const createCustomerTier = (raw: string): Option<CustomerTier> =>
  match(raw)
    .with(...premiumTiers, ...standardTiers, t => O.some(t))
    .otherwise(() => O.none);
```

**Match a closed domain with `.exhaustive()`; reserve `.otherwise(() => O.none)` for a
best-effort parser where "no match" is legitimately `None`.** The error-to-transport
mapper is always `.exhaustive()` so a new variant fails to compile. Never defeat
`.exhaustive()` with a catch-all.

**All construction/validation logic lives inside the VO constructor, to guarantee the
invariant at the single point of creation** — never re-validate in the application layer.

## Compound value objects as `E.Do`/`E.apS` compositions

**Build a compound value object (a discriminated union with fields) via an
`Either`-returning factory that composes the narrower validators with `E.Do` / `E.apS`,**
dispatching on the discriminator and assembling field-by-field:

```ts
export type Discount = PercentageDiscount | FixedDiscount;
export const createDiscount = (kind: DiscountKind) =>
  match(kind)
    .with("percentage", () => createPercentageDiscount)
    .with("fixed", () => createFixedDiscount)
    .exhaustive();

export const createPercentageDiscount = (/* ...fields */): Either<
  PricingError,
  PercentageDiscount
> =>
  pipe(
    E.Do,
    E.apS("factor", validateFactor(rawFactor)),
    E.map(({ factor }) => ({ type: "percentage", factor /* ... */ })),
  );
```

## Discriminated unions & error modeling

**Model every domain "kind" as a discriminated union with an explicit tag field, not by
property presence.** Discriminate config unions by a `type`/`tag` field, never by
`'someKey' in options`.

**Error unions get a scope discriminator plus an attribution id, and unreachable variants
get pruned.** Key an error union on `scope` so a consumer can localize a failure to the
item that caused it:

```ts
export type PricingError = OrderScopedError | LineScopedError;
export type LineScopedError = (
  | RangeEndpointsNotFound
  | OverlappingRanges
  | ProvidedRateNotAllowed
) & { readonly scope: "line"; readonly lineId: LineId };
```

When variants prove unreachable, *remove* them — prune the type to true reachable states,
don't just add capability.

**Prefer one error type with a `reason` sub-union over many separate error constructors**
when the variants share a situation — it keeps the transport mapping's match narrow and
per-reason. Error tags are `PascalCase` failure sentences naming the condition
(`OverlappingRanges`, `NotEnoughRateSlices`), never the HTTP status.

## Entity lifecycle in the type system

**Model saved/unsaved in types, not with a nullable id field.** `Entity<Name>` has
`id: Some<Id<Name>>`; `Local<E>` has `id: Option<never>` (i.e. `None`);
`LocalOrPersisted<E>` is the union used in mapper signatures. `assignId` is the *only*
promotion path from `Local<E>` to `E`:

```ts
export interface Entity<Name extends symbol> {
  readonly id: Some<Id<Name>>;
}
export type Local<E> =
  E extends Entity<infer _>
    ? Omit<E, "id"> & { readonly id: Option<never> }
    : never;
export type LocalOrPersisted<E> =
  E extends Entity<infer Name>
    ? Omit<E, "id"> & { readonly id: Option<Id<Name>> }
    : never;
```

`Eq`/`Ord` for entities are generic factories (`createEq<T extends Entity<symbol>>()`)
comparing by unwrapped id value — not hand-rolled per entity.

## Pipeline stages as named types

**Give every pipeline stage a named type documented with what it represents, and export
only the boundary type.** The module boundary is the type boundary: a pricing pipeline
reads `CollisionResolvedStage` → `AllowanceBuiltStage` → `UsageCalculatedStage` →
`Distributed`; only the last is exported. Successive processing states of the same data
take transformation-state prefixes (`Compiled*`/`Enriched*`/`Resolved*`; `*Stage` for
snapshots; `*Unwrapped` for plain-primitive projections).

## Naming

**Name types and functions by role/intent, drop implementation suffixes.** Domain nouns
carry no `Impl`/Hungarian/`I`-prefix. Command and query *types* are named after the intent
with no `Command`/`Query`/`Options`/`Params`/`Dto` postfix on the function — the function
is the plain verb (`mergeOrders`, `bulkAssign`). Use a `Schema` postfix only to
distinguish a DB-row schema from its entity. DTOs map presentation↔domain only, named for
the read model (`OrderListItemDto`), never a generic bag.

**Use a string-literal union for a closed set of string values — never a TS `enum`.**
Declare the literals once `as const` and derive the type:

```ts
export const orderStatuses = [
  "Draft",
  "Submitted",
  "Settled",
  "Withdrawn",
] as const;
export type OrderStatus = (typeof orderStatuses)[number];
```

One exception: bridging a legacy enum, documented at the site.

**Name a projection/accessor as a noun phrase in the domain's own vocabulary, never after
an operation.** An accessor named with a verb-like word ("partition", "resolve") parses as
an action on first read and collides in meaning with the functions that actually perform
that action. An accessor's name must never claim to do what a nearby function does.

**When key and label differ, model it as a single `as const` record (key=value,
value=label) and derive the list/types from it** — never parallel enum + label structures.
Use stable codes, not human labels, for value-object enums. Give enums/constants specific
scoped names.

## One way to say "no value"

**Prefer a required `field: X | null` over an optional `field?: X | null` on a model
type.** The optional-plus-null dual gives a construction site two ways to omit the field
(`undefined` by absence, `null` explicitly) and forces every reader back onto a loose
`!= null` check to cover both. A required `| null` field means absence normalizes to
`null` **once**, at each type's declared boundary, and everything downstream compares with
strict `=== null` / `!== null`. Spell the boundary out in the field's doc comment ("a raw
legacy row that lacks the property is normalized to `null` at the boundary — never left
absent past that point").

## Literal unions replace legacy untyped enum objects, in new code

**When a new model field needs a closed string set that a legacy runtime `*Map` object
already describes, declare the literal union on the owning model type instead of importing
the map.** Verify the map's runtime values match the literals you're about to hardcode —
don't guess the strings — and record the verification in the doc comment. **Legacy call
sites keep using the map** — this is a new-code convention, not a retrofit.

## Canonical type ownership across bounded contexts

**The data-owning context defines the model type; a consuming context imports it and, only
where genuinely needed, narrows it via `interface X extends Canonical { ... }` — never
redeclares an independent copy.** The narrowing only adds what the consuming seam actually
needs beyond the canonical shape: widen a `number | null` to non-null `number` where rows
provably arrive resolved, add a consumer-only field the owner's type doesn't carry.
**The import runs consumer → owner at the border crossing, never the reverse.** Put a
comment at the import naming the ownership direction, and a doc comment on the narrowed
interface explaining why each delta is safe.

## Invariants in structure; `interface` vs `type`

**Encode invariants in smart constructors and type structure — not scattered runtime
asserts, and not comments alone.** A `[0,1]` bound is the prism; an overlap policy is a
documented solver, not a use-site check. There is no `throw` in domain code (test fixtures
aside).

**Declare every entity, value object, and command as `readonly`** — `readonly` on every
field and array type.

**`interface` for object/data shapes (entities, VOs, config); `type` reserved for unions,
aliases, and function signatures.**

## Curated barrel files

**A context's `index.ts` hand-lists its re-exports under section banners — never
`export *`.** Group exports as `// -- Entities --`, `// -- Value objects --`,
`// -- Result shape --`, with the context's entry point at the top. A context's `index.ts`
is its only public surface; cross-context imports go through it.

**The barrel is the entry point + exports; a helper function accumulating there is drift,
not a home.** Move it out to the module owning the type it operates on; the barrel only
imports and re-exports.
