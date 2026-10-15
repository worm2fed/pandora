// Pure JSON narrowing shared by position.ts and review.ts: journal events and workflow
// returns arrive as `unknown`. No `$` here.

export type JsonRecord = Record<string, unknown>

/** A plain object; an array or null is not one. */
export const isRecord = (value: unknown): value is JsonRecord => typeof value === 'object' && value !== null && !Array.isArray(value)

/** The value as an object; anything else (an array, null, a scalar) as `{}`. */
export const asRecord = (value: unknown): JsonRecord => (isRecord(value) ? value : {})

/** The value when it is a string, else `fallback`. */
export const asString = (value: unknown, fallback = ''): string => (typeof value === 'string' ? value : fallback)

/** The string entries of an array; [] for anything else. */
export const asStringList = (value: unknown): string[] => (Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [])
