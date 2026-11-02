#!/usr/bin/env bash
# Scaffold: builds a small journaled TypeScript repo in the CURRENT directory (the repo root).
# Runs outside the sandbox (--scaffold). Synthetic throughout.
#
# Graph arm only: run with `codegraph` on PATH (see the evals README, "Code-graph arm"), so
# signals.py reads `"source": "graph"`. The journal already holds the stream's
# route-and-map entry with graph signals, a design-committed and two verified tasks: the
# flow is at review. The question is whether the graph still feeds the flow past
# route-and-map: the review must dispatch from the risk ranking and record it on the
# verdict (`review-verdict.ranking`, source graph).
#
# The change at HEAD touches three files. src/billing/invoice.ts is the hot one: 10 of its
# 14 commits (HEAD included) are fixes, and 5 modules import it. src/billing/format.ts and
# src/reports/labels.ts have one commit each and no fixes.
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


def append(path, text):
    with open(path, "a") as fh:
        fh.write(text)


def commit(day, msg):
    sh("git", "add", "-A")
    stamp = f"{day}T10:00:00+00:00"
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                    "commit", "-qm", msg], check=True, stdout=subprocess.DEVNULL,
                   env=dict(ENV, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp))


sh("git", "init", "-q", "-b", "main")
write(".gitignore", "node_modules/\n.claude/shipgate.db*\n.codegraph/\n")
write("README.md", "# billing — invoices and reports\n\nTypeScript. `npm test` runs the unit tests.\n")
write("CLAUDE.md", """
    # billing — conventions

    - Money is integer cents; format only through `src/billing/format.ts`.
    - Tests sit beside the code as `*.test.ts`.
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

    ## Autonomy
    - Mode: executive
""")
write(".claude/shipgate.json", json.dumps({
    "version": 1, "db": ".claude/shipgate.db",
    "artifact_homes": {"prd": "docs/prd/*.md", "adr": "docs/adr/*.md", "worklog": "docs/prd/*.worklog.md"},
    "enforce": {"stop_gate": True, "auto_capture": True},
}, indent=2) + "\n")
write("package.json", json.dumps({"name": "billing", "private": True, "type": "module",
                                  "scripts": {"test": "node --import tsx --test src/**/*.test.ts"}},
                                 indent=2) + "\n")
write("src/billing/format.ts", """
    export const formatCents = (cents: number): string =>
      `${Math.trunc(cents / 100)}.${String(Math.abs(cents % 100)).padStart(2, '0')}`
""")
write("src/billing/tax.ts", """
    export const taxCents = (netCents: number, ratePercent: number): number =>
      Math.round((netCents * ratePercent) / 100)
""")
write("src/billing/invoice.ts", """
    import { taxCents } from './tax.js'

    export interface Line {
      readonly description: string
      readonly quantity: number
      readonly unitCents: number
    }

    export interface Invoice {
      readonly number: string
      readonly lines: readonly Line[]
      readonly taxPercent: number
    }

    export const netCents = (invoice: Invoice): number =>
      invoice.lines.reduce((sum, line) => sum + line.quantity * line.unitCents, 0)

    export const totalCents = (invoice: Invoice): number =>
      netCents(invoice) + taxCents(netCents(invoice), invoice.taxPercent)
""")
write("src/reports/labels.ts", """
    export const columnLabels = ['Invoice', 'Net', 'Total'] as const
""")
write("src/reports/summary.ts", """
    import { formatCents } from '../billing/format.js'
    import { netCents, totalCents, type Invoice } from '../billing/invoice.js'
    import { columnLabels } from './labels.js'

    export const summaryRows = (invoices: readonly Invoice[]): string[][] => [
      [...columnLabels],
      ...invoices.map((i) => [i.number, formatCents(netCents(i)), formatCents(totalCents(i))]),
    ]
""")
write("src/reports/aging.ts", """
    import { totalCents, type Invoice } from '../billing/invoice.js'

    export const outstandingCents = (invoices: readonly Invoice[]): number =>
      invoices.reduce((sum, i) => sum + totalCents(i), 0)
""")
write("src/api/handlers.ts", """
    import { totalCents, type Invoice } from '../billing/invoice.js'

    export const invoiceTotal = (invoice: Invoice): { total: number } => ({ total: totalCents(invoice) })
""")
write("src/api/export.ts", """
    import { netCents, type Invoice } from '../billing/invoice.js'

    export const exportNet = (invoices: readonly Invoice[]): number[] => invoices.map(netCents)
""")
write("src/billing/invoice.test.ts", """
    import assert from 'node:assert/strict'
    import { test } from 'node:test'
    import { totalCents } from './invoice.js'

    test('total adds tax to the net', () => {
      assert.equal(totalCents({ number: 'I-1', taxPercent: 20, lines: [{ description: 'a', quantity: 2, unitCents: 500 }] }), 1200)
    })
""")
commit("2026-06-01", "feat: billing scaffold — invoices, tax, format, reports, api")
fixes = ["fix(invoice): net ignored quantity", "fix(invoice): tax on an empty invoice",
         "fix(invoice): rounding of half cents", "fix(invoice): negative quantity accepted",
         "fix(invoice): total counted tax twice", "fix(invoice): zero tax percent",
         "fix(invoice): line order changed the total", "fix(invoice): large totals overflowed",
         "fix(invoice): credit lines", "fix(invoice): tax percent as a fraction"]
