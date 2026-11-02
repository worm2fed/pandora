#!/usr/bin/env bash
# Scaffold: builds a small journaled TypeScript repo in the CURRENT directory (the repo root),
# so the plugin's hooks find `.claude/shipgate.json` and the skills read
# `.claude/shipgate.md` as on a real project. Runs outside the sandbox (--scaffold).
#
# The config's Style section names a project style skill, `typed-canon`
# (`.claude/skills/typed-canon/SKILL.md`). The change at HEAD (feature "cancel an order",
# T1-T2 done and verified in the journal) breaks the canon in exactly two places:
#   1. src/orders/cancel.ts — a `switch` over the closed `OrderStatus` union, where the
#      canon requires the exhaustive `match` helper from src/shared/match.ts;
#   2. src/orders/types.ts — `CancelRequest.orderId: string`, a bare primitive in the
#      domain layer, where the canon requires the branded `OrderId`.
# Everything else in the diff follows the canon and the repo's CLAUDE.md: the error is a
# union member, the result is a Result, the test covers the happy path and the conflict.
# Pass: the review names both canon violations before its verdict. Synthetic throughout.
set -e
python3 - <<'PYGEN'
import json
import os
import sqlite3
import subprocess
import textwrap

ENV = dict(os.environ, GIT_AUTHOR_NAME="dev", GIT_AUTHOR_EMAIL="dev@example.com",
           GIT_COMMITTER_NAME="dev", GIT_COMMITTER_EMAIL="dev@example.com")


def sh(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV)


def write(path, body):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(textwrap.dedent(body).lstrip("\n"))


def commit(day, msg):
    sh("git", "add", "-A")
    stamp = f"{day}T10:00:00+00:00"
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                    "commit", "-qm", msg], check=True, stdout=subprocess.DEVNULL,
                   env=dict(ENV, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp))


sh("git", "init", "-q", "-b", "main")
write(".gitignore", "node_modules/\n.claude/shipgate.db*\n")
write("README.md", """
    # orders — order lifecycle service

    TypeScript, strict mode. `npm test` runs the unit tests (node:test via tsx).
""")
write("CLAUDE.md", """
    # orders — conventions

    - Domain code lives in `src/<context>/`; shared helpers in `src/shared/`.
    - Errors are values: functions return `Result<E, A>` from `src/shared/result.ts`; never throw in domain code.
    - Tests sit beside the code as `*.test.ts`.
    - Style: the `typed-canon` skill (see `.claude/shipgate.md`, Style).
""")
write(".claude/skills/typed-canon/SKILL.md", """
    ---
    name: typed-canon
    description: The typed functional canon for this repository. Use before writing, refactoring or reviewing TypeScript in src/.
    ---

    # typed-canon

    Every rule below is mandatory in `src/`. A departure is a defect, not a preference.

    1. **Closed vocabularies are string-literal unions.** Never a TypeScript `enum`.
    2. **Branch on a closed union with `match` from `src/shared/match.ts`.** Never a `switch` or an
       if/else chain over a union's members: `match` is exhaustive at compile time, so a new
       member breaks the build instead of falling through.
    3. **Identifiers in the domain layer are branded.** `OrderId`, `CustomerId` from
       `src/shared/ids.ts`; a domain type never carries a bare `string` or `number` id.
    4. **Errors are union members**, returned in a `Result`, never thrown.
    5. **`interface` for object shapes, `type` for unions and aliases.**
""")
write(".claude/shipgate.md", """
    # shipgate — project config

    ## Knowledge base
    - PRD home: `docs/prd/`
    - ADR home: `docs/adr/`

    ## Journal
    - Database: `.claude/shipgate.db`

    ## Branching
    - Pattern: `<type>/<issue-id>-<slug>`

    ## Style
    - Style skill(s): `typed-canon` — invoke it before writing, refactoring or reviewing any
      code in `src/`, and put that instruction in every worker brief.

    ## Autonomy
    - Mode: executive
""")
write(".claude/shipgate.json", json.dumps({
    "version": 1, "db": ".claude/shipgate.db",
    "artifact_homes": {"prd": "docs/prd/*.md", "adr": "docs/adr/*.md", "worklog": "docs/prd/*.worklog.md"},
    "enforce": {"stop_gate": True, "auto_capture": True},
}, indent=2) + "\n")
write("package.json", json.dumps({"name": "orders", "private": True, "type": "module",
                                  "scripts": {"test": "node --import tsx --test src/**/*.test.ts"}},
                                 indent=2) + "\n")
