// The narrowing kernel shared by the pure modules: JSON from journal.py, a workflow return
// and a stored value arrive as `unknown`, and these helpers narrow it. A helper returns null
// for a value of another shape, never a fallback; a decoder returns the failure at the path
// it stopped at. No `$` here. `Brand` and `ShapeError` live in `types/index.d.ts`, because the
// $.state contract holds them and may not import.

import type { ShapeError } from '../types'

/** Success with a value, or failure with a typed error: astrolabe's `Either`, hand-rolled because a mod imports only `claude-code`. */
export type Result<E, A> = { readonly ok: true; readonly value: A } | { readonly ok: false; readonly error: E }

/** A success. */
export const ok = <A>(value: A): Result<never, A> => ({ ok: true, value })

/** A failure. */
export const err = <E>(error: E): Result<E, never> => ({ ok: false, error })

/**
 * The `default` of a `switch` that handled every member of a union: `value` is `never` there,
 * so a member added to the union is a compile error at the call. Reached at run time only by
 * a value the types ruled out.
 */
export const absurd = (value: never): never => {
  throw new Error(`shipgate-hud: unexpected value ${JSON.stringify(value)}`)
}

/** Why a text is not JSON: the parser's message. */
export interface ParseError {
  readonly message: string
}

/**
 * The text parsed as JSON, or why it is not JSON. One of the two places a `try` may stand
 * (ADR 0006): `JSON.parse` throws, and this turns the throw into a value.
 */
export function parseJson(text: string): Result<ParseError, unknown> {
  try {
    const value: unknown = JSON.parse(text)
    return ok(value)
  } catch (error) {
    return err({ message: error instanceof Error ? error.message : String(error) })
  }
}

/** A JSON object as the narrowing helpers hand it on: its values still `unknown`. */
export type JsonRecord = Readonly<Record<string, unknown>>

/** A plain object; an array or null is not one. */
export const isRecord = (value: unknown): value is JsonRecord => typeof value === 'object' && value !== null && !Array.isArray(value)

/** The value when it is a plain object, else null. */
export const recordOf = (value: unknown): JsonRecord | null => (isRecord(value) ? value : null)

/** The value when it is an array, else null. */
export const listOf = (value: unknown): readonly unknown[] | null => (Array.isArray(value) ? value : null)

/** The value when it is a string, else null. */
export const stringOf = (value: unknown): string | null => (typeof value === 'string' ? value : null)

/** The value when it is a finite number, else null. */
export const numberOf = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)

/** The value when it is a boolean, else null. */
export const booleanOf = (value: unknown): boolean | null => (typeof value === 'boolean' ? value : null)

/** The value when it is an array of strings only, else null: one entry of another type fails the whole list. */
export const stringListOf = (value: unknown): readonly string[] | null =>
  Array.isArray(value) && value.every((entry): entry is string => typeof entry === 'string') ? value : null

// ---------------------------------------------------------------------------------------
// Decoders: a value of the expected shape, or the failure at the path it stopped at. One
// copy for journal.ts and review.ts.
// ---------------------------------------------------------------------------------------

/** A decoded value, or where it did not have the expected shape. */
export type Decoded<A> = Result<ShapeError, A>

/** A decoder: the value at `path` decoded, or the failure there. */
export type Decoder<A> = (value: unknown, path: string) => Decoded<A>

/** The failure at `path`, where `expected` was not found. */
export const fail = (path: string, expected: string): Decoded<never> => err({ path, expected })

/** Is `key` one of the table's keys? Own keys only, so `constructor` is none. */
export const isKeyOf = <K extends string>(table: Readonly<Record<K, true>>, key: string): key is K => Object.hasOwn(table, key)

/** The value as a member of the table's union, or the failure at `path`. */
export const decodeMember = <K extends string>(table: Readonly<Record<K, true>>, value: unknown, path: string, expected: string): Decoded<K> => {
  const text = stringOf(value)
  return text !== null && isKeyOf(table, text) ? ok(text) : fail(path, expected)
}

/** Every entry of a list decoded, in order, or the first entry's failure. */
export const decodeEach = <A>(list: readonly unknown[], path: string, decode: Decoder<A>): Decoded<readonly A[]> =>
  list.reduce<Decoded<readonly A[]>>((done, item, index) => {
    if (!done.ok) return done
    const one = decode(item, `${path}[${index}]`)
    return one.ok ? ok([...done.value, one.value]) : one
  }, ok([]))

/** A list whose every entry decodes, or the failure at `path` (not a list) or at the first bad entry. */
export const decodeList = <A>(value: unknown, path: string, decode: Decoder<A>): Decoded<readonly A[]> => {
  const list = listOf(value)
  return list === null ? fail(path, 'an array') : decodeEach(list, path, decode)
}

/** A plain object, or the failure at `path`. */
export const decodeRecord = (value: unknown, path: string): Decoded<JsonRecord> => {
  const record = recordOf(value)
  return record === null ? fail(path, 'an object') : ok(record)
}