features = ["feat(invoice): line descriptions", "refactor(invoice): name the net"]
for n, msg in enumerate(fixes + features):
    append("src/billing/invoice.ts", f"\n// {msg}\n")
    commit(f"2026-{6 + n // 4:02d}-{(n % 4) * 7 + 3:02d}", msg)
write("docs/prd/invoice-discounts.md", """
    ---
    type: prd
    title: "PRD: Invoice discounts"
    status: clarified
    issue: "#21"
    worklog: "./invoice-discounts.worklog.md"
    ---

    # PRD: Invoice discounts

    - **FR-001** — An invoice may carry a discount percent; the net is reduced by it before tax.
    - **FR-002** — Reports show the discounted net.
    - **SC-001** — A 10% discount on a 1000-cent net with 20% tax totals 1080 cents.
""")
write("docs/prd/invoice-discounts.worklog.md", """
    ---
    type: worklog
    title: "Worklog: Invoice discounts"
    prd: "./invoice-discounts.md"
    ---

    # Worklog: Invoice discounts

    # Build Plan
    - [x] T1 — discount on `Invoice`, applied in `netCents` — file(s): `src/billing/invoice.ts`
    - [x] T2 — report labels and format helper — file(s): `src/reports/labels.ts`, `src/billing/format.ts`
""")
commit("2026-09-20", "docs: PRD and worklog for #21 invoice discounts")
sh("git", "checkout", "-q", "-b", "feat/21-invoice-discounts")
write("src/billing/invoice.ts", open("src/billing/invoice.ts").read().replace(
    "  readonly taxPercent: number\n}",
    "  readonly taxPercent: number\n  readonly discountPercent?: number\n}").replace(
    "export const netCents = (invoice: Invoice): number =>\n  invoice.lines.reduce((sum, line) => sum + line.quantity * line.unitCents, 0)",
    "export const netCents = (invoice: Invoice): number => {\n  const gross = invoice.lines.reduce((sum, line) => sum + line.quantity * line.unitCents, 0)\n  return gross - Math.round((gross * (invoice.discountPercent ?? 0)) / 100)\n}"))
write("src/reports/labels.ts", "export const columnLabels = ['Invoice', 'Net (after discount)', 'Total'] as const\n")
append("src/billing/format.ts", "\nexport const formatPercent = (percent: number): string => `${percent}%`\n")
commit("2026-09-22", "feat(invoice): discount percent (#21 T1-T2)")

STREAM = "feat/21-invoice-discounts"
SIGNALS = {"source": "graph", "blast": 6, "tests": 1,
           "modules": {"src/billing": {"churn": "top", "fix": "top", "fan_in": "top"}}}
EVENTS = [
    ("2026-09-20T09:00:00+00:00", "flow-started", {"request": "Invoice discounts (#21)", "branch": STREAM}),
    ("2026-09-20T09:05:00+00:00", "phase-entered", {"phase": "workspace"}),
    ("2026-09-20T09:20:00+00:00", "phase-entered", {"phase": "route-and-map", "primary_home": "src/billing", "touched": ["src/billing", "src/reports"], "signals": SIGNALS}),
    ("2026-09-20T09:40:00+00:00", "phase-entered", {"phase": "clarify", "skipped": ["explore"], "implied": True, "implied_by": "clarify-passed"}),
    ("2026-09-20T09:40:01+00:00", "clarify-passed", {"prd": "docs/prd/invoice-discounts.md"}),
    ("2026-09-20T10:00:00+00:00", "phase-entered", {"phase": "design", "implied": True, "implied_by": "design-committed"}),
    ("2026-09-20T10:00:01+00:00", "design-committed", {"issue": "21", "worklog": "docs/prd/invoice-discounts.worklog.md"}),
    ("2026-09-22T09:00:00+00:00", "phase-entered", {"phase": "implement", "style": []}),
    ("2026-09-22T09:50:00+00:00", "verify-run", {"outcome": "pass", "task_ids": ["T1", "T2"], "commands": [{"cmd": "npm test", "exit": 0}]}),
    ("2026-09-22T09:51:00+00:00", "task-done", {"task_id": "T1"}),
    ("2026-09-22T09:51:01+00:00", "task-done", {"task_id": "T2"}),
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
for key, value in (("schema_version", "1"), ("created_at", "2026-09-20T09:00:00+00:00")):
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
for version, (ts, kind, data) in enumerate(EVENTS, 1):
    conn.execute("INSERT INTO events (stream, version, type, data, ts, actor) VALUES (?, ?, ?, ?, ?, ?)",
                 (STREAM, version, kind, json.dumps(data, sort_keys=True), ts, "orchestrator"))
conn.commit()
conn.close()
PYGEN
