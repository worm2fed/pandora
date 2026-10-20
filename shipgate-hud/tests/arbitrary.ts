// Property tests without a library: a mod imports only `claude-code`, so fast-check is not
// available (HUD ADR 0006). A seeded PRNG, small generators built on it, and `forAll`, which
// runs a law over generated inputs and names the seed and the input of the first failure.

/** A source of numbers in [0, 1), the same sequence for the same seed. */
export interface Rng {
  readonly next: () => number
}

/** mulberry32: a 32-bit seeded PRNG, small and fast; not for anything but tests. */
export function mulberry32(seed: number): Rng {
  // the generator's one piece of state: the next call's seed
  let state = seed >>> 0
  return {
    next: () => {
      state = (state + 0x6d2b79f5) >>> 0
      const mixed = Math.imul(state ^ (state >>> 15), state | 1)
      const spread = mixed ^ (mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61))
      return ((spread ^ (spread >>> 14)) >>> 0) / 4294967296
    },
  }
}

/** A generator: an input drawn from the rng. */
export type Gen<A> = (rng: Rng) => A

/** An integer in [min, max], both included. */
export const int =
  (min: number, max: number): Gen<number> =>
  rng =>
    min + Math.floor(rng.next() * (max - min + 1))

/** True or false, evenly. */
export const bool: Gen<boolean> = rng => rng.next() < 0.5

/** One of the items, evenly; the list must not be empty. */
export const pick =
  <A>(items: readonly [A, ...A[]]): Gen<A> =>
  rng =>
    items[Math.floor(rng.next() * items.length)] ?? items[0]

/** A list of `min` to `max` values of `gen`. */
export const listOf =
  <A>(gen: Gen<A>, min: number, max: number): Gen<readonly A[]> =>
  rng =>
    Array.from({ length: int(min, max)(rng) }, () => gen(rng))

/** A string of `min` to `max` characters drawn from `alphabet`. */
export const stringOf =
  (alphabet: string, min: number, max: number): Gen<string> =>
  rng => {
    const chars = [...alphabet]
    return Array.from({ length: int(min, max)(rng) }, () => chars[Math.floor(rng.next() * chars.length)] ?? '').join('')
  }

/** `gen`'s value, or null one time in `oneIn`. */
export const orNull =
  <A>(gen: Gen<A>, oneIn = 4): Gen<A | null> =>
  rng =>
    rng.next() < 1 / oneIn ? null : gen(rng)

/** The seed of run `index` of a forAll seeded `seed`: each run replays alone from it. */
export const runSeed = (seed: number, index: number): number => (seed + Math.imul(index, 0x9e3779b9)) >>> 0

/** An input as a failure names it: JSON, or its text when JSON cannot hold it. */
const shown = (value: unknown): string => {
  try {
    return JSON.stringify(value) ?? String(value)
  } catch {
    return String(value)
  }
}

/**
 * Runs `law` on `runs` inputs drawn by `gen`, run i from its own seed (`runSeed(seed, i)`). A
 * law fails by returning false or by throwing (an `expect` that does not hold); the first
 * failure throws an error naming the seed, the run, the run's own seed (so
 * `forAll(thatSeed, 1, gen, law)` replays it) and the input.
 */
export function forAll<A>(seed: number, runs: number, gen: Gen<A>, law: (input: A) => boolean | void): void {
  for (let index = 0; index < runs; index += 1) {
    const own = runSeed(seed, index)
    const input = gen(mulberry32(own))
    const failure = ((): string | null => {
      try {
        return law(input) === false ? 'the law returned false' : null
      } catch (error) {
        return error instanceof Error ? error.message : String(error)
      }
    })()
    if (failure !== null) {
      throw new Error(`forAll: seed ${seed}, run ${index} of ${runs} (replay: forAll(${own}, 1, …)) failed: ${failure}\ninput: ${shown(input)}`)
    }
  }
}