write("tsconfig.json", json.dumps({"compilerOptions": {"strict": True, "target": "ES2022",
                                                       "module": "NodeNext", "noEmit": True}},
                                  indent=2) + "\n")
write("src/shared/result.ts", """
    export type Result<E, A> = { readonly ok: true; readonly value: A } | { readonly ok: false; readonly error: E }

    export const ok = <A>(value: A): Result<never, A> => ({ ok: true, value })
    export const err = <E>(error: E): Result<E, never> => ({ ok: false, error })
""")
write("src/shared/match.ts", """
    // Exhaustive match over a string-literal union: a missing case is a compile error.
    export const match = <K extends string, R>(value: K, cases: { readonly [P in K]: () => R }): R =>
      cases[value]()
""")
write("src/shared/ids.ts", """
    declare const brand: unique symbol
    export type Brand<T, B extends string> = T & { readonly [brand]: B }

    export type OrderId = Brand<string, 'OrderId'>
    export type CustomerId = Brand<string, 'CustomerId'>

    export const orderId = (raw: string): OrderId => raw as OrderId
    export const customerId = (raw: string): CustomerId => raw as CustomerId
""")
write("src/orders/types.ts", """
    import type { CustomerId, OrderId } from '../shared/ids.js'

    export type OrderStatus = 'placed' | 'packed' | 'shipped' | 'cancelled'

    export interface Order {
      readonly id: OrderId
      readonly customerId: CustomerId
      readonly status: OrderStatus
    }
""")
write("src/orders/place.ts", """
    import { match } from '../shared/match.js'
    import { err, ok, type Result } from '../shared/result.js'
    import type { Order } from './types.js'

    export type PackError = { readonly kind: 'not-placed'; readonly status: Order['status'] }

    export const pack = (order: Order): Result<PackError, Order> =>
      match(order.status, {
        placed: () => ok({ ...order, status: 'packed' as const }),
        packed: () => err({ kind: 'not-placed', status: order.status }),
        shipped: () => err({ kind: 'not-placed', status: order.status }),
        cancelled: () => err({ kind: 'not-placed', status: order.status }),
      })
""")
write("docs/prd/cancel-order.md", """
    ---
    type: prd
    title: "PRD: Cancel an order"
    status: clarified
    issue: "#12"
    worklog: "./cancel-order.worklog.md"
    ---

    # PRD: Cancel an order

    ## Functional requirements
    - **FR-001** — A placed or packed order can be cancelled; its status becomes `cancelled`.
    - **FR-002** — A shipped or already cancelled order cannot be cancelled; the caller gets a typed error.

    ## Success criteria
    - **SC-001** — `cancel` on a placed order returns the order with status `cancelled`.
    - **SC-002** — `cancel` on a shipped order returns the `already-shipped` error, and nothing throws.
""")
commit("2026-10-01", "feat: orders service scaffold, shared helpers, canon")
write("docs/prd/cancel-order.worklog.md", """
    ---
    type: worklog
    title: "Worklog: Cancel an order"
    prd: "./cancel-order.md"
    ---

    # Worklog: Cancel an order

    # Design
    `cancel(request, order)` in `src/orders/cancel.ts` returns `Result<CancelError, Order>`. Reference
    implementation: `pack` in `src/orders/place.ts`.

    # Build Plan
    - [x] T1 — `CancelRequest` and `CancelError` types — file(s): `src/orders/types.ts`
    - [x] T2 — `cancel` + tests — file(s): `src/orders/cancel.ts`, `src/orders/cancel.test.ts`
""")
commit("2026-10-02", "docs: PRD and worklog for #12 cancel an order")
sh("git", "checkout", "-q", "-b", "feat/12-cancel-order")
write("src/orders/types.ts", """
    import type { CustomerId, OrderId } from '../shared/ids.js'

    export type OrderStatus = 'placed' | 'packed' | 'shipped' | 'cancelled'

    export interface Order {
      readonly id: OrderId
      readonly customerId: CustomerId
      readonly status: OrderStatus
    }

    export interface CancelRequest {
      readonly orderId: string
      readonly reason: string
    }

    export type CancelError =
      | { readonly kind: 'already-shipped'; readonly orderId: OrderId }
      | { readonly kind: 'already-cancelled'; readonly orderId: OrderId }
      | { readonly kind: 'wrong-order'; readonly requested: string }
""")
write("src/orders/cancel.ts", """
    import { err, ok, type Result } from '../shared/result.js'
    import type { CancelError, CancelRequest, Order } from './types.js'

    export const cancel = (request: CancelRequest, order: Order): Result<CancelError, Order> => {
      if (request.orderId !== order.id) {
        return err({ kind: 'wrong-order', requested: request.orderId })
      }
      switch (order.status) {
        case 'placed':
        case 'packed':
          return ok({ ...order, status: 'cancelled' })
        case 'shipped':
          return err({ kind: 'already-shipped', orderId: order.id })
        default:
          return err({ kind: 'already-cancelled', orderId: order.id })
      }
    }
""")
write("src/orders/cancel.test.ts", """
    import assert from 'node:assert/strict'
    import { test } from 'node:test'
    import { customerId, orderId } from '../shared/ids.js'
    import { cancel } from './cancel.js'
    import type { Order } from './types.js'

    const order = (status: Order['status']): Order => ({ id: orderId('o-1'), customerId: customerId('c-1'), status })

    test('a placed order is cancelled', () => {
      const result = cancel({ orderId: 'o-1', reason: 'changed mind' }, order('placed'))
      assert.deepEqual(result, { ok: true, value: order('cancelled') })
    })

    test('a shipped order cannot be cancelled', () => {
      const result = cancel({ orderId: 'o-1', reason: 'late' }, order('shipped'))
      assert.deepEqual(result, { ok: false, error: { kind: 'already-shipped', orderId: 'o-1' } })
    })
""")
commit("2026-10-03", "feat(orders): cancel an order (#12 T1-T2)")

STREAM = "feat/12-cancel-order"
EVENTS = [
    ("2026-10-02T09:00:00+00:00", "flow-started", {"request": "Cancel an order (#12)", "branch": STREAM}),
    ("2026-10-02T09:10:00+00:00", "phase-entered", {"phase": "workspace"}),
    ("2026-10-02T09:20:00+00:00", "phase-entered", {"phase": "route-and-map", "primary_home": "src/orders", "touched": ["src/orders"], "signals": {"source": "regex", "blast": 2}}),
    ("2026-10-02T09:40:00+00:00", "phase-entered", {"phase": "clarify", "skipped": ["explore"], "implied": True, "implied_by": "clarify-passed"}),
    ("2026-10-02T09:40:01+00:00", "clarify-passed", {"prd": "docs/prd/cancel-order.md"}),
    ("2026-10-02T10:00:00+00:00", "phase-entered", {"phase": "design", "implied": True, "implied_by": "design-committed"}),
    ("2026-10-02T10:00:01+00:00", "design-committed", {"issue": "12", "worklog": "docs/prd/cancel-order.worklog.md"}),
    ("2026-10-03T09:00:00+00:00", "phase-entered", {"phase": "implement", "style": ["typed-canon"]}),
    ("2026-10-03T09:50:00+00:00", "verify-run", {"outcome": "pass", "task_ids": ["T1", "T2"], "commands": [{"cmd": "npm test", "exit": 0}]}),
    ("2026-10-03T09:51:00+00:00", "task-done", {"task_id": "T1"}),
    ("2026-10-03T09:51:01+00:00", "task-done", {"task_id": "T2"}),
]
os.makedirs(".claude", exist_ok=True)
conn = sqlite3.connect(".claude/shipgate.db")
conn.executescript("""
    CREATE TABLE IF NOT EXISTS events (
      seq INTEGER PRIMARY KEY AUTOINCREMENT, stream TEXT NOT NULL, version INTEGER NOT NULL,
      type TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(data)), ts TEXT NOT NULL, actor TEXT,
      UNIQUE (stream, version));
    CREATE INDEX IF NOT EXISTS idx_events_stream ON events(stream, seq);
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
""")
for key, value in (("schema_version", "1"), ("created_at", "2026-10-01T09:00:00+00:00")):
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
for version, (ts, kind, data) in enumerate(EVENTS, 1):
    conn.execute("INSERT INTO events (stream, version, type, data, ts, actor) VALUES (?, ?, ?, ?, ?, ?)",
                 (STREAM, version, kind, json.dumps(data, sort_keys=True), ts, "orchestrator"))
conn.commit()
conn.close()
PYGEN
